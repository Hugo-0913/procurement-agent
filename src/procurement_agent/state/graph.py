from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any, Callable, TypedDict

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt

from procurement_agent.config import ProcurementConfig
from procurement_agent.state.models import TaskState
from procurement_agent.state.nodes import StageResult
from procurement_agent.state.store import InvalidTransition, TaskStore

Handler = Callable[[str, dict[str, Any]], StageResult]


class PipelineState(TypedDict, total=False):
    task_id: str
    request_text: str
    context: dict[str, Any]
    needs_approval: bool
    matched_rules: list[str]
    approval: dict[str, Any]
    outcome: dict[str, Any]
    prefilled: dict[str, Any]


def _saver_for(store: TaskStore) -> SqliteSaver:
    database = store.engine.url.database
    connection = sqlite3.connect(database, check_same_thread=False)
    return SqliteSaver(connection)


def build_stage_graph(
    store: TaskStore,
    handlers: dict[TaskState, Handler],
    config: ProcurementConfig,
    checkpointer: SqliteSaver | None = None,
):
    """构建阶段推进图。审批环节使用 LangGraph 持久化中断。"""
    saver = checkpointer or _saver_for(store)

    def _stage_node(stage: TaskState):
        def node(state: PipelineState) -> dict[str, Any]:
            task_id = state["task_id"]
            handler = handlers.get(stage)
            if handler is None:
                raise KeyError(f"缺少阶段处理器: {stage.value}")
            result = handler(task_id, dict(state.get("context", {})))
            current = store.get_task(task_id).state
            if result.state is not current:
                store.transition(task_id, result.state)
            context = {**state.get("context", {}), **result.payload}
            update: dict[str, Any] = {"context": context}
            if "needs_approval" in result.payload:
                update["needs_approval"] = bool(result.payload["needs_approval"])
            if "matched_rules" in result.payload:
                update["matched_rules"] = list(result.payload["matched_rules"])
            return update

        return node

    def approval_gate(state: PipelineState) -> dict[str, Any]:
        task_id = state["task_id"]
        matched_rules = list(state.get("matched_rules", []))
        if not state.get("needs_approval"):
            return {}

        current = store.get_task(task_id).state
        if current is not TaskState.AWAITING_APPROVAL:
            store.transition(task_id, TaskState.AWAITING_APPROVAL)
            store.append_event(
                task_id,
                agent="policy_engine",
                event_type="approval_requested",
                payload={"matched_rules": matched_rules},
            )

        decision = interrupt(
            {"task_id": task_id, "matched_rules": matched_rules, "type": "order_approval"}
        )
        payload = decision if isinstance(decision, dict) else {"decision": str(decision)}
        store.record_intervention(task_id)
        store.record_approval(
            task_id=task_id,
            decision=str(payload.get("decision", "")),
            operator=str(payload.get("operator", "")),
            reason=str(payload.get("reason", "")),
            matched_rules=matched_rules,
        )
        store.append_event(
            task_id,
            agent="human",
            event_type="approval_decided",
            payload=payload,
        )
        return {"approval": payload}

    def route_after_approval(state: PipelineState) -> str:
        task_id = state["task_id"]
        current = store.get_task(task_id).state
        if current is not TaskState.AWAITING_APPROVAL:
            # 本轮未产生新的审批请求（例如驳回后重跑），按正常路径继续。
            return "ordering"
        decision = str(state.get("approval", {}).get("decision", "approve"))
        if decision == "reject":
            store.transition(task_id, TaskState.REVISION_REQUIRED)
            return "sourcing"
        if decision == "revise":
            store.transition(task_id, TaskState.ORDER_DRAFTING)
            return "order_drafting"
        return "ordering"

    def route_after_parsing(state: PipelineState) -> str:
        if state.get("context", {}).get("needs_clarification"):
            return "end"
        return "qualifying"

    def finish(state: PipelineState) -> dict[str, Any]:
        task_id = state["task_id"]
        store.transition(task_id, TaskState.COMPLETED)
        store.finish_task(task_id, TaskState.COMPLETED)
        store.append_event(
            task_id,
            agent="coordinator",
            event_type="task_finished",
            payload={"state": TaskState.COMPLETED.value},
        )
        return {}

    graph = StateGraph(PipelineState)
    graph.add_node("parsing", _stage_node(TaskState.PARSING))
    graph.add_node("qualifying", _stage_node(TaskState.QUALIFYING))
    graph.add_node("sourcing", _stage_node(TaskState.SOURCING))
    graph.add_node("order_drafting", _stage_node(TaskState.ORDER_DRAFTING))
    graph.add_node("approval_gate", approval_gate)
    graph.add_node("ordering", _stage_node(TaskState.ORDERED))
    graph.add_node("finish", finish)

    graph.add_edge(START, "parsing")
    graph.add_conditional_edges(
        "parsing", route_after_parsing, {"qualifying": "qualifying", "end": END}
    )
    graph.add_edge("qualifying", "sourcing")
    graph.add_edge("sourcing", "order_drafting")
    graph.add_edge("order_drafting", "approval_gate")
    graph.add_conditional_edges(
        "approval_gate",
        route_after_approval,
        {"ordering": "ordering", "sourcing": "sourcing", "order_drafting": "order_drafting"},
    )
    graph.add_edge("ordering", "finish")
    graph.add_edge("finish", END)

    return graph.compile(checkpointer=saver)


class TaskRunner:
    """任务执行入口：负责启动任务与恢复挂起的审批。"""

    def __init__(self, store: TaskStore, graph) -> None:
        self.store = store
        self.graph = graph

    def _config(self, task_id: str) -> dict[str, Any]:
        return {"configurable": {"thread_id": task_id}}

    def start(self, request_text: str, prefilled: dict[str, Any] | None = None) -> str:
        task_id = self.store.create_task(request_text)
        self.run(task_id, request_text, prefilled)
        return task_id

    def run(
        self,
        task_id: str,
        request_text: str,
        prefilled: dict[str, Any] | None = None,
    ) -> None:
        """在已创建的任务上执行流程（供后台线程调用）。"""
        current = self.store.get_task(task_id).state
        if current is not TaskState.PARSING:
            self.store.transition(task_id, TaskState.PARSING)
        try:
            self.graph.invoke(
                {
                    "task_id": task_id,
                    "request_text": request_text,
                    # 点选式输入放在 context 里：阶段处理器读到的是 context 子字典，
                    # 放在图状态顶层会导致下游读不到（曾经因此静默走回模型解析）。
                    "context": {"prefilled": prefilled} if prefilled else {},
                    "needs_approval": False,
                    "matched_rules": [],
                },
                self._config(task_id),
            )
        except Exception as exc:  # noqa: BLE001
            self._fail(task_id, exc)

    def continue_after_clarification(self, task_id: str, answer: str) -> None:
        """把用户的补充说明并回需求文本，从解析阶段续跑。"""
        record = self.store.get_task(task_id)
        if record.state is not TaskState.AWAITING_CLARIFICATION:
            raise InvalidTransition(record.state, TaskState.PARSING)
        # 补充说明是"修正"而不是"追加"：保留最新一条即可。
        # 早期实现直接往末尾追加，用户改两次就会攒出多条互相矛盾的补充，
        # 模型反而更抓不住重点（曾出现"补充了注射器仍解析成苹果"）。
        base = record.request_text.split("\n补充说明：")[0].strip()
        merged = f"{base}\n补充说明：{answer}"
        self.store.set_request_text(task_id, merged)
        self.store.append_event(
            task_id,
            agent="human",
            event_type="clarification_answered",
            payload={"answer": answer},
        )
        self.run(task_id, merged)

    def resume(self, task_id: str, decision: str, operator: str, reason: str = "") -> None:
        try:
            self.graph.invoke(
                Command(resume={"decision": decision, "operator": operator, "reason": reason}),
                self._config(task_id),
            )
        except Exception as exc:  # noqa: BLE001
            self._fail(task_id, exc)

    def _fail(self, task_id: str, exc: Exception) -> None:
        record = self.store.get_task(task_id)
        if record.state is not TaskState.FAILED:
            self.store.transition(task_id, TaskState.FAILED)
        self.store.append_event(
            task_id,
            agent="coordinator",
            event_type="error",
            payload={"error": type(exc).__name__, "message": str(exc)},
        )
        self.store.finish_task(task_id, TaskState.FAILED)
