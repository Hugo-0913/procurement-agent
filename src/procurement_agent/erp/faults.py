from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from procurement_agent.db.models import FaultFlag

SUPPLIER_B_EXPIRED = "supplier_b_expired"
SUPPLIER_C_NO_QUOTE = "supplier_c_no_quote"
SUPPLIER_E_NO_QUOTE = "supplier_e_no_quote"
ALL_QUOTES_OVER_BUDGET = "all_quotes_over_budget"

ALL_FLAGS = (
    SUPPLIER_B_EXPIRED,
    SUPPLIER_C_NO_QUOTE,
    SUPPLIER_E_NO_QUOTE,
    ALL_QUOTES_OVER_BUDGET,
)

FLAG_LABELS = {
    SUPPLIER_B_EXPIRED: "让瑞康医械供应链的经营许可证过期",
    SUPPLIER_C_NO_QUOTE: "让济生医疗科技停止报价",
    SUPPLIER_E_NO_QUOTE: "让安泰医疗物资停止报价",
    ALL_QUOTES_OVER_BUDGET: "让全部报价涨到三倍",
}


class FaultRegistry:
    """故障注入开关，写入 fault_flags 表，供演示时动态切换。"""

    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def set(self, flag: str, enabled: bool) -> None:
        now = datetime.now().isoformat(timespec="seconds")
        with Session(self.engine) as session:
            row = session.scalar(select(FaultFlag).where(FaultFlag.flag == flag))
            if row is None:
                session.add(FaultFlag(flag=flag, enabled=enabled, updated_at=now))
            else:
                row.enabled = enabled
                row.updated_at = now
            session.commit()

    def is_enabled(self, flag: str) -> bool:
        with Session(self.engine) as session:
            row = session.scalar(select(FaultFlag).where(FaultFlag.flag == flag))
            return bool(row.enabled) if row is not None else False

    def list_flags(self) -> dict[str, bool]:
        with Session(self.engine) as session:
            rows = session.scalars(select(FaultFlag)).all()
        result = {flag: False for flag in ALL_FLAGS}
        for row in rows:
            result[row.flag] = bool(row.enabled)
        return result
