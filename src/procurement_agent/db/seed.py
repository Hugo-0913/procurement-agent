from __future__ import annotations

from datetime import date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from procurement_agent.db.models import (
    Material,
    PriceHistory,
    PurchaseRequest,
    Qualification,
    Quote,
    Supplier,
)


def _add_purchase_requests(session: Session) -> None:
    rows = [
        ("采购 20 箱 A4 纸，成本中心 CC-1001", "ST-A4-500", 20, "CC-1001"),
        ("补充 50 箱 A4 纸，下周一前到货", "ST-A4-500", 50, "CC-1001"),
        ("采购 10 箱 A4 纸用于培训中心", "ST-A4-500", 10, "CC-2003"),
        ("行政部申请 30 箱 A4 纸", "ST-A4-500", 30, "CC-1001"),
        ("采购 15 箱 A4 纸，预算 400 元", "ST-A4-500", 15, "CC-1002"),
        ("研发中心领用 40 箱 A4 纸", "ST-A4-500", 40, "CC-3007"),
        ("采购 25 箱 A4 纸，优先 A 类供应商", "ST-A4-500", 25, "CC-1001"),
    ]
    now = datetime.now().isoformat(timespec="seconds")
    for text, sku, qty, cc in rows:
        session.add(
            PurchaseRequest(
                request_text=text,
                material_sku=sku,
                quantity=qty,
                cost_center=cc,
                created_at=now,
            )
        )


def seed_demo_data(engine: Engine) -> None:
    """写入演示数据；已有数据时直接返回（幂等）。"""
    today = date.today()
    with Session(engine) as session:
        if session.scalar(select(Material).limit(1)) is not None:
            _backfill_demo_aliases(session)
            return

        material = Material(
            sku="ST-A4-500",
            name="A4 纸",
            spec="70g/500张",
            unit="箱",
            category="办公耗材",
            aliases="A4纸,办公用纸,复印纸,打印纸",
        )
        session.add(material)
        session.flush()

        suppliers = [
            Supplier(code="SUP-A", name="晨光办公用品", tier="A", blacklisted=False, delivery_rate=0.98),
            Supplier(code="SUP-B", name="恒信纸业", tier="B", blacklisted=False, delivery_rate=0.91),
            Supplier(code="SUP-C", name="金辉文具", tier="A", blacklisted=False, delivery_rate=0.96),
            Supplier(code="SUP-D", name="廉价办公仓", tier="C", blacklisted=True, delivery_rate=0.72),
        ]
        session.add_all(suppliers)
        session.flush()
        by_code = {s.code: s for s in suppliers}

        # 资质：SUP-C 20 天后过期（临期），SUP-A/B/D 均在有效期外 90 天以上
        expiries = {
            "SUP-A": today + timedelta(days=120),
            "SUP-B": today + timedelta(days=200),
            "SUP-C": today + timedelta(days=20),
            "SUP-D": today + timedelta(days=150),
        }
        for code, expires in expiries.items():
            session.add(
                Qualification(
                    supplier_id=by_code[code].id,
                    qual_type="营业执照",
                    issued_at=expires - timedelta(days=365 * 3),
                    expires_at=expires,
                )
            )

        quote_rows = [
            ("SUP-A", 21.5, 0.0, 3),
            ("SUP-B", 19.8, 120.0, 5),
            ("SUP-C", 20.2, 0.0, 2),
        ]
        for code, unit_price, freight, lead_days in quote_rows:
            session.add(
                Quote(
                    supplier_id=by_code[code].id,
                    material_id=material.id,
                    unit_price=unit_price,
                    freight=freight,
                    lead_days=lead_days,
                    valid_until=today + timedelta(days=30),
                    available=True,
                )
            )

        history_rows = {
            "SUP-A": (21.2, 21.8, 21.5),
            "SUP-B": (19.5, 20.0, 19.9),
            "SUP-C": (20.0, 20.3, 20.2),
        }
        for code, prices in history_rows.items():
            for index, price in enumerate(prices):
                session.add(
                    PriceHistory(
                        supplier_id=by_code[code].id,
                        material_id=material.id,
                        unit_price=price,
                        ordered_at=today - timedelta(days=30 * (index + 1)),
                    )
                )

        _add_purchase_requests(session)
        session.commit()


def _backfill_demo_aliases(session: Session) -> None:
    """为既有演示数据补齐别名。

    别名是后加的字段，早期建的库不会重跑种子逻辑，这里做一次幂等回填，
    避免出现"用户说办公用纸、系统说不认识"的情况。
    """
    material = session.scalar(select(Material).where(Material.sku == "ST-A4-500"))
    if material is not None and not material.aliases:
        material.aliases = "A4纸,办公用纸,复印纸,打印纸"
        session.commit()
