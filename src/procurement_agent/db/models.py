from __future__ import annotations

import sqlite3
from datetime import date
from pathlib import Path

from sqlalchemy import (
    Boolean,
    Date,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    create_engine,
)
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

SCHEMA_PATH = Path(__file__).with_name("schema.sql")


class Base(DeclarativeBase):
    pass


class Material(Base):
    __tablename__ = "materials"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    sku: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    spec: Mapped[str | None] = mapped_column(String(128))
    unit: Mapped[str] = mapped_column(String(16), default="件")
    category: Mapped[str | None] = mapped_column(String(64))


class Supplier(Base):
    __tablename__ = "suppliers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    tier: Mapped[str] = mapped_column(String(4), default="B")
    blacklisted: Mapped[bool] = mapped_column(Boolean, default=False)
    delivery_rate: Mapped[float] = mapped_column(Float, default=0.95)


class Qualification(Base):
    __tablename__ = "supplier_qualifications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    supplier_id: Mapped[int] = mapped_column(ForeignKey("suppliers.id"), nullable=False)
    qual_type: Mapped[str] = mapped_column(String(64), nullable=False)
    issued_at: Mapped[date] = mapped_column(Date, nullable=False)
    expires_at: Mapped[date] = mapped_column(Date, nullable=False)


class Quote(Base):
    __tablename__ = "quotes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    supplier_id: Mapped[int] = mapped_column(ForeignKey("suppliers.id"), nullable=False)
    material_id: Mapped[int] = mapped_column(ForeignKey("materials.id"), nullable=False)
    unit_price: Mapped[float] = mapped_column(Float, nullable=False)
    freight: Mapped[float] = mapped_column(Float, default=0.0)
    lead_days: Mapped[int] = mapped_column(Integer, nullable=False)
    valid_until: Mapped[date] = mapped_column(Date, nullable=False)
    available: Mapped[bool] = mapped_column(Boolean, default=True)


class PriceHistory(Base):
    __tablename__ = "price_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    supplier_id: Mapped[int] = mapped_column(ForeignKey("suppliers.id"), nullable=False)
    material_id: Mapped[int] = mapped_column(ForeignKey("materials.id"), nullable=False)
    unit_price: Mapped[float] = mapped_column(Float, nullable=False)
    ordered_at: Mapped[date] = mapped_column(Date, nullable=False)


class Order(Base):
    __tablename__ = "orders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    task_id: Mapped[str] = mapped_column(Text, nullable=False)
    supplier_id: Mapped[int] = mapped_column(ForeignKey("suppliers.id"), nullable=False)
    material_id: Mapped[int] = mapped_column(ForeignKey("materials.id"), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    unit_price: Mapped[float] = mapped_column(Float, nullable=False)
    total_amount: Mapped[float] = mapped_column(Float, nullable=False)
    lead_days: Mapped[int] = mapped_column(Integer, nullable=False)
    cost_center: Mapped[str | None] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(16), default="CREATED")
    created_at: Mapped[str] = mapped_column(Text, nullable=False)


class FaultFlag(Base):
    __tablename__ = "fault_flags"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    flag: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    updated_at: Mapped[str] = mapped_column(Text, nullable=False)


class PurchaseRequest(Base):
    __tablename__ = "purchase_requests"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    request_text: Mapped[str] = mapped_column(Text, nullable=False)
    material_sku: Mapped[str | None] = mapped_column(String(64))
    quantity: Mapped[int | None] = mapped_column(Integer)
    cost_center: Mapped[str | None] = mapped_column(String(32))
    created_at: Mapped[str] = mapped_column(Text, nullable=False)


def init_db(db_path: Path) -> Engine:
    """建库建表并返回 SQLAlchemy Engine。"""
    target = Path(db_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(target)
    try:
        connection.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
        connection.commit()
    finally:
        connection.close()
    return create_engine(f"sqlite+pysqlite:///{target.as_posix()}", future=True)


from procurement_agent.db.seed import seed_demo_data  # noqa: E402

__all__ = [
    "Base",
    "FaultFlag",
    "Material",
    "Order",
    "PriceHistory",
    "PurchaseRequest",
    "Qualification",
    "Quote",
    "Supplier",
    "init_db",
    "seed_demo_data",
]
