from __future__ import annotations

import json
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Engine

from procurement_agent.state.models import (
    ALLOWED_TRANSITIONS,
    TaskEvent,
    TaskRecord,
    TaskState,
)


class InvalidTransition(Exception):
    def __init__(self, from_state: TaskState, to_state: TaskState) -> None:
        super().__init__(f"非法状态转移: {from_state.value} -> {to_state.value}")
        self.from_state = from_state
        self.to_state = to_state


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _row_to_record(row: Any) -> TaskRecord:
    return TaskRecord(
        id=row.id,
        request_text=row.request_text,
        state=TaskState(row.state),
        structured_request=json.loads(row.structured_request) if row.structured_request else None,
        created_at=row.created_at,
        updated_at=row.updated_at,
        finished_at=row.finished_at,
        human_interventions=row.human_interventions,
        token_usage=json.loads(row.token_usage) if row.token_usage else {},
    )


class TaskStore:
    """任务状态与事件流的唯一持久化入口。"""

    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    # ---------- 任务 ----------

    def create_task(self, request_text: str) -> str:
        task_id = f"t-{uuid.uuid4().hex[:12]}"
        now = _now()
        with self.engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO tasks (id, request_text, state, created_at, updated_at) "
                    "VALUES (:id, :text, :state, :now, :now)"
                ),
                {
                    "id": task_id,
                    "text": request_text,
                    "state": TaskState.PENDING.value,
                    "now": now,
                },
            )
        return task_id

    def _raw_task(self, conn: Any, task_id: str) -> Any:
        row = conn.execute(
            text("SELECT * FROM tasks WHERE id = :id"), {"id": task_id}
        ).one_or_none()
        if row is None:
            raise KeyError(f"任务不存在: {task_id}")
        return row

    def get_task(self, task_id: str) -> TaskRecord:
        with self.engine.connect() as conn:
            return _row_to_record(self._raw_task(conn, task_id))

    def list_tasks(self, state: TaskState | None = None) -> list[TaskRecord]:
        sql = "SELECT * FROM tasks"
        params: dict[str, Any] = {}
        if state is not None:
            sql += " WHERE state = :state"
            params["state"] = state.value
        sql += " ORDER BY created_at DESC, id DESC"
        with self.engine.connect() as conn:
            rows = conn.execute(text(sql), params).all()
        return [_row_to_record(row) for row in rows]

    def transition(self, task_id: str, to_state: TaskState) -> None:
        now = _now()
        with self.engine.begin() as conn:
            row = self._raw_task(conn, task_id)
            from_state = TaskState(row.state)
            if to_state not in ALLOWED_TRANSITIONS[from_state]:
                raise InvalidTransition(from_state, to_state)
            conn.execute(
                text("UPDATE tasks SET state = :state, updated_at = :now WHERE id = :id"),
                {"state": to_state.value, "now": now, "id": task_id},
            )
            self._append_event(
                conn,
                task_id,
                agent="coordinator",
                event_type="stage_change",
                payload={"from": from_state.value, "to": to_state.value},
            )

    def set_structured_request(self, task_id: str, payload: dict[str, Any]) -> None:
        with self.engine.begin() as conn:
            conn.execute(
                text(
                    "UPDATE tasks SET structured_request = :payload, updated_at = :now "
                    "WHERE id = :id"
                ),
                {"payload": json.dumps(payload, ensure_ascii=False), "now": _now(), "id": task_id},
            )

    def record_intervention(self, task_id: str) -> None:
        with self.engine.begin() as conn:
            conn.execute(
                text(
                    "UPDATE tasks SET human_interventions = human_interventions + 1, "
                    "updated_at = :now WHERE id = :id"
                ),
                {"now": _now(), "id": task_id},
            )

    def add_tokens(self, task_id: str, tokens: int, total: int | None = None) -> None:
        with self.engine.begin() as conn:
            row = self._raw_task(conn, task_id)
            usage = json.loads(row.token_usage) if row.token_usage else {}
            usage["total"] = int(usage.get("total", 0)) + int(tokens)
            if total is not None:
                usage["peak"] = max(int(usage.get("peak", 0)), int(total))
            conn.execute(
                text("UPDATE tasks SET token_usage = :usage, updated_at = :now WHERE id = :id"),
                {"usage": json.dumps(usage), "now": _now(), "id": task_id},
            )

    def finish_task(self, task_id: str, state: TaskState) -> None:
        now = _now()
        with self.engine.begin() as conn:
            conn.execute(
                text(
                    "UPDATE tasks SET state = :state, finished_at = :now, updated_at = :now "
                    "WHERE id = :id"
                ),
                {"state": state.value, "now": now, "id": task_id},
            )

    # ---------- 事件 ----------

    def _append_event(
        self,
        conn: Any,
        task_id: str,
        agent: str,
        event_type: str,
        payload: dict[str, Any],
    ) -> TaskEvent:
        created_at = _now()
        seq = int(
            conn.execute(
                text(
                    "SELECT COALESCE(MAX(seq), 0) + 1 FROM task_events WHERE task_id = :id"
                ),
                {"id": task_id},
            ).scalar_one()
        )
        conn.execute(
            text(
                "INSERT INTO task_events (task_id, seq, agent, event_type, payload, created_at) "
                "VALUES (:id, :seq, :agent, :type, :payload, :now)"
            ),
            {
                "id": task_id,
                "seq": seq,
                "agent": agent,
                "type": event_type,
                "payload": json.dumps(payload, ensure_ascii=False),
                "now": created_at,
            },
        )
        return TaskEvent(
            task_id=task_id,
            seq=seq,
            agent=agent,
            event_type=event_type,
            payload=payload,
            created_at=created_at,
        )

    def append_event(
        self, task_id: str, agent: str, event_type: str, payload: dict[str, Any]
    ) -> TaskEvent:
        with self.engine.begin() as conn:
            return self._append_event(conn, task_id, agent, event_type, payload)

    def list_events(self, task_id: str, after_seq: int = 0) -> list[TaskEvent]:
        with self.engine.connect() as conn:
            rows = conn.execute(
                text(
                    "SELECT * FROM task_events WHERE task_id = :id AND seq > :after "
                    "ORDER BY seq"
                ),
                {"id": task_id, "after": after_seq},
            ).all()
        return [
            TaskEvent(
                task_id=row.task_id,
                seq=row.seq,
                agent=row.agent,
                event_type=row.event_type,
                payload=json.loads(row.payload) if row.payload else {},
                created_at=row.created_at,
            )
            for row in rows
        ]

