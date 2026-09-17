from __future__ import annotations

import asyncio
import json
from typing import AsyncIterator

from procurement_agent.state.store import TaskStore

POLL_INTERVAL_SECONDS = 0.5


async def event_stream(
    store: TaskStore,
    task_id: str,
    after_seq: int = 0,
    poll_interval: float = POLL_INTERVAL_SECONDS,
) -> AsyncIterator[str]:
    """按 seq 增量推送任务事件，供 SSE 使用。"""
    cursor = after_seq
    while True:
        events = await asyncio.to_thread(store.list_events, task_id, cursor)
        for event in events:
            cursor = event.seq
            payload = {
                "seq": event.seq,
                "agent": event.agent,
                "event_type": event.event_type,
                "payload": event.payload,
                "created_at": event.created_at,
            }
            yield f"id: {event.seq}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"
        await asyncio.sleep(poll_interval)

