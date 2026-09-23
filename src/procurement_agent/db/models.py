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
    aliases: Mapped[str | None] = mapped_column(Text)
    # 效期管理：耗材有保质期，到货时剩余效期不得低于总效期的这个比例
    shelf_life_days: Mapped[int | None] = mapped_column(Integer)
    min_remaining_ratio: Mapped[float] = mapped_column(Float, default=0.66)


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
    # material_id 为空表示通用资质（营业执照、经营许可证）；不为空表示该物料的产品注册证
    material_id: Mapped[int | None] = mapped_column(ForeignKey("materials.id"))
    # 经营许可证的经营范围，用于校验所采购的物料类别是否被覆盖
    scope: Mapped[str | None] = mapped_column(Text)


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
    min_order_qty: Mapped[int] = mapped_column(Integer, default=1)
    remaining_shelf_life_days: Mapped[int | None] = mapped_column(Integer)


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
        _migrate(connection)
        connection.commit()
    finally:
        connection.close()
    return create_engine(f"sqlite+pysqlite:///{target.as_posix()}", future=True)


def _migrate(connection: sqlite3.Connection) -> None:
    """轻量增量迁移：为既有数据库补上后来新增的列。

    演示项目用最小实现，避免引入 Alembic；生产环境应换成正式迁移工具。
    """
    migrations = {
        "materials": [
            ("aliases", "TEXT"),
            ("shelf_life_days", "INTEGER"),
            ("min_remaining_ratio", "REAL NOT NULL DEFAULT 0.66"),
        ],
        "supplier_qualifications": [
            ("material_id", "INTEGER"),
            ("scope", "TEXT"),
        ],
        "quotes": [
            ("min_order_qty", "INTEGER NOT NULL DEFAULT 1"),
            ("remaining_shelf_life_days", "INTEGER"),
        ],
    }
    for table, columns in migrations.items():
        existing = {
            row[1]
            for row in connection.execute(f"PRAGMA table_info({table})").fetchall()
        }
        for name, ddl in columns:
            if name not in existing:
                connection.execute(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}")


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
