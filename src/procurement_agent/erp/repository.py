from __future__ import annotations

from dataclasses import asdict, is_dataclass
from datetime import date, datetime, timedelta
from typing import Any, Mapping

from sqlalchemy import func, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from procurement_agent.db.models import (
    Material,
    Order,
    PriceHistory,
    Qualification,
    Quote,
    Supplier,
)
from procurement_agent.erp.faults import (
    ALL_QUOTES_OVER_BUDGET,
    SUPPLIER_B_EXPIRED,
    SUPPLIER_C_NO_QUOTE,
    FaultRegistry,
)

EXPIRED_SUPPLIER_CODES = {"SUP-B"}
NO_QUOTE_SUPPLIER_CODES = {"SUP-C"}


def _as_mapping(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    if is_dataclass(value):
        return asdict(value)
    raise TypeError(f"无法转换为字段映射: {type(value)!r}")


class ErpRepository:
    """mock ERP 仓储层。故障注入在此层生效，Agent 侧无感知。"""

    def __init__(self, engine: Engine, faults: FaultRegistry | None = None) -> None:
        self.engine = engine
        self.faults = faults

    def _flag(self, name: str) -> bool:
        return bool(self.faults and self.faults.is_enabled(name))

    def find_material_by_name(self, name: str) -> Material | None:
        with Session(self.engine) as session:
            return session.scalar(
                select(Material).where(Material.name.like(f"%{name}%")).limit(1)
            )

    def get_material(self, material_id: int) -> Material | None:
        with Session(self.engine) as session:
            return session.get(Material, material_id)

    def list_suppliers(self) -> list[Supplier]:
        with Session(self.engine) as session:
            return list(session.scalars(select(Supplier).order_by(Supplier.id)))

    def list_qualifications(self, supplier_id: int) -> list[Qualification]:
        with Session(self.engine) as session:
            rows = list(
                session.scalars(
                    select(Qualification).where(Qualification.supplier_id == supplier_id)
                )
            )
            if self._flag(SUPPLIER_B_EXPIRED):
                code = session.scalar(
                    select(Supplier.code).where(Supplier.id == supplier_id)
                )
                if code in EXPIRED_SUPPLIER_CODES:
                    expired = date.today() - timedelta(days=5)
                    for row in rows:
                        row.expires_at = expired
            session.expunge_all()
            return rows

    def list_quotes(self, material_id: int) -> list[Quote]:
        today = date.today()
        with Session(self.engine) as session:
            rows = list(
                session.scalars(
                    select(Quote)
                    .where(
                        Quote.material_id == material_id,
                        Quote.available.is_(True),
                        Quote.valid_until >= today,
                    )
                    .order_by(Quote.unit_price)
                )
            )
            if self._flag(SUPPLIER_C_NO_QUOTE):
                blocked = {
                    sid
                    for (sid,) in session.execute(
                        select(Supplier.id).where(Supplier.code.in_(NO_QUOTE_SUPPLIER_CODES))
                    )
                }
                rows = [row for row in rows if row.supplier_id not in blocked]
            if self._flag(ALL_QUOTES_OVER_BUDGET):
                for row in rows:
                    row.unit_price = round(row.unit_price * 3.0, 2)
            session.expunge_all()
            return rows

    def price_history(self, material_id: int, supplier_id: int | None = None) -> list[float]:
        with Session(self.engine) as session:
            stmt = select(PriceHistory.unit_price).where(
                PriceHistory.material_id == material_id
            )
            if supplier_id is not None:
                stmt = stmt.where(PriceHistory.supplier_id == supplier_id)
            return [float(value) for value in session.scalars(stmt)]

    def supplier(self, supplier_id: int) -> Supplier | None:
        with Session(self.engine) as session:
            return session.get(Supplier, supplier_id)

    def supplier_by_code(self, code: str) -> Supplier | None:
        with Session(self.engine) as session:
            return session.scalar(select(Supplier).where(Supplier.code == code))

    def create_order(self, draft: Any) -> int:
        payload = _as_mapping(draft)
        with Session(self.engine) as session:
            order = Order(
                task_id=str(payload["task_id"]),
                supplier_id=int(payload["supplier_id"]),
                material_id=int(payload["material_id"]),
                quantity=int(payload["quantity"]),
                unit_price=float(payload["unit_price"]),
                total_amount=float(payload["total_amount"]),
                lead_days=int(payload["lead_days"]),
                cost_center=payload.get("cost_center"),
                status=str(payload.get("status", "CREATED")),
                created_at=datetime.now().isoformat(timespec="seconds"),
            )
            session.add(order)
            session.commit()
            return int(order.id)

    def get_order(self, order_id: int) -> Order:
        with Session(self.engine) as session:
            order = session.get(Order, order_id)
            if order is None:
                raise KeyError(f"订单不存在: {order_id}")
            session.expunge(order)
            return order

    def list_orders(self) -> list[Order]:
        with Session(self.engine) as session:
            return list(session.scalars(select(Order).order_by(Order.id.desc())))

    def count_orders(self) -> int:
        with Session(self.engine) as session:
            return int(session.scalar(select(func.count()).select_from(Order)) or 0)

    def record_price(self, supplier_id: int, material_id: int, unit_price: float) -> None:
        with Session(self.engine) as session:
            session.add(
                PriceHistory(
                    supplier_id=supplier_id,
                    material_id=material_id,
                    unit_price=unit_price,
                    ordered_at=date.today(),
                )
            )
            session.commit()

