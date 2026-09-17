from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class Middleware(Protocol):
    """可插拔中间件协议。"""

    name: str

    def on_event(self, task_id: str, event: dict[str, Any]) -> None:  # pragma: no cover
        ...

