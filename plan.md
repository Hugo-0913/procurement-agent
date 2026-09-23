# 医用耗材采购自动化 Agent 系统 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 构建一个可演示、可评测的医用耗材采购自动化 Agent 系统，用主 Agent 委派三类子 Agent 完成「需求输入 → 资质核验 → 比价分析 → 订单生成」闭环，并提供本地 Web 界面实时观察委派过程、审批拦截与异常重试。

**Architecture:** 外层用 LangGraph 状态机 + SQLite checkpointer 作为唯一任务状态源，负责阶段流转与人工审批的持久化中断；内层用 DeepAgents 作为 Agent 运行时，承载主 Agent 与三个子 Agent 的委派、虚拟文件系统与中间件；DeepSeek 作为唯一模型；FastAPI + 原生 JS 提供 Web 界面，通过 SSE 推送事件。

**Tech Stack:** Python 3.11、deepagents、langgraph、langgraph-checkpoint-sqlite、langchain-deepseek、FastAPI、uvicorn、SQLAlchemy 2.0 + SQLite、pydantic v2、PyYAML、pytest。

**Spec:** `PRD.md`

## Global Constraints

- 运行环境：Windows 11，Python 3.11，本机无 Docker、无可用 WSL，沙箱只能做进程级实现。
- 模型：仅 DeepSeek，通过 OpenAI 兼容接口调用；API key 从环境变量读取，禁止写入仓库。
- 测试禁止真实网络调用：所有 LLM 交互必须通过可注入的模型对象，测试中使用 `FakeModel`。
- 前端仅使用原生 HTML/CSS/JS，禁止引入需要 npm 构建的工具链（本机 Node v14 过旧）。
- 界面文案使用中文。
- 所有任务状态与事件必须持久化到 SQLite，进程重启后任务可恢复。
- 审批金额阈值默认 ¥50,000，重试上限默认 3 次，均定义在 `config/procurement.yaml`，不得硬编码在业务逻辑中。
- 技能文件固定放在 `skills/<skill_name>/SKILL.md`，frontmatter 必须含 `name` 与 `description`。
- 事件类型限定为 PRD 第 7 节枚举值：`stage_change`、`agent_delegation`、`tool_call`、`tool_result`、`skill_loaded`、`policy_denied`、`retry`、`context_summarized`、`approval_requested`、`approval_decided`、`memory_loaded`、`memory_written`、`error`、`task_finished`。
- 每个 Task 结束提交一次 git commit，提交信息使用 `feat:` / `test:` / `docs:` 前缀。
- 单一职责文件划分，任何源文件超过 300 行时需在本 Task 内拆分。

---

## 文件结构总览

```
PRD.md / plan.md / README.md / pyproject.toml / .env.example / .gitignore
config/            agents.yaml, procurement.yaml
skills/            requirement_parsing|supplier_qualification|price_comparison|order_compliance /SKILL.md
src/procurement_agent/
  config.py        环境变量与 YAML 配置加载
  vfs.py           虚拟文件系统
  skills_loader.py 技能注册表与渐进式加载
  db/              schema.sql, models.py, seed.py
  erp/             repository.py, faults.py
  state/           models.py, store.py, graph.py, nodes.py
  agents/          model.py, config.py, coordinator.py, qualification.py, sourcing.py, ordering.py
  memory/          store.py
  middleware/      base.py, context_summarizer.py, policy_guard.py, reflection_retry.py
  sandbox/         policy.py, executor.py
  web/             app.py, routes.py, events.py, templates/*.html, static/*.js,*.css
  eval/            runner.py, cases.yaml, metrics.py
tests/             test_*.py, fakes.py
docs/              architecture.md, decision-log.md, sandbox-security.md, demo-script.md
```

---

# 阶段 M1 · 地基

### Task 1: 项目骨架与配置加载

**Files:**
- Create: `pyproject.toml`, `.gitignore`, `.env.example`, `src/procurement_agent/__init__.py`, `src/procurement_agent/config.py`, `config/procurement.yaml`, `tests/test_config.py`

**Interfaces:**
- Consumes: 无
- Produces: `load_procurement_config(path: Path | None = None) -> ProcurementConfig`；`ProcurementConfig` 含字段 `approval_threshold: float`、`retry_max_attempts: int`、`context_token_threshold: int`、`min_quote_count: int`、`freshness_warn_days: int`

- [ ] **Step 1: 初始化仓库与目录**

Run: `git init` 然后 `mkdir src/procurement_agent tests config skills docs`

`.gitignore` 内容：

```gitignore
__pycache__/
*.pyc
.venv/
.env
data/*.db
workspace/
eval_results/
```

- [ ] **Step 2: 写 pyproject 与安装依赖**

`pyproject.toml`：

```toml
[project]
name = "procurement-agent"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
  "deepagents",
  "langgraph",
  "langgraph-checkpoint-sqlite",
  "langchain-deepseek",
  "fastapi",
  "uvicorn[standard]",
  "sqlalchemy>=2.0",
  "pydantic>=2",
  "pydantic-settings",
  "pyyaml",
  "jinja2",
]

[project.optional-dependencies]
dev = ["pytest", "pytest-asyncio", "httpx"]

[tool.pytest.ini_options]
pythonpath = ["src"]
testpaths = ["tests"]
asyncio_mode = "auto"
```

Run: `python -m pip install -e ".[dev]"`
Expected: 安装成功。若因网络受限失败，请求提升权限后重试。

- [ ] **Step 3: 写失败测试**

`tests/test_config.py`：

```python
from pathlib import Path

import pytest

from procurement_agent.config import load_procurement_config


def test_load_config(tmp_path: Path):
    cfg_file = tmp_path / "procurement.yaml"
    cfg_file.write_text(
        "approval_threshold: 50000\n"
        "retry_max_attempts: 3\n"
        "context_token_threshold: 12000\n"
        "min_quote_count: 2\n"
        "freshness_warn_days: 30\n",
        encoding="utf-8",
    )
    cfg = load_procurement_config(cfg_file)
    assert cfg.approval_threshold == 50000
    assert cfg.retry_max_attempts == 3
    assert cfg.freshness_warn_days == 30


def test_missing_field_raises(tmp_path: Path):
    cfg_file = tmp_path / "procurement.yaml"
    cfg_file.write_text("approval_threshold: 50000\n", encoding="utf-8")
    with pytest.raises(ValueError):
        load_procurement_config(cfg_file)
```

- [ ] **Step 4: 运行测试确认失败**

Run: `python -m pytest tests/test_config.py -v`
Expected: FAIL，`ModuleNotFoundError: No module named 'procurement_agent.config'`

- [ ] **Step 5: 最小实现**

`src/procurement_agent/config.py`：

```python
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

DEFAULT_CONFIG_PATH = Path("config/procurement.yaml")
REQUIRED_FIELDS = (
    "approval_threshold",
    "retry_max_attempts",
    "context_token_threshold",
    "min_quote_count",
    "freshness_warn_days",
)


@dataclass(frozen=True)
class ProcurementConfig:
    approval_threshold: float
    retry_max_attempts: int
    context_token_threshold: int
    min_quote_count: int
    freshness_warn_days: int


def load_procurement_config(path: Path | None = None) -> ProcurementConfig:
    target = Path(path) if path is not None else DEFAULT_CONFIG_PATH
    raw = yaml.safe_load(target.read_text(encoding="utf-8")) or {}
    missing = [f for f in REQUIRED_FIELDS if f not in raw]
    if missing:
        raise ValueError(f"缺少必需配置项: {', '.join(missing)}")
    return ProcurementConfig(**{f: raw[f] for f in REQUIRED_FIELDS})
```

同时创建 `config/procurement.yaml`（上述五个字段，取值同上）与 `.env.example`：

```env
DEEPSEEK_API_KEY=sk-xxx
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-chat
```

- [ ] **Step 6: 运行测试确认通过**

Run: `python -m pytest tests/test_config.py -v`
Expected: 2 passed

- [ ] **Step 7: 提交**

```bash
git add -A
git commit -m "feat: 项目骨架与采购配置加载"
```

---

### Task 2: DeepAgents + DeepSeek 冒烟验证

**Files:**
- Create: `src/procurement_agent/agents/model.py`, `scripts/smoke_deepagents.py`, `docs/decision-log.md`, `tests/test_model_factory.py`

**Interfaces:**
- Consumes: `ProcurementConfig`
- Produces: `build_chat_model(**overrides) -> BaseChatModel`（从环境变量构造 DeepSeek 模型）；决策记录中锁定 deepagents 与 langgraph 的版本号与构造签名

**这是整个项目风险最高的一步**，必须先验证再往上堆功能。

- [ ] **Step 1: 写失败测试**

`tests/test_model_factory.py`：

```python
import pytest

from procurement_agent.agents.model import build_chat_model


def test_missing_api_key_raises(monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="DEEPSEEK_API_KEY"):
        build_chat_model()
```

Run: `python -m pytest tests/test_model_factory.py -v`
Expected: FAIL，模块不存在

- [ ] **Step 2: 实现模型工厂**

`src/procurement_agent/agents/model.py`：

```python
from __future__ import annotations

import os


def build_chat_model(**overrides):
    from langchain_deepseek import ChatDeepSeek

    api_key = os.environ.get("DEEPSEEK_API_KEY")
    if not api_key:
        raise RuntimeError("环境变量 DEEPSEEK_API_KEY 未设置")
    return ChatDeepSeek(
        model=os.environ.get("DEEPSEEK_MODEL", "deepseek-chat"),
        api_key=api_key,
        api_base=os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
        temperature=0,
        **overrides,
    )
```

Run: `python -m pytest tests/test_model_factory.py -v`
Expected: PASS

- [ ] **Step 3: 写冒烟脚本**

`scripts/smoke_deepagents.py` 构造一个只含单个固定返回工具的 Agent，并注册一个子 Agent，依次验证并打印结果：

1. 主 Agent 能否调用工具；
2. 主 Agent 能否委派子 Agent（在消息序列中查找子 Agent 名）；
3. 中间件 hook 是否被调用（打印 hook 名称）。

脚本同时打印 `deepagents.__version__` 与 `create_deep_agent` 的实际签名，便于写入决策记录。

- [ ] **Step 4: 运行冒烟脚本**

Run: `python scripts/smoke_deepagents.py`
Expected: 三项验证均有明确的通过/失败输出。

若第 2 项失败，启用降级方案并在决策记录中写明：改为在 LangGraph 节点内直接调用子 Agent 的函数式接口，不依赖框架的自动委派路由。

- [ ] **Step 5: 写决策记录**

`docs/decision-log.md` 记录：`deepagents` 与 `langgraph` 精确版本、`create_deep_agent` 实际签名、三项验证结论、是否启用降级方案、可用的中间件 hook 名称清单。本文件是 Task 8 与 Task 12 的实现依据。

- [ ] **Step 6: 提交**

```bash
git add -A
git commit -m "feat: DeepSeek 模型工厂与 DeepAgents 委派冒烟验证"
```

---

### Task 3: mock ERP 数据层

**Files:**
- Create: `src/procurement_agent/db/schema.sql`, `src/procurement_agent/db/models.py`, `src/procurement_agent/db/seed.py`, `src/procurement_agent/erp/repository.py`, `tests/test_repository.py`

**Interfaces:**
- Consumes: `ProcurementConfig`
- Produces:
  - `init_db(db_path: Path) -> Engine`
  - `seed_demo_data(engine) -> None`
  - ORM 类型：`Material`、`Supplier`、`Qualification`、`Quote`
  - `ErpRepository(engine, faults=None)`：`find_material_by_name(name: str) -> Material | None`、`list_suppliers() -> list[Supplier]`、`list_qualifications(supplier_id: int) -> list[Qualification]`、`list_quotes(material_id: int) -> list[Quote]`、`price_history(material_id: int, supplier_id: int | None = None) -> list[float]`、`create_order(draft: dict) -> int`、`get_order(order_id: int) -> Order`、`list_orders() -> list[Order]`

- [ ] **Step 1: 写建表脚本**

`src/procurement_agent/db/schema.sql` 按 PRD 第 7 节建表，包含 `materials`、`suppliers`、`supplier_qualifications`、`quotes`、`price_history`、`purchase_requests`、`tasks`、`task_events`、`orders`、`approvals`、`agent_memory`、`fault_flags`。关键约束：`suppliers.code` 唯一、`task_events(task_id, seq)` 唯一、外键指向 `suppliers` / `materials`。

- [ ] **Step 2: 写失败测试**

`tests/test_repository.py`：

```python
from pathlib import Path

from procurement_agent.db.models import init_db, seed_demo_data
from procurement_agent.erp.repository import ErpRepository


def make_repo(tmp_path: Path) -> ErpRepository:
    engine = init_db(tmp_path / "erp.db")
    seed_demo_data(engine)
    return ErpRepository(engine)


def test_find_material_by_name(tmp_path):
    repo = make_repo(tmp_path)
    material = repo.find_material_by_name("一次性无菌注射器")
    assert material is not None
    assert material.sku == "ST-SYR-5ML"


def test_quotes_available_for_material(tmp_path):
    repo = make_repo(tmp_path)
    material = repo.find_material_by_name("一次性无菌注射器")
    quotes = repo.list_quotes(material.id)
    assert len(quotes) >= 3
    assert all(q.unit_price > 0 for q in quotes)


def test_create_and_read_order(tmp_path):
    repo = make_repo(tmp_path)
    order_id = repo.create_order(
        {
            "task_id": "t-1",
            "supplier_id": 1,
            "material_id": 1,
            "quantity": 50,
            "unit_price": 21.5,
            "total_amount": 1075.0,
            "lead_days": 3,
            "cost_center": "CC-1001",
        }
    )
    order = repo.get_order(order_id)
    assert order.total_amount == 1075.0
    assert order.status == "CREATED"
```

- [ ] **Step 3: 运行测试确认失败**

Run: `python -m pytest tests/test_repository.py -v`
Expected: FAIL，模块不存在

- [ ] **Step 4: 实现 ORM 与 seed**

`models.py` 用 SQLAlchemy 2.0 `Mapped` / `mapped_column` 定义模型；`init_db` 先执行 `PRAGMA foreign_keys=ON` 再 `create_all`。

`seed.py` 写入演示数据：物料 `一次性无菌注射器`（SKU `ST-SYR-5ML`，规格 `70g/500张`，单位 `箱`）；4 家供应商（`SUP-A` A 类、`SUP-B` B 类、`SUP-C` A 类且资质 20 天后到期、`SUP-D` 黑名单）；询价覆盖 `SUP-A/B/C`，单价分别 21.5 / 19.8 / 23.0，运费 0 / 120 / 0，交期 3 / 5 / 2 天；每家 3 条历史成交价；7 条历史采购需求写入 `purchase_requests`。

- [ ] **Step 5: 实现 Repository**

`find_material_by_name` 使用包含匹配；`list_quotes` 默认只返回 `available = 1` 且 `valid_until >= today` 的记录；`create_order` 写入后返回自增主键。

- [ ] **Step 6: 运行测试确认通过**

Run: `python -m pytest tests/test_repository.py -v`
Expected: 3 passed

- [ ] **Step 7: 提交**

```bash
git add -A
git commit -m "feat: mock ERP 数据模型与仓储层"
```

---

### Task 4: 故障注入开关

**Files:**
- Create: `src/procurement_agent/erp/faults.py`, `tests/test_faults.py`
- Modify: `src/procurement_agent/erp/repository.py`

**Interfaces:**
- Consumes: `ErpRepository`
- Produces:
  - 常量 `SUPPLIER_B_EXPIRED = "supplier_b_expired"`、`SUPPLIER_C_NO_QUOTE = "supplier_c_no_quote"`、`ALL_QUOTES_OVER_BUDGET = "all_quotes_over_budget"`
  - `FaultRegistry(engine)`：`set(flag: str, enabled: bool) -> None`、`is_enabled(flag: str) -> bool`、`list_flags() -> dict[str, bool]`

- [ ] **Step 1: 写失败测试**

`tests/test_faults.py`：

```python
from datetime import date
from pathlib import Path

from procurement_agent.db.models import init_db, seed_demo_data
from procurement_agent.erp.faults import SUPPLIER_B_EXPIRED, FaultRegistry
from procurement_agent.erp.repository import ErpRepository


def make_repo(tmp_path: Path):
    engine = init_db(tmp_path / "erp.db")
    seed_demo_data(engine)
    faults = FaultRegistry(engine)
    return ErpRepository(engine, faults), faults


def test_supplier_b_qualification_becomes_expired(tmp_path):
    repo, faults = make_repo(tmp_path)
    supplier_b = next(s for s in repo.list_suppliers() if s.code == "SUP-B")
    before = repo.list_qualifications(supplier_b.id)
    assert all(q.expires_at >= date.today() for q in before)

    faults.set(SUPPLIER_B_EXPIRED, True)
    after = repo.list_qualifications(supplier_b.id)
    assert any(q.expires_at < date.today() for q in after)


def test_supplier_c_quote_removed(tmp_path):
    repo, faults = make_repo(tmp_path)
    material = repo.find_material_by_name("一次性无菌注射器")
    before = len(repo.list_quotes(material.id))
    faults.set("supplier_c_no_quote", True)
    assert len(repo.list_quotes(material.id)) == before - 1


def test_fault_flags_persisted(tmp_path):
    _, faults = make_repo(tmp_path)
    faults.set("all_quotes_over_budget", True)
    assert faults.is_enabled("all_quotes_over_budget") is True
    assert faults.list_flags()["all_quotes_over_budget"] is True
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_faults.py -v`
Expected: FAIL，`ModuleNotFoundError: procurement_agent.erp.faults`

- [ ] **Step 3: 实现 FaultRegistry**

读写 `fault_flags` 表，`set` 使用 UPSERT，`is_enabled` 未设置时返回 False，`list_flags` 返回全部开关的字典。

- [ ] **Step 4: 在 Repository 中应用故障**

`list_qualifications` 内：若 `SUPPLIER_B_EXPIRED` 开启且供应商 `code == "SUP-B"`，返回记录的 `expires_at` 替换为 `date.today() - timedelta(days=5)`。

`list_quotes` 内：若 `SUPPLIER_C_NO_QUOTE` 开启，过滤 `SUP-C`；若 `ALL_QUOTES_OVER_BUDGET` 开启，返回报价的 `unit_price` 统一乘以 3.0。

故障判断写在 Repository 内部而非 Agent 内部，保证 Agent 代码对故障无感。

- [ ] **Step 5: 运行测试确认通过**

Run: `python -m pytest tests/test_faults.py tests/test_repository.py -v`
Expected: 6 passed

- [ ] **Step 6: 提交**

```bash
git add -A
git commit -m "feat: mock ERP 故障注入开关"
```

---

# 阶段 M2 · 状态机与 Agent 核心

### Task 5: 任务状态与事件存储

**Files:**
- Create: `src/procurement_agent/state/models.py`, `src/procurement_agent/state/store.py`, `tests/test_task_store.py`

**Interfaces:**
- Consumes: `init_db`
- Produces:
  - `TaskState`（StrEnum，取值严格对应 PRD 4.2）
  - `TaskEvent(task_id, seq, agent, event_type, payload, created_at)`
  - `TaskRecord(id, request_text, state, structured_request, created_at, updated_at, finished_at, human_interventions, token_usage)`
  - `InvalidTransition(Exception)`，属性 `from_state`、`to_state`
  - `TaskStore(engine)`：`create_task(request_text: str) -> str`、`get_task(task_id: str) -> TaskRecord`、`list_tasks(state: TaskState | None = None) -> list[TaskRecord]`、`transition(task_id: str, to_state: TaskState) -> None`、`append_event(task_id: str, agent: str, event_type: str, payload: dict) -> TaskEvent`、`list_events(task_id: str, after_seq: int = 0) -> list[TaskEvent]`、`record_intervention(task_id: str) -> None`、`finish_task(task_id: str, state: TaskState) -> None`

- [ ] **Step 1: 写失败测试**

`tests/test_task_store.py`：

```python
from pathlib import Path

import pytest

from procurement_agent.db.models import init_db
from procurement_agent.state.models import TaskState
from procurement_agent.state.store import InvalidTransition, TaskStore


def make_store(tmp_path: Path) -> TaskStore:
    return TaskStore(init_db(tmp_path / "erp.db"))


def test_create_task_starts_pending(tmp_path):
    store = make_store(tmp_path)
    task_id = store.create_task("采购 50 箱 一次性无菌注射器")
    assert store.get_task(task_id).state is TaskState.PENDING


def test_legal_transition(tmp_path):
    store = make_store(tmp_path)
    task_id = store.create_task("x")
    store.transition(task_id, TaskState.PARSING)
    assert store.get_task(task_id).state is TaskState.PARSING


def test_illegal_transition_raises(tmp_path):
    store = make_store(tmp_path)
    task_id = store.create_task("x")
    with pytest.raises(InvalidTransition) as exc:
        store.transition(task_id, TaskState.ORDERED)
    assert exc.value.from_state is TaskState.PENDING
    assert exc.value.to_state is TaskState.ORDERED


def test_events_are_sequenced(tmp_path):
    store = make_store(tmp_path)
    task_id = store.create_task("x")
    first = store.append_event(task_id, "coordinator", "stage_change", {"to": "PARSING"})
    second = store.append_event(task_id, "coordinator", "tool_call", {"tool": "x"})
    assert (first.seq, second.seq) == (1, 2)
    assert [e.seq for e in store.list_events(task_id, after_seq=1)] == [2]


def test_finish_sets_finished_at(tmp_path):
    store = make_store(tmp_path)
    task_id = store.create_task("x")
    store.transition(task_id, TaskState.FAILED)
    store.finish_task(task_id, TaskState.FAILED)
    assert store.get_task(task_id).finished_at is not None
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_task_store.py -v`
Expected: FAIL，模块不存在

- [ ] **Step 3: 实现状态枚举与合法转移表**

`state/models.py` 定义 `TaskState` 与模块级常量 `ALLOWED_TRANSITIONS: dict[TaskState, frozenset[TaskState]]`，内容严格对应 PRD 4.3 的转移表：`PENDING → {PARSING, FAILED}`、`PARSING → {QUALIFYING, FAILED}`、`QUALIFYING → {SOURCING, FAILED}`、`SOURCING → {ORDER_DRAFTING, FAILED}`、`ORDER_DRAFTING → {AWAITING_APPROVAL, ORDERED, FAILED}`、`AWAITING_APPROVAL → {ORDERED, REVISION_REQUIRED, ORDER_DRAFTING, FAILED}`、`REVISION_REQUIRED → {SOURCING, FAILED}`、`ORDERED → {COMPLETED, FAILED}`、`COMPLETED → frozenset()`、`FAILED → frozenset()`。

- [ ] **Step 4: 实现 TaskStore**

`transition` 先校验转移表，非法时抛 `InvalidTransition`；合法时更新 `tasks.state` 与 `updated_at`，并写入一条 `stage_change` 事件（`payload={"from": ..., "to": ...}`）。`append_event` 在同一事务内用 `SELECT COALESCE(MAX(seq), 0) + 1` 生成序号。

- [ ] **Step 5: 运行测试确认通过**

Run: `python -m pytest tests/test_task_store.py -v`
Expected: 5 passed

- [ ] **Step 6: 提交**

```bash
git add -A
git commit -m "feat: 任务状态机与事件存储"
```

---

### Task 6: 阶段推进与持久化审批中断

**Files:**
- Create: `src/procurement_agent/state/graph.py`, `src/procurement_agent/state/nodes.py`, `tests/test_graph_stages.py`

**Interfaces:**
- Consumes: `TaskStore`、`TaskState`、`ProcurementConfig`
- Produces:
  - `StageResult(state: TaskState, payload: dict)`
  - `build_stage_graph(store: TaskStore, handlers: dict[TaskState, Callable[[str, dict], StageResult]], config: ProcurementConfig) -> CompiledStateGraph`
  - `TaskRunner(store: TaskStore, graph) `：`start(request_text: str) -> str`、`resume(task_id: str, decision: str, operator: str, reason: str) -> None`

- [ ] **Step 1: 写失败测试**

`tests/test_graph_stages.py` 用假 handler（不做任何 LLM 调用）验证三件事：正常路径走完到 `COMPLETED`；金额超阈值时停在 `AWAITING_APPROVAL`；进程重建（新建 `TaskRunner` 指向同一 db 文件）后仍可 resume 到 `ORDERED`。

```python
from pathlib import Path

from procurement_agent.config import ProcurementConfig
from procurement_agent.db.models import init_db
from procurement_agent.state.graph import TaskRunner, build_stage_graph
from procurement_agent.state.models import TaskState
from procurement_agent.state.nodes import StageResult
from procurement_agent.state.store import TaskStore

CONFIG = ProcurementConfig(50000.0, 3, 12000, 2, 30)


def make_handlers(total_amount: float, needs_approval: bool):
    def factory(state: TaskState):
        def handler(task_id: str, payload: dict) -> StageResult:
            return StageResult(
                state=state,
                payload={"total_amount": total_amount, "needs_approval": needs_approval},
            )

        return handler

    return {
        s: factory(s)
        for s in (
            TaskState.PARSING,
            TaskState.QUALIFYING,
            TaskState.SOURCING,
            TaskState.ORDER_DRAFTING,
            TaskState.ORDERED,
        )
    }


def test_happy_path_completes(tmp_path: Path):
    store = TaskStore(init_db(tmp_path / "erp.db"))
    runner = TaskRunner(store, build_stage_graph(store, make_handlers(1000.0, False), CONFIG))
    task_id = runner.start("采购 50 箱 一次性无菌注射器")
    assert store.get_task(task_id).state is TaskState.COMPLETED


def test_approval_pauses_task(tmp_path: Path):
    store = TaskStore(init_db(tmp_path / "erp.db"))
    runner = TaskRunner(store, build_stage_graph(store, make_handlers(62000.0, True), CONFIG))
    task_id = runner.start("采购 50 箱 一次性无菌注射器")
    assert store.get_task(task_id).state is TaskState.AWAITING_APPROVAL


def test_resume_after_process_restart(tmp_path: Path):
    db = tmp_path / "erp.db"
    store = TaskStore(init_db(db))
    runner = TaskRunner(store, build_stage_graph(store, make_handlers(62000.0, True), CONFIG))
    task_id = runner.start("采购 50 箱 一次性无菌注射器")

    store2 = TaskStore(init_db(db))
    runner2 = TaskRunner(store2, build_stage_graph(store2, make_handlers(62000.0, True), CONFIG))
    runner2.resume(task_id, decision="approve", operator="alice", reason="预算内")
    assert store2.get_task(task_id).state is TaskState.ORDERED
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_graph_stages.py -v`
Expected: FAIL，模块不存在

- [ ] **Step 3: 实现图结构**

`state/graph.py` 用 `StateGraph` 定义节点 `parsing`、`qualifying`、`sourcing`、`order_drafting`、`approval_gate`、`ordering`、`finish`。每个阶段节点调用对应 handler，把 `StageResult.state` 写回 `TaskStore`。

`approval_gate` 读取 `payload["needs_approval"]`：为真时先 `store.transition(task_id, TaskState.AWAITING_APPROVAL)` 并写 `approval_requested` 事件（`payload` 含 `matched_rules`），再调用 LangGraph `interrupt(...)` 挂起；为假时直接进入 `ordering`。

编译时传入 `SqliteSaver`，checkpoint 数据库与 ERP 使用同一个 db 文件，保证进程重启后 `resume` 能取回中断点。

- [ ] **Step 4: 实现 resume 路由**

`TaskRunner.resume` 用 `Command(resume={"decision": ..., "operator": ..., "reason": ...})` 续跑，并按决策路由：`approve` → `ordering`；`reject` → 先转 `REVISION_REQUIRED` 再回 `sourcing`；`revise` → 回 `order_drafting`。三种决策均写 `approval_decided` 事件并调用 `record_intervention`。

- [ ] **Step 5: 运行测试确认通过**

Run: `python -m pytest tests/test_graph_stages.py -v`
Expected: 3 passed

- [ ] **Step 6: 提交**

```bash
git add -A
git commit -m "feat: 阶段推进图与持久化审批中断"
```

---

### Task 7: 技能系统与渐进式加载

**Files:**
- Create: `src/procurement_agent/skills_loader.py`, `skills/requirement_parsing/SKILL.md`, `skills/supplier_qualification/SKILL.md`, `skills/price_comparison/SKILL.md`, `skills/order_compliance/SKILL.md`, `tests/test_skills_loader.py`

**Interfaces:**
- Consumes: 无
- Produces:
  - `SkillMeta(name: str, description: str, path: Path)`
  - `SkillNotFound(Exception)`
  - `SkillRegistry(skills_root: Path)`：`list_metadata() -> list[SkillMeta]`、`load(name: str) -> str`、`loaded_names -> set[str]`、`reset() -> None`

- [ ] **Step 1: 写四个 SKILL.md**

每个文件格式如下（正文各不少于 20 行，写清该领域的具体规则与输出格式要求）：

```markdown
---
name: price_comparison
description: 当需要在多个合格供应商之间比较报价、计算综合成本并给出推荐理由时使用。
---

（正文：比价维度、综合成本口径、推荐规则、非最低价时必须给出的理由模板）
```

四个技能的名称必须为 `requirement_parsing`、`supplier_qualification`、`price_comparison`、`order_compliance`，规则内容与 PRD 第 5 节 FR-01 / FR-02 / FR-03 / FR-04 一致。

- [ ] **Step 2: 写失败测试**

`tests/test_skills_loader.py`：

```python
from pathlib import Path

import pytest

from procurement_agent.skills_loader import SkillNotFound, SkillRegistry

SKILLS_ROOT = Path("skills")


def test_lists_four_skills_without_loading_bodies():
    registry = SkillRegistry(SKILLS_ROOT)
    metas = registry.list_metadata()
    assert {m.name for m in metas} == {
        "requirement_parsing",
        "supplier_qualification",
        "price_comparison",
        "order_compliance",
    }
    assert all(m.description for m in metas)
    assert registry.loaded_names == set()


def test_load_returns_body_and_marks_loaded():
    registry = SkillRegistry(SKILLS_ROOT)
    body = registry.load("price_comparison")
    assert "比价" in body
    assert registry.loaded_names == {"price_comparison"}


def test_unknown_skill_raises():
    registry = SkillRegistry(SKILLS_ROOT)
    with pytest.raises(SkillNotFound):
        registry.load("nope")
```

- [ ] **Step 3: 运行测试确认失败**

Run: `python -m pytest tests/test_skills_loader.py -v`
Expected: FAIL，模块不存在

- [ ] **Step 4: 实现 SkillRegistry**

用 `re` 解析 frontmatter 的 `name` 与 `description`；`list_metadata` 只读文件头部，不加载正文；`load` 读取正文并加入 `_loaded` 集合；`reset` 清空集合，供每个新任务调用。

- [ ] **Step 5: 运行测试确认通过**

Run: `python -m pytest tests/test_skills_loader.py -v`
Expected: 3 passed

- [ ] **Step 6: 提交**

```bash
git add -A
git commit -m "feat: 技能注册表与渐进式加载"
```

---

### Task 8: YAML 驱动的 Agent 配置

**Files:**
- Create: `config/agents.yaml`, `src/procurement_agent/agents/config.py`, `tests/test_agent_config.py`

**Interfaces:**
- Consumes: `ProcurementConfig`、`SkillMeta`
- Produces:
  - `AgentSpec(name: str, role: str, system_prompt: str, tools: tuple[str, ...], skills: tuple[str, ...], max_tool_calls: int)`
  - `AgentsConfig(coordinator: AgentSpec, subagents: dict[str, AgentSpec])`
  - `load_agents_config(path: Path | None = None) -> AgentsConfig`

- [ ] **Step 1: 写 config/agents.yaml**

包含 `coordinator` 与 `subagents`（键为 `qualification`、`sourcing`、`ordering`）四段，每段含 `name`、`role`、`system_prompt`、`tools`、`skills`、`max_tool_calls`（默认 6）。`coordinator.tools` 中列出三个子 Agent 名称作为可委派目标；`ordering` 段的 `skills` 含 `order_compliance`；`coordinator` 段的 `skills` 含 `requirement_parsing`。

- [ ] **Step 2: 写失败测试**

`tests/test_agent_config.py` 断言：四段配置均可加载；`subagents` 恰好 3 个且键名正确；每个 Agent 的 `skills` 中每个名称都能在 `skills/` 下找到对应目录；`max_tool_calls` 为正整数；缺少必需字段时抛 `ValueError` 且消息中包含该 Agent 名。

- [ ] **Step 3: 运行测试确认失败**

Run: `python -m pytest tests/test_agent_config.py -v`
Expected: FAIL，模块不存在

- [ ] **Step 4: 实现加载器**

`agents/config.py` 用 `@dataclass(frozen=True)` 定义 `AgentSpec` 与 `AgentsConfig`，用必填字段校验实现 `load_agents_config`，`tools` 与 `skills` 转成 tuple。

- [ ] **Step 5: 运行测试确认通过**

Run: `python -m pytest tests/test_agent_config.py -v`
Expected: 全部通过

- [ ] **Step 6: 提交**

```bash
git add -A
git commit -m "feat: YAML 驱动的 Agent 配置"
```

---

### Task 9: 资质核验子 Agent

**Files:**
- Create: `src/procurement_agent/agents/qualification.py`, `tests/fakes.py`, `tests/test_qualification_agent.py`

**Interfaces:**
- Consumes: `ErpRepository`、`ProcurementConfig`、`SkillRegistry`
- Produces:
  - `QualifiedSupplier(supplier_id: int, code: str, name: str, tier: str, expiring_soon: bool)`
  - `RejectedSupplier(supplier_id: int, code: str, name: str, reason: str)`
  - `QualificationOutcome(qualified: list[QualifiedSupplier], rejected: list[RejectedSupplier], notes: list[str])`
  - `run_qualification(repo, config, material_id: int, *, skills: SkillRegistry | None = None) -> QualificationOutcome`

**设计约束：** 业务判定必须是确定性纯函数，不依赖 LLM，保证可测试、可复现。

- [ ] **Step 1: 写测试替身**

`tests/fakes.py` 提供 `FakeModel`：构造时传入 `responses: list[str]` 脚本，调用时按顺序弹出；脚本耗尽时抛 `AssertionError("FakeModel 脚本已耗尽")`，防止测试意外发起真实调用。同时提供 `FixedModelFactory(responses)`，签名与 `build_chat_model` 兼容。

- [ ] **Step 2: 写失败测试**

`tests/test_qualification_agent.py`：

```python
from pathlib import Path

from procurement_agent.agents.qualification import run_qualification
from procurement_agent.config import ProcurementConfig
from procurement_agent.db.models import init_db, seed_demo_data
from procurement_agent.erp.faults import SUPPLIER_B_EXPIRED, FaultRegistry
from procurement_agent.erp.repository import ErpRepository


def make_env(tmp_path: Path):
    engine = init_db(tmp_path / "erp.db")
    seed_demo_data(engine)
    faults = FaultRegistry(engine)
    repo = ErpRepository(engine, faults)
    cfg = ProcurementConfig(50000.0, 3, 12000, 2, 30)
    material = repo.find_material_by_name("一次性无菌注射器")
    return repo, faults, cfg, material


def test_blacklisted_supplier_rejected(tmp_path):
    repo, _, cfg, material = make_env(tmp_path)
    outcome = run_qualification(repo, cfg, material.id)
    assert "SUP-D" not in {s.code for s in outcome.qualified}
    assert "黑名单" in {r.code: r.reason for r in outcome.rejected}["SUP-D"]


def test_expired_supplier_rejected_when_fault_enabled(tmp_path):
    repo, faults, cfg, material = make_env(tmp_path)
    faults.set(SUPPLIER_B_EXPIRED, True)
    outcome = run_qualification(repo, cfg, material.id)
    assert "SUP-B" not in {s.code for s in outcome.qualified}
    assert "过期" in {r.code: r.reason for r in outcome.rejected}["SUP-B"]


def test_expiring_soon_marked_not_rejected(tmp_path):
    repo, _, cfg, material = make_env(tmp_path)
    outcome = run_qualification(repo, cfg, material.id)
    sup_c = next(s for s in outcome.qualified if s.code == "SUP-C")
    assert sup_c.expiring_soon is True
```

- [ ] **Step 3: 运行测试确认失败**

Run: `python -m pytest tests/test_qualification_agent.py -v`
Expected: FAIL，模块不存在

- [ ] **Step 4: 实现核验逻辑**

规则判定顺序：黑名单 → 资质缺失 → 资质已过期 → 临期标记（`expires_at` 距今小于 `config.freshness_warn_days`）。淘汰与临期标记均写入带中文关键词的结构化原因（必须包含"黑名单""过期""临期"字样，供页面与测试断言）。

传入 `skills` 时调用 `skills.load("supplier_qualification")`。

- [ ] **Step 5: 运行测试确认通过**

Run: `python -m pytest tests/test_qualification_agent.py -v`
Expected: 3 passed

- [ ] **Step 6: 提交**

```bash
git add -A
git commit -m "feat: 资质核验子 Agent"
```

---

### Task 10: 比价分析子 Agent

**Files:**
- Create: `src/procurement_agent/agents/sourcing.py`, `tests/test_sourcing_agent.py`

**Interfaces:**
- Consumes: `QualificationOutcome`、`ErpRepository`、`ProcurementConfig`、`SkillRegistry`
- Produces:
  - `QuoteComparison(supplier_id: int, code: str, name: str, unit_price: float, freight: float, lead_days: int, total: float, history_avg: float | None, deviation: float | None, expiring_soon: bool)`
  - `SourcingOutcome(comparisons: list[QuoteComparison], recommended: QuoteComparison | None, reason: str, insufficient_quotes: bool)`
  - `run_sourcing(repo, config, material_id: int, quantity: int, qualified: QualificationOutcome, *, skills: SkillRegistry | None = None) -> SourcingOutcome`

**计算口径：** 综合成本 `total = unit_price * quantity + freight`；历史偏差 `deviation = (unit_price - history_avg) / history_avg`（无历史价时为 None）。

- [ ] **Step 1: 写失败测试**

`tests/test_sourcing_agent.py` 覆盖四条断言：

1. `comparisons` 长度等于合格供应商中有报价者的数量；
2. `recommended` 的 `expiring_soon` 为 False；
3. 当推荐对象不是最低综合成本者时，`reason` 非空且包含中文理由（例如"资质临期"）；
4. 启用 `SUPPLIER_C_NO_QUOTE` 后 `insufficient_quotes` 为 True。

复用 Task 9 的 `make_env`，需把 `make_env` 提取到 `tests/conftest.py` 以便两个测试文件共用。

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_sourcing_agent.py -v`
Expected: FAIL，模块不存在

- [ ] **Step 3: 实现比价逻辑**

遍历合格供应商，读取其报价与历史均价，构造 `QuoteComparison`。推荐规则：在 `expiring_soon=False` 的候选中取 `total` 最小者；若最优候选为临期供应商，改选第二优，并把差异原因写入 `reason`。判定"不是最低价"的条件是 `recommended.total > min(all totals)`。

`reason` 模板固定为两种：

- `f"推荐 {recommended.name}，综合成本 ¥{recommended.total:.2f}；未选最低价 {cheapest.name}，原因：{cause}"`
- `f"推荐 {recommended.name}，综合成本最低 ¥{recommended.total:.2f}"`

`insufficient_quotes` 判定为 `len(comparisons) < config.min_quote_count`。

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest tests/test_sourcing_agent.py -v`
Expected: 4 passed

- [ ] **Step 5: 提交**

```bash
git add -A
git commit -m "feat: 比价分析子 Agent"
```

---

### Task 11: 订单草稿与审批策略引擎

**Files:**
- Create: `src/procurement_agent/sandbox/policy.py`, `src/procurement_agent/agents/ordering.py`, `tests/test_policy_engine.py`, `tests/test_ordering_agent.py`

**Interfaces:**
- Consumes: `SourcingOutcome`、`ProcurementConfig`、`ErpRepository`
- Produces:
  - `PolicyDecision(allowed: bool, requires_approval: bool, matched_rules: tuple[str, ...], reason: str)`
  - `PolicyEngine(config: ProcurementConfig)`：`check_order(draft: OrderDraft) -> PolicyDecision`
  - `OrderDraft(task_id, supplier_id, material_id, quantity, unit_price, total_amount, lead_days, cost_center, supplier_expiring_soon=False, price_gap_ratio=0.0)`
  - `InsufficientQuotesError(Exception)`
  - `run_ordering(repo, policy, sourcing: SourcingOutcome, quantity: int, cost_center: str, task_id: str) -> tuple[OrderDraft, PolicyDecision]`

- [ ] **Step 1: 写策略引擎失败测试**

`tests/test_policy_engine.py`：

```python
from procurement_agent.agents.ordering import OrderDraft
from procurement_agent.config import ProcurementConfig
from procurement_agent.sandbox.policy import PolicyEngine

CFG = ProcurementConfig(50000.0, 3, 12000, 2, 30)


def make_draft(total: float, expiring: bool = False, price_gap: float = 0.0) -> OrderDraft:
    return OrderDraft(
        task_id="t-1",
        supplier_id=1,
        material_id=1,
        quantity=50,
        unit_price=total / 50,
        total_amount=total,
        lead_days=3,
        cost_center="CC-1001",
        supplier_expiring_soon=expiring,
        price_gap_ratio=price_gap,
    )


def test_amount_below_threshold_allows():
    decision = PolicyEngine(CFG).check_order(make_draft(1000.0))
    assert decision.allowed is True
    assert decision.requires_approval is False
    assert decision.matched_rules == ()


def test_amount_above_threshold_requires_approval():
    decision = PolicyEngine(CFG).check_order(make_draft(62400.0))
    assert decision.requires_approval is True
    assert any("50000" in rule for rule in decision.matched_rules)


def test_expiring_supplier_requires_approval():
    decision = PolicyEngine(CFG).check_order(make_draft(1000.0, expiring=True))
    assert decision.requires_approval is True
    assert any("临期" in rule for rule in decision.matched_rules)


def test_price_gap_requires_approval():
    decision = PolicyEngine(CFG).check_order(make_draft(1000.0, price_gap=0.15))
    assert decision.requires_approval is True
    assert any("非最低价" in rule for rule in decision.matched_rules)
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_policy_engine.py -v`
Expected: FAIL，模块不存在

- [ ] **Step 3: 实现 PolicyEngine 与 OrderDraft**

`OrderDraft` 为 `@dataclass(frozen=True)`。`PolicyEngine.check_order` 依次检查三条规则并累积 `matched_rules`，规则字符串必须包含具体数值，例如：

- `f"订单金额 ¥{draft.total_amount:.2f} > 阈值 ¥{config.approval_threshold:.2f}"`
- `"供应商资质临期，需要人工确认"`
- `f"推荐结果非最低价，差额比例 {draft.price_gap_ratio:.1%} 超过 10%"`

`allowed` 恒为 True（超阈值是转人工而非拒绝），`requires_approval` 由是否命中规则决定；命中时 `reason` 为规则拼接。

- [ ] **Step 4: 写订单子 Agent 失败测试**

`tests/test_ordering_agent.py` 覆盖：由比价结果生成草稿且 `total_amount` 等于推荐的综合成本；非最低价时 `price_gap_ratio` 计算正确（`(recommended.total - cheapest.total) / cheapest.total`）；比价结论为临期供应商时 `supplier_expiring_soon` 为 True；`recommended is None` 时抛 `InsufficientQuotesError`；`repo.create_order` 被调用后 `get_order` 能读到记录。

- [ ] **Step 5: 运行测试确认失败**

Run: `python -m pytest tests/test_ordering_agent.py -v`
Expected: FAIL，模块不存在

- [ ] **Step 6: 实现 run_ordering**

由推荐结果构造 `OrderDraft`，调用 `policy.check_order` 返回 `(draft, decision)`。`run_ordering` 本身不写库，写库动作由 Task 12 的 `ordering` handler 在审批通过后执行，保证"审批前不产生订单"。

- [ ] **Step 7: 运行测试确认通过**

Run: `python -m pytest tests/test_policy_engine.py tests/test_ordering_agent.py -v`
Expected: 全部通过

- [ ] **Step 8: 提交**

```bash
git add -A
git commit -m "feat: 订单草稿生成与审批策略引擎"
```

---

### Task 12: 主 Agent 委派编排

**Files:**
- Create: `src/procurement_agent/agents/coordinator.py`, `tests/test_coordinator.py`
- Modify: `src/procurement_agent/state/nodes.py`（补齐真实 handler）

**Interfaces:**
- Consumes: `TaskStore`、`ErpRepository`、`ProcurementConfig`、`AgentsConfig`、`SkillRegistry`、`PolicyEngine`、`MemoryStore`、`ContextSummarizer`、`RetryPolicy`
- Produces:
  - `CoordinatorDeps(repo, store, config, agents_config, skills, policy, memory, summarizer, model_factory)`
  - `build_handlers(deps: CoordinatorDeps) -> dict[TaskState, Callable[[str, dict], StageResult]]`
  - 每个 handler 的职责：切换状态、写 `agent_delegation` 事件、调用对应子 Agent、写 `tool_call` / `tool_result` 事件、返回 `StageResult`

- [ ] **Step 1: 写失败测试**

`tests/test_coordinator.py` 使用 `FixedModelFactory` 与真实 mock ERP，断言完整跑通后：

- 事件类型集合包含 `stage_change`、`agent_delegation`、`tool_call`、`tool_result`、`skill_loaded`；
- `agent_delegation` 事件恰好 3 条，`payload["to"]` 覆盖三个子 Agent 名；
- `skill_loaded` 至少包含 `requirement_parsing` 与 `price_comparison`，且不含未使用的 `order_compliance`；
- 金额超阈值用例中出现 `approval_requested`；
- 未超阈值用例最终状态为 `COMPLETED`，且 `orders` 表中有对应订单。

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_coordinator.py -v`
Expected: FAIL，模块不存在

- [ ] **Step 3: 实现 parsing handler**

调用 `skills.load("requirement_parsing")` 并写 `skill_loaded` 事件；用模型把需求文本解析为结构化要素（测试中由 `FixedModelFactory` 返回固定 JSON 字符串）；解析结果写入 `tasks.structured_request`。若缺少物料或数量，返回 `StageResult(state=TaskState.PARSING, payload={"needs_clarification": True, "question": ...})` 并停在原状态。

结构化输出的解析必须做 JSON 校验，校验失败抛 `json.JSONDecodeError` 交给重试中间件处理。

- [ ] **Step 4: 实现 qualifying / sourcing / order_drafting handler**

三者结构一致：写 `agent_delegation` 事件 → 写 `tool_call` 事件 → 调用对应子 Agent（外层包 `run_with_retry`）→ 写 `tool_result` 事件 → 返回 `StageResult`。

`order_drafting` handler 额外把 `decision.requires_approval` 与 `decision.matched_rules` 放进 `payload`，供 `approval_gate` 使用。

- [ ] **Step 5: 实现 ordering handler**

调用 `repo.create_order(draft)`，写 `tool_result` 事件，调用 `memory.record_order_outcome` 并写 `memory_written` 事件，返回 `StageResult(state=TaskState.ORDERED, payload={"order_id": order_id})`。

若 `sourcing.insufficient_quotes` 为 True，抛 `InsufficientQuotesError`，由上层转 `FAILED` 并写 `error` 事件。

- [ ] **Step 6: 运行测试确认通过**

Run: `python -m pytest tests/test_coordinator.py -v`
Expected: 全部通过

- [ ] **Step 7: 提交**

```bash
git add -A
git commit -m "feat: 主 Agent 委派编排与阶段处理器"
```

---

# 阶段 M3 · 治理能力

### Task 13: 虚拟文件系统

**Files:**
- Create: `src/procurement_agent/vfs.py`, `tests/test_vfs.py`

**Interfaces:**
- Consumes: 无
- Produces:
  - `PathEscapeError(Exception)`，属性 `original: str`、`resolved: str`
  - `VirtualFileSystem(workspace: Path, readonly_roots: list[Path])`：`resolve(path: str, mode: Literal["read", "write"]) -> Path`、`read_text(path: str) -> str`、`write_text(path: str, content: str) -> None`、`list_dir(path: str) -> list[str]`

- [ ] **Step 1: 写失败测试**

`tests/test_vfs.py`：

```python
from pathlib import Path

import pytest

from procurement_agent.vfs import PathEscapeError, VirtualFileSystem


def make_vfs(tmp_path: Path) -> VirtualFileSystem:
    workspace = tmp_path / "workspace"
    readonly = tmp_path / "readonly"
    workspace.mkdir()
    readonly.mkdir()
    (readonly / "data.txt").write_text("hello", encoding="utf-8")
    return VirtualFileSystem(workspace=workspace, readonly_roots=[readonly])


def test_write_inside_workspace(tmp_path):
    vfs = make_vfs(tmp_path)
    vfs.write_text("notes/a.txt", "content")
    target = tmp_path / "workspace" / "notes" / "a.txt"
    assert target.read_text(encoding="utf-8") == "content"


def test_dotdot_escape_rejected(tmp_path):
    vfs = make_vfs(tmp_path)
    with pytest.raises(PathEscapeError):
        vfs.write_text("../outside.txt", "bad")


def test_absolute_path_write_rejected(tmp_path):
    vfs = make_vfs(tmp_path)
    with pytest.raises(PathEscapeError):
        vfs.write_text(str(tmp_path / "workspace" / "abs.txt"), "bad")


def test_readonly_write_rejected(tmp_path):
    vfs = make_vfs(tmp_path)
    with pytest.raises(PathEscapeError):
        vfs.write_text("readonly/data.txt", "bad")


def test_readonly_read_allowed(tmp_path):
    vfs = make_vfs(tmp_path)
    assert vfs.read_text("readonly/data.txt") == "hello"
```

注意：只读根需要在 `VirtualFileSystem` 内部以别名挂载（本例中挂载别名为 `readonly`），构造时同时传入 `readonly_aliases: dict[str, Path]`，测试中为 `{"readonly": tmp_path / "readonly"}`。实现签名相应调整为 `VirtualFileSystem(workspace: Path, readonly_aliases: dict[str, Path])`。

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_vfs.py -v`
Expected: FAIL，模块不存在

- [ ] **Step 3: 实现路径校验**

`resolve` 执行顺序：

1. 若 `Path(path).is_absolute()` 直接抛 `PathEscapeError`；
2. 若路径任一段为 `..` 直接抛 `PathEscapeError`；
3. 路径首段命中只读别名时映射到对应只读根，否则拼接到 workspace；
4. `Path.resolve()` 后校验是否落在允许根内（`is_relative_to`）；
5. `mode == "write"` 时校验结果不在任何只读根下。

所有拒绝均抛 `PathEscapeError`，消息含原始输入与实际解析结果。

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest tests/test_vfs.py -v`
Expected: 5 passed

- [ ] **Step 5: 提交**

```bash
git add -A
git commit -m "feat: 虚拟文件系统与路径逃逸防护"
```

---

### Task 14: 持久化记忆

**Files:**
- Create: `src/procurement_agent/memory/store.py`, `tests/test_memory.py`
- Modify: `src/procurement_agent/agents/coordinator.py`

**Interfaces:**
- Consumes: `Engine`
- Produces:
  - `MemoryStore(engine)`：`preferences() -> dict`、`set_preference(key: str, value) -> None`、`supplier_stats(supplier_code: str) -> dict`、`record_order_outcome(supplier_code: str, sku: str, unit_price: float, approved: bool) -> None`、`render_prompt_block() -> str`

- [ ] **Step 1: 写失败测试**

`tests/test_memory.py` 覆盖四条：空库时 `preferences()` 返回默认值（含 `prefer_tier="A"`、`default_cost_center="CC-1001"`）；`set_preference` 后读取生效；`record_order_outcome` 两次后 `supplier_stats` 中的 `order_count` 为 2 且 `last_unit_price` 为最近一次价格；`render_prompt_block()` 输出包含"已加载采购偏好"且不包含完整历史明细。

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_memory.py -v`
Expected: FAIL，模块不存在

- [ ] **Step 3: 实现 MemoryStore**

数据写入 `agent_memory` 表：偏好用 `scope='preference'`，供应商统计用 `scope='supplier'`、`key=<code>`，`value` 存 JSON 字符串。`render_prompt_block` 输出模板：

```
已加载采购偏好：优先 {tier} 类供应商；单笔超过 ¥{threshold} 需人工审批；默认成本中心 {cost_center}。
历史参考：{code} 历史均价 ¥{avg:.2f}，累计成交 {n} 次。
```

阈值从 `ProcurementConfig` 传入（`MemoryStore(engine, config)`）。

- [ ] **Step 4: 在协调器中接入**

`parsing` handler 开始处调用 `memory.render_prompt_block()`，写入 `memory_loaded` 事件（`payload` 含偏好摘要文本）；`ordering` handler 完成后调用 `record_order_outcome` 并写 `memory_written` 事件。

- [ ] **Step 5: 运行测试确认通过**

Run: `python -m pytest tests/test_memory.py tests/test_coordinator.py -v`
Expected: 全部通过

- [ ] **Step 6: 提交**

```bash
git add -A
git commit -m "feat: 持久化记忆模块与偏好注入"
```

---

### Task 15: 上下文摘要中间件

**Files:**
- Create: `src/procurement_agent/middleware/base.py`, `src/procurement_agent/middleware/context_summarizer.py`, `tests/test_context_summarizer.py`
- Modify: `src/procurement_agent/agents/coordinator.py`

**Interfaces:**
- Consumes: `ProcurementConfig`
- Produces:
  - `Middleware` 协议：`name: str`；`on_event(task_id: str, event: dict) -> None`
  - `estimate_tokens(text: str) -> int`
  - `SummaryResult(before_tokens: int, after_tokens: int, dropped_categories: tuple[str, ...], summary: str)`
  - `ContextSummarizer(config, model_factory)`：`maybe_summarize(messages: list[dict], essential: dict) -> tuple[list[dict], SummaryResult | None]`

**保留/丢弃规则：** 保留采购要素、各阶段结论、未决问题、审批状态；丢弃完整工具返回原文，仅保留一行摘要。

- [ ] **Step 1: 写失败测试**

`tests/test_context_summarizer.py` 覆盖四条：

1. `estimate_tokens("采购订单")` 返回 4（中文按 1 字 1 token）；`estimate_tokens("abcdefgh")` 返回 2（英文 4 字符 1 token）；
2. 消息总 token 低于阈值时返回原消息且 `SummaryResult is None`；
3. 超过阈值时 `after_tokens < before_tokens`；
4. 压缩后的内容仍包含 `essential` 字典中的全部键值字符串，且 `dropped_categories` 含 `"tool_result"`。

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_context_summarizer.py -v`
Expected: FAIL，模块不存在

- [ ] **Step 3: 实现摘要中间件**

`estimate_tokens` 按字符类型分别累加后取整。`maybe_summarize` 先估算总 token：低于 `config.context_token_threshold` 时原样返回；超阈值时把 `role == "tool"` 的消息替换为 `{"role": "tool", "content": f"[工具结果摘要] {first_line}"}`，把 `essential` 字典序列化为一段固定文本插到消息头部，再调用模型生成一段压缩说明（测试中由 `FixedModelFactory` 返回固定文本）。最终返回压缩后的消息列表与 `SummaryResult`。

- [ ] **Step 4: 在 handler 中接入**

每个阶段 handler 结束时调用 `maybe_summarize`，若返回非 None 则写 `context_summarized` 事件，`payload` 含 `before_tokens`、`after_tokens`、`dropped_categories`；同时把 `after_tokens` 累加到 `tasks.token_usage`。

- [ ] **Step 5: 运行测试确认通过**

Run: `python -m pytest tests/test_context_summarizer.py tests/test_coordinator.py -v`
Expected: 全部通过

- [ ] **Step 6: 提交**

```bash
git add -A
git commit -m "feat: 上下文摘要中间件与 token 治理"
```

---

### Task 16: 受限执行器与策略守卫

**Files:**
- Create: `src/procurement_agent/sandbox/executor.py`, `src/procurement_agent/middleware/policy_guard.py`, `tests/test_sandbox_executor.py`, `tests/test_policy_guard.py`

**Interfaces:**
- Consumes: `VirtualFileSystem`、`PolicyDecision`、`TaskStore`
- Produces:
  - `ExecutionResult(ok: bool, stdout: str, stderr: str, exit_code: int, denied_reason: str | None)`
  - `DANGEROUS_COMMANDS: frozenset[str]`
  - `SandboxExecutor(workspace: Path, vfs: VirtualFileSystem, timeout_seconds: float = 10.0, max_output_bytes: int = 65536, env_allowlist: tuple[str, ...] = ("PATH", "TEMP", "TMP"))`：`run(argv: list[str], cwd: str = ".") -> ExecutionResult`
  - `PolicyGuard(store: TaskStore)`：`guard_tool_call(task_id: str, tool_name: str, args: dict, decision: PolicyDecision) -> bool`

- [ ] **Step 1: 写执行器失败测试**

`tests/test_sandbox_executor.py` 覆盖五条：

1. 执行允许命令（`python -c "print('ok')"`）成功且 stdout 含 `ok`；
2. 危险命令被拒绝：参数化测试覆盖 `rm`、`del`、`curl`、`wget`、`shutdown`，`ok is False` 且 `denied_reason` 非空；
3. 超时命令（`python -c "import time; time.sleep(30)"`，`timeout_seconds=0.5`）返回 `ok is False`；
4. 大输出被截断，长度不超过 `max_output_bytes` 且尾部含 `[truncated]`；
5. `cwd` 越出工作区时抛 `PathEscapeError`。

- [ ] **Step 2: 写策略守卫失败测试**

`tests/test_policy_guard.py` 覆盖：`allowed=True, requires_approval=False` 时不写事件并返回 True；`requires_approval=True` 时写一条 `policy_denied` 事件（`payload` 含 `tool`、`rules`、`reason`）并返回 False。

- [ ] **Step 3: 运行测试确认失败**

Run: `python -m pytest tests/test_sandbox_executor.py tests/test_policy_guard.py -v`
Expected: FAIL，模块不存在

- [ ] **Step 4: 实现 SandboxExecutor**

`DANGEROUS_COMMANDS` 至少包含 `rm`、`rmdir`、`del`、`format`、`curl`、`wget`、`powershell`、`cmd`、`shutdown`、`reg`、`sc`、`netsh`。执行前取 `os.path.basename(argv[0]).lower()` 去掉 `.exe` 后缀后校验。

通过校验后用 `subprocess.run` 执行：`cwd=vfs.resolve(cwd, mode="write")`、`env` 仅由白名单变量构成、`timeout=timeout_seconds`、`capture_output=True`、`text=True`、`shell=False`。超时捕获 `subprocess.TimeoutExpired` 返回 `ok=False` 与 `denied_reason="执行超时"`；输出超限时截断并追加 `...[truncated]`。

- [ ] **Step 5: 实现 PolicyGuard**

需要审批或不允许时写 `policy_denied` 事件并返回 False；否则返回 True。

- [ ] **Step 6: 运行测试确认通过**

Run: `python -m pytest tests/test_sandbox_executor.py tests/test_policy_guard.py -v`
Expected: 全部通过

- [ ] **Step 7: 提交**

```bash
git add -A
git commit -m "feat: 受限执行器与策略守卫中间件"
```

---

### Task 17: 异常分类与反思重试

**Files:**
- Create: `src/procurement_agent/middleware/reflection_retry.py`, `tests/test_reflection_retry.py`
- Modify: `src/procurement_agent/agents/coordinator.py`

**Interfaces:**
- Consumes: `TaskStore`、`ProcurementConfig`
- Produces:
  - `RetryExhausted(Exception)`，属性 `attempts: int`、`last_error: Exception`
  - `RetryEvent(attempt: int, reason: str, corrective_action: str)`
  - `classify_error(exc: Exception) -> Literal["retryable", "fatal"]`
  - `CORRECTIVE_ACTIONS: dict[str, str]`
  - `run_with_retry(fn: Callable[[int], T], *, max_attempts: int, store: TaskStore, task_id: str, agent: str, on_retry=None) -> T`

- [ ] **Step 1: 写失败测试**

`tests/test_reflection_retry.py` 覆盖五条：

1. 第一次抛 `TimeoutError`、第二次成功时返回结果，且 `task_events` 中有一条 `retry` 事件；
2. `retry` 事件的 `corrective_action` 等于 `CORRECTIVE_ACTIONS["TimeoutError"]`；
3. 抛 `ValueError` 时立即向上抛出且不写 `retry` 事件；
4. 连续失败超过 `max_attempts` 时抛 `RetryExhausted`，且 `retry` 事件数为 `max_attempts - 1`；
5. `RetryExhausted.attempts == max_attempts`。

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_reflection_retry.py -v`
Expected: FAIL，模块不存在

- [ ] **Step 3: 实现重试器**

`classify_error` 映射表：

| 异常 | 分类 | 修正动作 |
| --- | --- | --- |
| `TimeoutError` | retryable | `缩短查询范围后重试` |
| `ConnectionError` | retryable | `等待 1 秒后重连重试` |
| `json.JSONDecodeError` | retryable | `要求模型按 JSON schema 重新输出` |
| `PathEscapeError` | fatal | — |
| `ValueError` | fatal | — |
| `InsufficientQuotesError` | fatal | — |

`run_with_retry` 循环尝试，捕获异常后分类：`fatal` 直接抛出；`retryable` 时写 `retry` 事件（`payload={"attempt": n, "reason": type(exc).__name__, "corrective_action": ...}`）并再次尝试；达到上限抛 `RetryExhausted`。

- [ ] **Step 4: 在协调器中接入**

三个子 Agent 的调用均包在 `run_with_retry` 中，`max_attempts=config.retry_max_attempts`。捕获 `RetryExhausted` 后把任务转 `FAILED`，写 `error` 事件（`payload` 含异常类型与最后错误信息）。

- [ ] **Step 5: 运行测试确认通过**

Run: `python -m pytest tests/test_reflection_retry.py tests/test_coordinator.py -v`
Expected: 全部通过

- [ ] **Step 6: 提交**

```bash
git add -A
git commit -m "feat: 异常分类与反思重试中间件"
```

---

# 阶段 M4 · Web 界面

### Task 18: FastAPI 应用、任务接口与 SSE

**Files:**
- Create: `src/procurement_agent/web/app.py`, `src/procurement_agent/web/routes.py`, `src/procurement_agent/web/events.py`, `tests/test_web_api.py`

**Interfaces:**
- Consumes: `TaskStore`、`TaskRunner`、`ErpRepository`、`FaultRegistry`、`FixedModelFactory`
- Produces:
  - `create_app(db_path: Path, *, offline: bool = False) -> FastAPI`
  - REST 接口：`POST /api/tasks`、`GET /api/tasks`、`GET /api/tasks/{task_id}`、`GET /api/tasks/{task_id}/events`（SSE，支持 `after_seq` 查询参数）、`POST /api/tasks/{task_id}/approval`、`GET /api/suppliers`、`GET /api/quotes`、`GET /api/orders`、`GET /api/faults`、`POST /api/faults`、`POST /api/eval/run`、`GET /api/eval/latest`
  - SSE 事件格式：`id: {seq}\ndata: {json}\n\n`

- [ ] **Step 1: 写失败测试**

`tests/test_web_api.py` 用 `httpx.ASGITransport` 与 `offline=True` 覆盖：

1. `POST /api/tasks` 返回 200 且含 `task_id`；
2. `GET /api/tasks` 包含刚创建的任务；
3. `GET /api/tasks/{id}` 含 `state` 与 `events` 字段；
4. `POST /api/tasks/{id}/approval` 传 `decision="reject"` 且 `reason=""` 返回 422；
5. 写入订单后 `GET /api/orders` 包含该订单；
6. `POST /api/faults` 打开开关后 `GET /api/faults` 反映新状态。

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_web_api.py -v`
Expected: FAIL，模块不存在

- [ ] **Step 3: 实现应用工厂与路由**

`create_app` 完成：解析 db 路径 → `init_db` → 若 `suppliers` 表为空则 `seed_demo_data` → 构造 `FaultRegistry`、`ErpRepository`、`TaskStore`、`SkillRegistry`、`MemoryStore`、`ContextSummarizer`、`PolicyEngine` → `build_handlers` → `TaskRunner` → 注册路由与静态文件。

`offline=True` 时把 `model_factory` 换成 `FixedModelFactory`，并跳过真实网络调用，保证测试不触网。

审批请求体用 pydantic 模型校验：`decision` 限定 `approve|reject|revise`；`reject` 与 `revise` 时 `reason` 必填且去除空白后非空，否则返回 422。

- [ ] **Step 4: 实现 SSE 推送**

`events.py` 提供异步生成器，按 `after_seq` 轮询 `TaskStore.list_events`：有新事件立即 yield；无新事件 `await asyncio.sleep(0.5)`；客户端断开时结束生成器。响应头设置 `Cache-Control: no-cache` 与 `X-Accel-Buffering: no`。

- [ ] **Step 5: 运行测试确认通过**

Run: `python -m pytest tests/test_web_api.py -v`
Expected: 全部通过

- [ ] **Step 6: 提交**

```bash
git add -A
git commit -m "feat: FastAPI 服务、任务接口与 SSE 推送"
```

---

### Task 19: 任务看板页

**Files:**
- Create: `src/procurement_agent/web/templates/base.html`, `src/procurement_agent/web/templates/board.html`, `src/procurement_agent/web/static/app.css`, `src/procurement_agent/web/static/board.js`, `tests/test_board_page.py`

**Interfaces:**
- Consumes: `GET /api/tasks`、`POST /api/tasks`
- Produces: 路由 `GET /` 渲染看板页；区块 id 固定为 `#status-filters`、`#new-request`、`#task-list`

- [ ] **Step 1: 写失败测试**

`tests/test_board_page.py` 断言：`GET /` 返回 200；HTML 含五个筛选标签文案（全部 / 运行中 / 等待审批 / 已完成 / 失败）；含"填入示例需求"按钮与提交按钮；已创建任务的需求摘要出现在页面；`/static/app.css` 与 `/static/board.js` 均返回 200。

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_board_page.py -v`
Expected: FAIL，返回 404

- [ ] **Step 3: 实现 base 与看板页**

`base.html` 定义顶部导航（任务看板 `/`、数据台 `/data`、评测 `/eval`）与公共样式引用，提供 `{% block content %}`。

`board.html` 结构：筛选标签行 → 新建需求区（`<textarea id="request-text">` + 提交按钮 + "填入示例需求"按钮，示例文本为 `采购 50 箱 一次性无菌注射器，下周一前到货，成本中心 CC-1001`）→ 任务卡片列表容器。

`board.js` 逻辑：加载时 `GET /api/tasks` 渲染卡片；点提交 `POST /api/tasks` 成功后 `location.href = "/tasks/" + taskId`；点筛选标签按状态过滤本地列表；点卡片跳转执行页。

状态徽章颜色映射：`PENDING/PARSING/QUALIFYING/SOURCING/ORDER_DRAFTING` → 蓝色，`AWAITING_APPROVAL/REVISION_REQUIRED` → 橙色，`ORDERED/COMPLETED` → 绿色，`FAILED` → 红色。

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest tests/test_board_page.py -v`
Expected: 全部通过

- [ ] **Step 5: 提交**

```bash
git add -A
git commit -m "feat: 任务看板页与新建需求入口"
```

---

### Task 20: 采购执行页（三栏布局、任务树、时间线）

**Files:**
- Create: `src/procurement_agent/web/templates/task.html`, `src/procurement_agent/web/static/task.js`, `src/procurement_agent/web/static/tree.js`, `src/procurement_agent/web/static/timeline.js`, `tests/test_task_page.py`

**Interfaces:**
- Consumes: `GET /api/tasks/{id}`、SSE `/api/tasks/{id}/events`
- Produces: 路由 `GET /tasks/{task_id}`；区块 id 固定为 `#stage-bar`、`#left-panel`、`#task-tree`、`#timeline`、`#result-card`

- [ ] **Step 1: 写失败测试**

`tests/test_task_page.py` 断言：页面含 `#stage-bar`、`#left-panel`、`#task-tree`、`#timeline`、`#result-card`；含"已加载记忆"与"技能状态"标题；含五个阶段名称（需求解析 / 资质核验 / 比价分析 / 订单审批 / 完成）；`/static/task.js`、`/static/tree.js`、`/static/timeline.js` 均返回 200。

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_task_page.py -v`
Expected: FAIL，返回 404

- [ ] **Step 3: 实现三栏布局与左栏**

CSS 栅格：左栏固定 `320px`，右栏固定 `420px`，中栏 `1fr`。

左栏内容：需求原文、结构化要素（键值表）、记忆区（`#memory-block`）、技能状态区（四个技能标签，`loaded` 类为实心、`metadata-only` 类为空心并显示"仅描述"）。技能状态由任务详情接口返回的 `loaded_skills` 数组驱动，鼠标悬停在"仅描述"标签时用 `title` 属性提示技能描述。

- [ ] **Step 4: 实现顶部状态条**

`#stage-bar` 渲染五个阶段节点，根据当前任务状态计算每个节点样式：已完成（打勾）、当前（高亮）、被驳回（红色）。右侧显示运行状态文案、已耗时（由 `created_at` 与当前时间计算，每 30 秒刷新一次）、token 计数（取任务详情的 `token_usage.total`）。

- [ ] **Step 5: 实现任务树**

`tree.js` 消费事件数组，按以下规则聚合：

- `agent_delegation` → 在中栏创建子 Agent 节点，`payload["to"]` 作为节点标题；
- `tool_call` → 在该子 Agent 下创建步骤行，`payload["tool"]` 作为步骤名；
- `tool_result` → 更新对应步骤为成功并显示耗时；
- `retry` → 给对应步骤加角标"第 N 次重试 · 原因：X"；
- `policy_denied` → 步骤整行加橙色类并标注"等待审批"；
- `skill_loaded` → 在左栏技能标签上切换为已加载状态。

点击步骤行派发 `CustomEvent("step-selected", {detail: {seq}})`。

- [ ] **Step 6: 实现时间线**

`timeline.js` 把事件渲染为平铺列表，格式 `[HH:MM:SS] {agent} {中文事件文案}`；中间件事件加前缀标签，例如 `[中间件·上下文摘要] 12.4k → 3.6k tokens`、`[中间件·策略引擎] 命中规则：...`、`[技能] 已加载 price_comparison 全文`。顶部两个下拉框按 `agent` 与 `event_type` 过滤。

监听 `step-selected`：滚动到对应 `seq` 的元素并加高亮类，同时展开该事件的 `payload` 详情（入参、返回摘要、重试历史）。

- [ ] **Step 7: 接入 SSE 与结果卡片**

`task.js` 在页面加载后用 `EventSource` 订阅 `/api/tasks/{id}/events?after_seq=N`，收到事件后追加到本地事件数组并重新渲染任务树与时间线，同步更新 `after_seq`。

当任务状态变为 `COMPLETED` 时渲染 `#result-card`：订单号、最终供应商、总金额、相比最高报价节省金额、总耗时、人工介入次数。

- [ ] **Step 8: 运行测试确认通过**

Run: `python -m pytest tests/test_task_page.py -v`
Expected: 全部通过

- [ ] **Step 9: 提交**

```bash
git add -A
git commit -m "feat: 采购执行页三栏布局、任务树与时间线"
```

---

### Task 21: 审批卡片交互

**Files:**
- Create: `src/procurement_agent/web/static/approval.js`, `src/procurement_agent/web/templates/partials/approval_card.html`, `tests/test_approval_flow.py`

**Interfaces:**
- Consumes: `POST /api/tasks/{id}/approval`
- Produces: 区块 id `#approval-card`、`#approval-reason`、`#btn-approve`、`#btn-reject`、`#btn-revise`；审批卡片数据来自任务详情接口的 `pending_approval` 字段（含 `matched_rules`、`order_draft`、`comparison_reason`）

- [ ] **Step 1: 写失败测试**

`tests/test_approval_flow.py` 覆盖（离线模式，金额超阈值用例）：

1. 任务进入 `AWAITING_APPROVAL` 后，任务详情接口返回非空的 `pending_approval`，其中 `matched_rules` 至少一条含 `"阈值"`；
2. `pending_approval.order_draft` 含 `supplier_name`、`total_amount`、`lead_days`、`cost_center`；
3. 调用审批接口 `decision="approve"` 后任务状态变为 `ORDERED` 或 `COMPLETED`，且 `GET /api/orders` 中出现该订单；
4. 调用 `decision="reject"` 且带理由后任务回到 `SOURCING` 或 `REVISION_REQUIRED`，事件流中出现 `approval_decided`；
5. 驳回后重跑产生第二条 `agent_delegation` 指向 `sourcing`。

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_approval_flow.py -v`
Expected: FAIL，`pending_approval` 字段不存在

- [ ] **Step 3: 在任务详情接口补 pending_approval**

当任务状态为 `AWAITING_APPROVAL` 时，接口额外返回 `pending_approval`：从最近一次 `approval_requested` 事件取 `matched_rules`，从订单草稿 payload 取订单摘要，从比价事件取 `reason`。若任务不在该状态则返回 `null`。

- [ ] **Step 4: 实现审批卡片**

`approval.js` 在检测到 `pending_approval` 非空时于 `#timeline` 顶部插入卡片，内容自上而下：命中的规则原文列表 → 订单摘要表 → 比价结论与推荐理由（推荐价非最低价时必须显示）→ 审批意见输入框 → 三个按钮。

按钮行为：`approve` 与 `revise` 允许理由为空（`revise` 仍要求填写修改意见，前端在为空时提示）；`reject` 理由为空时前端直接拦截并显示中文提示"驳回必须填写理由"，不发起请求。请求成功后刷新任务详情并重新渲染。

- [ ] **Step 5: 运行测试确认通过**

Run: `python -m pytest tests/test_approval_flow.py -v`
Expected: 全部通过

- [ ] **Step 6: 提交**

```bash
git add -A
git commit -m "feat: 审批卡片交互与三种处置流程"
```

---

### Task 22: 数据台与故障注入面板

**Files:**
- Create: `src/procurement_agent/web/templates/data.html`, `src/procurement_agent/web/static/data.js`, `tests/test_data_page.py`

**Interfaces:**
- Consumes: `GET /api/suppliers`、`GET /api/quotes`、`GET /api/orders`、`GET /api/faults`、`POST /api/faults`
- Produces: 路由 `GET /data`；标签页 id `#tab-suppliers`、`#tab-quotes`、`#tab-orders`；故障面板 id `#fault-panel`

- [ ] **Step 1: 写失败测试**

`tests/test_data_page.py` 断言：`GET /data` 返回 200；含三个标签页标题与"故障注入"标题；开关文案包含"让供应商 B 资质过期"、"让供应商 C 停止报价"、"让全部报价超预算"；`/static/data.js` 返回 200；调用 `POST /api/faults` 打开开关后 `GET /api/suppliers` 反映资质过期状态。

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_data_page.py -v`
Expected: FAIL，返回 404

- [ ] **Step 3: 实现页面与交互**

三个标签页分别渲染供应商表（含资质有效期与临期高亮）、报价表（含供应商、单价、运费、交期）、订单表（含审批记录列）。故障面板为三个开关，切换即 `POST /api/faults`，成功后重新拉取当前标签页数据。点订单行跳转 `/tasks/{task_id}`。

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest tests/test_data_page.py -v`
Expected: 全部通过

- [ ] **Step 5: 提交**

```bash
git add -A
git commit -m "feat: 数据台与故障注入面板"
```

---

### Task 23: 评测页

**Files:**
- Create: `src/procurement_agent/web/templates/eval.html`, `src/procurement_agent/web/static/eval.js`, `tests/test_eval_page.py`

**Interfaces:**
- Consumes: `POST /api/eval/run`、`GET /api/eval/latest`
- Produces: 路由 `GET /eval`；区块 id `#eval-run`、`#eval-metrics`、`#eval-failures`

- [ ] **Step 1: 写失败测试**

`tests/test_eval_page.py` 断言：`GET /eval` 返回 200；含"运行评测"按钮与五个指标标题（用例总数 / 成功率 / 人工介入率 / 平均耗时 / 上下文 token 峰值）；`POST /api/eval/run` 触发后 `GET /api/eval/latest` 返回非空报告且含 `success_rate` 字段；失败用例列表每项含 `task_id`。

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_eval_page.py -v`
Expected: FAIL，返回 404

- [ ] **Step 3: 实现页面**

`eval.js` 点击按钮后 `POST /api/eval/run`，轮询 `GET /api/eval/latest` 直到 `status == "finished"`，随后渲染指标卡片与失败用例表。失败用例行点击跳转 `/tasks/{task_id}`。

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest tests/test_eval_page.py -v`
Expected: 全部通过

- [ ] **Step 5: 提交**

```bash
git add -A
git commit -m "feat: 评测页与指标展示"
```

---

# 阶段 M5 · 评测与文档

### Task 24: 评测用例集与运行器

**Files:**
- Create: `src/procurement_agent/eval/cases.yaml`, `src/procurement_agent/eval/runner.py`, `src/procurement_agent/eval/metrics.py`, `tests/test_eval_runner.py`

**Interfaces:**
- Consumes: `create_app` 的离线依赖组装、`TaskStore`、`FaultRegistry`
- Produces:
  - `EvalCase(id: str, request_text: str, faults: dict[str, bool], expect_state: str, expect_approval: bool)`
  - `load_cases(path: Path) -> list[EvalCase]`
  - `EvalReport(total, success_count, success_rate, intervention_count, intervention_rate, avg_duration_ms, token_peak, token_mean, failures: list[dict], status)`
  - `run_eval(cases: list[EvalCase], workspace: Path) -> EvalReport`

- [ ] **Step 1: 写 30 条用例**

`cases.yaml` 固定 30 条，分布为：正常路径 12 条；`supplier_b_expired` 5 条；`supplier_c_no_quote` 5 条；`all_quotes_over_budget` 5 条；组合故障 3 条。每条含 `id`、`request_text`、`faults`、`expect_state`、`expect_approval`。

- [ ] **Step 2: 写失败测试**

`tests/test_eval_runner.py` 覆盖：

1. `load_cases` 返回 30 条且 id 唯一；
2. 用小规模自造用例（3 条）运行 `run_eval` 返回报告，字段范围合法（`0 <= success_rate <= 1`）；
3. 同一份用例连续运行两次，`success_rate` 与 `token_peak` 完全一致（可复现性）；
4. 失败用例的 `task_id` 出现在 `failures` 中且能在 `TaskStore` 中查到。

- [ ] **Step 3: 运行测试确认失败**

Run: `python -m pytest tests/test_eval_runner.py -v`
Expected: FAIL，模块不存在

- [ ] **Step 4: 实现运行器**

每条用例独立使用临时 db 文件（`tempfile.mkdtemp()` 下），保证用例之间互不污染；按 `faults` 字段设置开关；使用离线模型工厂运行任务；收集最终状态、是否发生审批、耗时与 token 峰值；与 `expect_state` / `expect_approval` 比对得出成功与否。`metrics.py` 负责聚合计算，保持纯函数以便单独测试。

- [ ] **Step 5: 运行测试确认通过**

Run: `python -m pytest tests/test_eval_runner.py -v`
Expected: 全部通过

- [ ] **Step 6: 运行完整评测并产出报告**

Run: `python -m procurement_agent.eval.runner --out eval_results/latest.json`
Expected: 生成 JSON 报告，包含全部五个指标与失败用例列表；重复运行结果一致。

- [ ] **Step 7: 提交**

```bash
git add -A
git commit -m "feat: 评测用例集与可复现评测运行器"
```

---

### Task 25: 项目文档与演示脚本

**Files:**
- Create: `README.md`, `docs/architecture.md`, `docs/sandbox-security.md`, `docs/demo-script.md`
- Modify: `docs/decision-log.md`

**Interfaces:**
- Consumes: 全部已完成模块
- Produces: 可交付文档集

- [ ] **Step 1: 写 README**

包含：一句话介绍、架构图（Mermaid）、快速开始（安装依赖、配置 `.env`、初始化数据库、启动 `uvicorn`）、目录结构说明、演示路径、评测运行方式、v1 范围与不做清单的链接（指向 `PRD.md`）。

- [ ] **Step 2: 写架构文档**

`docs/architecture.md` 覆盖：主 Agent 与三类子 Agent 的职责边界；状态机与 DeepAgents 的职责划分（为什么自研状态机是唯一状态源）；事件模型与数据表关系；中间件体系的挂载点；两次请求的完整时序图（正常路径与审批驳回路径）。

- [ ] **Step 3: 写安全设计文档**

`docs/sandbox-security.md` 覆盖：双层沙箱的具体实现；危险命令清单与判定方式；路径逃逸防护的四种攻击向量与对应拒绝点；审批策略的三条规则；以及"生产环境如何升级为容器或微 VM 隔离"的演进方案与代价分析。

- [ ] **Step 4: 写演示脚本**

`docs/demo-script.md` 提供 5 分钟分镜：00:00-00:40 看板页提交示例需求；00:40-02:00 执行页观察任务树与时间线；02:00-03:00 打开数据台故障开关"让供应商 B 资质过期"，重跑并讲解改选理由；03:00-04:00 触发超预算审批并现场处置；04:00-05:00 运行评测展示指标。每段附讲解词要点与可能被追问的问题及回答要点。

- [ ] **Step 5: 提交**

```bash
git add -A
git commit -m "docs: 架构、安全、演示与说明文档"
```

---

## 自查结果

**Spec 覆盖检查：** PRD 的 13 条功能需求均有对应 Task——FR-01 → Task 12；FR-02 → Task 9；FR-03 → Task 10；FR-04 → Task 11；FR-05 → Task 6/21；FR-06 → Task 7；FR-07 → Task 13；FR-08 → Task 14；FR-09 → Task 15；FR-10 → Task 11/16；FR-11 → Task 17；FR-12 → Task 18/20；FR-13 → Task 24。PRD 第 6 节的四个页面 → Task 19/20/21/22/23。

**占位符检查：** 全部 Task 均已给出具体文件路径、接口签名、测试断言与实现要点，无 TBD / TODO。

**类型一致性检查：** `StageResult`、`PolicyDecision`、`QualificationOutcome`、`SourcingOutcome`、`OrderDraft`、`SummaryResult`、`RetryEvent`、`ExecutionResult` 均在首次出现的 Task 中定义，后续 Task 只引用不重定义。

## 执行方式选择

两种执行方式：

1. **Subagent-Driven（推荐）**：每个 Task 派发一个全新 subagent 实现，Task 之间由我做审查与门禁，迭代快、上下文干净。
2. **Inline Execution**：在当前会话里按批次执行，带检查点暂停评审。
