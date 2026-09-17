from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Callable, Literal, TypeVar

from procurement_agent.state.store import TaskStore

T = TypeVar("T")

RETRYABLE_ERRORS: tuple[type[BaseException], ...] = (
    json.JSONDecodeError,  # 必须先于 ValueError（JSONDecodeError 是其子类）
    TimeoutError,
    ConnectionError,
)

CORRECTIVE_ACTIONS: dict[str, str] = {
    "TimeoutError": "缩短查询范围后重试",
    "ConnectionError": "等待 1 秒后重连重试",
    "JSONDecodeError": "要求模型按 JSON schema 重新输出",
}


class RetryExhausted(Exception):
    def __init__(self, attempts: int, last_error: BaseException) -> None:
        super().__init__(f"重试 {attempts} 次后仍失败：{last_error!r}")
        self.attempts = attempts
        self.last_error = last_error


@dataclass(frozen=True)
class RetryEvent:
    attempt: int
    reason: str
    corrective_action: str


def classify_error(exc: BaseException) -> Literal["retryable", "fatal"]:
    return "retryable" if isinstance(exc, RETRYABLE_ERRORS) else "fatal"


def run_with_retry(
    fn: Callable[[int], T],
    *,
    max_attempts: int,
    store: TaskStore,
    task_id: str,
    agent: str,
    on_retry: Callable[[RetryEvent], None] | None = None,
) -> T:
    attempt = 0
    last_error: BaseException | None = None
    while attempt < max_attempts:
        attempt += 1
        try:
            return fn(attempt)
        except BaseException as exc:  # noqa: BLE001
            if classify_error(exc) == "fatal":
                raise
            last_error = exc
            if attempt >= max_attempts:
                break
            name = type(exc).__name__
            event = RetryEvent(
                attempt=attempt,
                reason=name,
                corrective_action=CORRECTIVE_ACTIONS.get(name, "修正参数后重试"),
            )
            if on_retry is not None:
                on_retry(event)
            store.append_event(
                task_id,
                agent=agent,
                event_type="retry",
                payload={
                    "attempt": event.attempt,
                    "reason": event.reason,
                    "corrective_action": event.corrective_action,
                },
            )
    assert last_error is not None
    raise RetryExhausted(attempts=max_attempts, last_error=last_error)

