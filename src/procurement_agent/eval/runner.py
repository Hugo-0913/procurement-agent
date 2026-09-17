from __future__ import annotations

import argparse
import json
import threading
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import yaml

from procurement_agent.agents.config import load_agents_config
from procurement_agent.agents.coordinator import CoordinatorDeps, build_handlers
from procurement_agent.agents.offline import offline_model_factory
from procurement_agent.config import ProcurementConfig, load_procurement_config
from procurement_agent.db.models import init_db, seed_demo_data
from procurement_agent.erp.faults import FaultRegistry
from procurement_agent.erp.repository import ErpRepository
from procurement_agent.eval import metrics
from procurement_agent.memory.store import MemoryStore
from procurement_agent.middleware.context_summarizer import ContextSummarizer
from procurement_agent.sandbox.policy import PolicyEngine
from procurement_agent.skills_loader import SkillRegistry
from procurement_agent.state.graph import TaskRunner, build_stage_graph
from procurement_agent.state.models import TaskState
from procurement_agent.state.store import TaskStore

DEFAULT_CASES_PATH = Path(__file__).with_name("cases.yaml")
DEFAULT_RESULT_PATH = Path("eval_results") / "latest.json"


@dataclass(frozen=True)
class EvalCase:
    id: str
    request_text: str
    quantity: int
    faults: dict[str, bool] = field(default_factory=dict)
    expect_state: str = "COMPLETED"
    expect_approval: bool = False


@dataclass
class EvalReport:
    status: str = "idle"
    total: int = 0
    success_count: int = 0
    success_rate: float = 0.0
    intervention_count: int = 0
    intervention_rate: float = 0.0
    avg_duration_ms: float = 0.0
    token_peak: int = 0
    token_mean: float = 0.0
    token_total_mean: float = 0.0
    token_total_max: int = 0
    delegation_framework: int = 0
    delegation_fallback: int = 0
    context_reduction_rate: float = 0.0
    context_before_tokens: int = 0
    context_after_tokens: int = 0
    failures: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def load_cases(path: Path | None = None) -> list[EvalCase]:
    target = Path(path) if path is not None else DEFAULT_CASES_PATH
    raw = yaml.safe_load(target.read_text(encoding="utf-8")) or []
    cases = [
        EvalCase(
            id=str(item["id"]),
            request_text=str(item["request_text"]),
            quantity=int(item.get("quantity", 50)),
            faults=dict(item.get("faults") or {}),
            expect_state=str(item.get("expect_state", "COMPLETED")),
            expect_approval=bool(item.get("expect_approval", False)),
        )
        for item in raw
    ]
    ids = [case.id for case in cases]
    if len(ids) != len(set(ids)):
        raise ValueError("用例 id 存在重复")
    return cases


def _parse_response(quantity: int) -> str:
    return json.dumps(
        {
            "material_name": "A4 纸",
            "quantity": quantity,
            "unit": "箱",
            "expected_date": None,
            "budget": None,
            "cost_center": "CC-1001",
            "note": None,
        },
        ensure_ascii=False,
    )


def measure_context_reduction(
    config: ProcurementConfig | None = None,
    tool_results: int = 12,
    payload_chars: int = 1500,
) -> tuple[int, int, float]:
    """用可复现的长对话测量上下文压缩效果，返回 (压缩前, 压缩后, 压缩比例)。"""
    from dataclasses import replace

    from procurement_agent.middleware.context_summarizer import ContextSummarizer

    base = config or load_procurement_config()
    # 用较低的阈值触发压缩，模拟长任务达到阈值后的行为
    low_threshold = replace(base, context_token_threshold=2000)
    summarizer = ContextSummarizer(
        low_threshold, offline_model_factory("压缩后的阶段结论摘要")
    )
    messages = [
        {
            "role": "tool",
            "content": json.dumps(
                {
                    "step": f"工具返回 {index}",
                    "detail": "A" * payload_chars,
                },
                ensure_ascii=False,
            ),
        }
        for index in range(tool_results)
    ]
    essential = {
        "material_name": "A4 纸",
        "quantity": 50,
        "cost_center": "CC-1001",
        "stage_conclusions": ["资质核验完成", "比价完成"],
    }
    _, summary = summarizer.maybe_summarize(messages, essential)
    if summary is None:  # pragma: no cover - 阈值配置足以触发
        before = summarizer.estimate_messages(messages, essential)
        return before, before, 0.0
    reduction = 1 - summary.after_tokens / summary.before_tokens
    return summary.before_tokens, summary.after_tokens, round(reduction, 4)


def _run_single_case(
    case: EvalCase,
    workspace: Path,
    config: ProcurementConfig,
    model_factory=None,
) -> dict[str, Any]:
    case_dir = workspace / case.id
    case_dir.mkdir(parents=True, exist_ok=True)
    engine = init_db(case_dir / "erp.db")
    seed_demo_data(engine)
    faults = FaultRegistry(engine)
    for flag, enabled in case.faults.items():
        faults.set(flag, enabled)

    repo = ErpRepository(engine, faults)
    store = TaskStore(engine)
    skills = SkillRegistry()
    # 默认不传固定脚本：让评测真正走一遍规则解析器，而不是复用预先给定的解析结果
    factory = model_factory or offline_model_factory()
    deps = CoordinatorDeps(
        repo=repo,
        store=store,
        config=config,
        agents_config=load_agents_config(),
        skills=skills,
        policy=PolicyEngine(config),
        model_factory=factory,
        memory=MemoryStore(engine, config),
        summarizer=ContextSummarizer(config, factory),
    )
    graph = build_stage_graph(store, build_handlers(deps), config)
    runner = TaskRunner(store, graph)

    started = time.perf_counter()
    task_id = runner.start(case.request_text)
    record = store.get_task(task_id)
    events = store.list_events(task_id)
    approval_requested = any(event.event_type == "approval_requested" for event in events)
    delegation_modes = [
        event.payload.get("mode")
        for event in events
        if event.event_type == "delegation_result"
    ]
    if record.state is TaskState.AWAITING_APPROVAL and case.expect_state == "AWAITING_APPROVAL":
        pass
    duration_ms = round((time.perf_counter() - started) * 1000, 2)

    return {
        "case_id": case.id,
        "task_id": task_id,
        "expect_state": case.expect_state,
        "actual_state": record.state.value,
        "expect_approval": case.expect_approval,
        "approval_requested": approval_requested,
        "duration_ms": duration_ms,
        "token_peak": int(record.token_usage.get("peak", 0)),
        "token_total": int(record.token_usage.get("total", 0)),
        "delegation_framework": sum(1 for mode in delegation_modes if mode == "framework"),
        "delegation_fallback": sum(1 for mode in delegation_modes if mode == "fallback"),
        "success": record.state.value == case.expect_state
        and approval_requested == case.expect_approval,
    }


def run_eval(
    cases: list[EvalCase],
    workspace: Path,
    config: ProcurementConfig | None = None,
    model_factory=None,
) -> EvalReport:
    cfg = config or load_procurement_config()
    workspace = Path(workspace)
    workspace.mkdir(parents=True, exist_ok=True)
    results = [_run_single_case(case, workspace, cfg, model_factory) for case in cases]

    report = EvalReport(status="finished", total=len(results))
    report.success_count = sum(1 for item in results if item["success"])
    report.success_rate = round(metrics.success_rate([item["success"] for item in results]), 4)
    interventions = [item["approval_requested"] for item in results]
    report.intervention_count = sum(1 for item in interventions if item)
    report.intervention_rate = round(metrics.intervention_rate(interventions), 4)
    report.avg_duration_ms = metrics.average_duration([item["duration_ms"] for item in results])
    report.token_peak = metrics.token_peak([item["token_peak"] for item in results])
    report.token_mean = metrics.token_mean([item["token_peak"] for item in results])
    totals = [item["token_total"] for item in results]
    report.token_total_mean = round(metrics.average_duration(totals), 2)
    report.token_total_max = max(totals) if totals else 0
    report.delegation_framework = sum(item["delegation_framework"] for item in results)
    report.delegation_fallback = sum(item["delegation_fallback"] for item in results)
    before, after, reduction = measure_context_reduction(cfg)
    report.context_before_tokens = before
    report.context_after_tokens = after
    report.context_reduction_rate = reduction
    report.failures = [item for item in results if not item["success"]]
    return report


class EvalRunner:
    """Web 层使用的评测运行器：后台线程执行并缓存最新报告。"""

    def __init__(
        self,
        cases_path: Path | None = None,
        workspace: Path | None = None,
        output_path: Path | None = None,
    ) -> None:
        self.cases_path = cases_path
        self.workspace = Path(workspace) if workspace else Path("eval_results") / "runs"
        self.output_path = Path(output_path) if output_path else DEFAULT_RESULT_PATH
        self._report = EvalReport(status="idle")
        self._lock = threading.Lock()

    def status(self) -> str:
        with self._lock:
            return self._report.status

    def latest(self) -> dict[str, Any]:
        with self._lock:
            return self._report.to_dict()

    def _execute(self) -> None:
        try:
            cases = load_cases(self.cases_path)
            report = run_eval(cases, self.workspace)
        except Exception as exc:  # noqa: BLE001
            report = EvalReport(status="failed", failures=[{"case_id": "-", "error": str(exc)}])
        with self._lock:
            self._report = report
        self.output_path.parent.mkdir(parents=True, exist_ok=True)
        self.output_path.write_text(
            json.dumps(report.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def start(self) -> None:
        with self._lock:
            if self._report.status == "running":
                return
            self._report = EvalReport(status="running")
        threading.Thread(target=self._execute, name="eval-runner", daemon=True).start()


def main() -> int:
    parser = argparse.ArgumentParser(description="运行采购流程评测")
    parser.add_argument("--cases", default=str(DEFAULT_CASES_PATH))
    parser.add_argument("--out", default=str(DEFAULT_RESULT_PATH))
    parser.add_argument("--workspace", default="eval_results/runs")
    parser.add_argument(
        "--live",
        action="store_true",
        help="使用真实 DeepSeek 模型评测（需要 DEEPSEEK_API_KEY，会产生费用与网络时延）",
    )
    parser.add_argument("--limit", type=int, default=0, help="只跑前 N 条用例，0 表示全部")
    args = parser.parse_args()

    cases = load_cases(Path(args.cases))
    if args.limit > 0:
        cases = cases[: args.limit]

    factory = None
    if args.live:
        from procurement_agent.agents.model import build_chat_model

        factory = build_chat_model
        print(f"[真实模型模式] 用例数 = {len(cases)}")

    report = run_eval(cases, Path(args.workspace), model_factory=factory)
    output = Path(args.out)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(report.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(report.to_dict(), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
