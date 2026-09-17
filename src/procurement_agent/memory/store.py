from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from sqlalchemy.engine import Engine

from procurement_agent.config import ProcurementConfig

PREFERENCE_SCOPE = "preference"
SUPPLIER_SCOPE = "supplier"


def _default_preferences(config: ProcurementConfig) -> dict[str, Any]:
    return {
        "prefer_tier": "A",
        "default_cost_center": "CC-1001",
        "approval_threshold": config.approval_threshold,
    }


class MemoryStore:
    """跨任务复用的采购偏好与供应商历史，落在 agent_memory 表。"""

    def __init__(self, engine: Engine, config: ProcurementConfig) -> None:
        self.engine = engine
        self.config = config

    # ---------- 通用读写 ----------

    def _get(self, scope: str, key: str) -> Any | None:
        with self.engine.connect() as conn:
            from sqlalchemy import text

            row = conn.execute(
                text(
                    "SELECT value FROM agent_memory WHERE scope = :scope AND key = :key"
                ),
                {"scope": scope, "key": key},
            ).one_or_none()
        return json.loads(row.value) if row else None

    def _set(self, scope: str, key: str, value: Any) -> None:
        from sqlalchemy import text

        now = datetime.now().isoformat(timespec="seconds")
        payload = json.dumps(value, ensure_ascii=False)
        with self.engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO agent_memory (scope, key, value, updated_at) "
                    "VALUES (:scope, :key, :value, :now) "
                    "ON CONFLICT(scope, key) DO UPDATE SET value = :value, updated_at = :now"
                ),
                {"scope": scope, "key": key, "value": payload, "now": now},
            )

    # ---------- 采购偏好 ----------

    def preferences(self) -> dict[str, Any]:
        result = _default_preferences(self.config)
        with self.engine.connect() as conn:
            from sqlalchemy import text

            rows = conn.execute(
                text("SELECT key, value FROM agent_memory WHERE scope = :scope"),
                {"scope": PREFERENCE_SCOPE},
            ).all()
        for row in rows:
            result[row.key] = json.loads(row.value)
        return result

    def set_preference(self, key: str, value: Any) -> None:
        self._set(PREFERENCE_SCOPE, key, value)

    # ---------- 供应商历史 ----------

    def supplier_stats(self, supplier_code: str) -> dict[str, Any]:
        stats = self._get(SUPPLIER_SCOPE, supplier_code) or {}
        return {
            "order_count": int(stats.get("order_count", 0)),
            "last_unit_price": stats.get("last_unit_price"),
            "avg_unit_price": stats.get("avg_unit_price"),
            "approved_count": int(stats.get("approved_count", 0)),
        }

    def record_order_outcome(
        self,
        supplier_code: str,
        sku: str,
        unit_price: float,
        approved: bool,
    ) -> None:
        stats = self.supplier_stats(supplier_code)
        count = stats["order_count"]
        prev_avg = stats["avg_unit_price"] or 0.0
        new_count = count + 1
        new_avg = (prev_avg * count + float(unit_price)) / new_count
        self._set(
            SUPPLIER_SCOPE,
            supplier_code,
            {
                "order_count": new_count,
                "last_unit_price": float(unit_price),
                "last_sku": sku,
                "avg_unit_price": round(new_avg, 4),
                "approved_count": stats["approved_count"] + (1 if approved else 0),
            },
        )

    # ---------- 渲染 ----------

    def render_prompt_block(self) -> str:
        prefs = self.preferences()
        lines = [
            f"已加载采购偏好：优先 {prefs.get('prefer_tier', 'A')} 类供应商；"
            f"单笔超过 ¥{float(prefs.get('approval_threshold', self.config.approval_threshold)):.0f} 需人工审批；"
            f"默认成本中心 {prefs.get('default_cost_center', 'CC-1001')}。"
        ]
        with self.engine.connect() as conn:
            from sqlalchemy import text

            rows = conn.execute(
                text("SELECT key, value FROM agent_memory WHERE scope = :scope LIMIT 3"),
                {"scope": SUPPLIER_SCOPE},
            ).all()
        for row in rows:
            stats = json.loads(row.value)
            avg = stats.get("avg_unit_price")
            if avg is None:
                continue
            lines.append(
                f"历史参考：{row.key} 历史均价 ¥{float(avg):.2f}，累计成交 "
                f"{int(stats.get('order_count', 0))} 次。"
            )
        return "\n".join(lines)
