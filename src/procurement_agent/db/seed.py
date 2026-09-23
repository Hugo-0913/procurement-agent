"""演示数据：医用耗材采购。

整个演示业务域的数据都集中在这里定义，换品类只需要改这一处。
数据规模刻意保持小（2 种物料、4 家供应商），但每一家、每一个价格都有演示用途。
"""

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

# ---------- 物料 ----------
# 单位保持"箱/盒"，符合医院实际按箱、按盒采购的习惯
MATERIALS: list[dict] = [
    {
        "sku": "ST-SYR-5ML",
        "name": "一次性无菌注射器",
        "spec": "5ml 带针，100 支/箱",
        "unit": "箱",
        "category": "注射穿刺类",
        "aliases": "注射器,无菌注射器,一次性注射器",
    },
    {
        "sku": "ST-MASK-50",
        "name": "医用外科口罩",
        "spec": "一次性，50 只/盒",
        "unit": "盒",
        "category": "防护类",
        "aliases": "口罩,外科口罩,医用口罩",
    },
]

# ---------- 供应商 ----------
SUPPLIERS: list[dict] = [
    {"code": "SUP-A", "name": "华康医疗器械", "tier": "A", "blacklisted": False, "delivery_rate": 0.98},
    {"code": "SUP-B", "name": "瑞康医械供应链", "tier": "B", "blacklisted": False, "delivery_rate": 0.91},
    {"code": "SUP-C", "name": "济生医疗科技", "tier": "A", "blacklisted": False, "delivery_rate": 0.96},
    {"code": "SUP-D", "name": "低价医械网", "tier": "C", "blacklisted": True, "delivery_rate": 0.72},
]

# 医疗器械经营许可证的有效期（天）。SUP-C 只剩 20 天，用于演示"资质临期需人工确认"。
# 营业执照统一给 3 年有效期，不参与异常演示。
LICENCE_EXPIRY_DAYS = {"SUP-A": 120, "SUP-B": 200, "SUP-C": 20, "SUP-D": 150}

# ---------- 报价 ----------
# 每种物料：[(供应商, 单价, 运费, 交期天数)]
# 设计意图：SUP-C 综合成本最低，但许可证临期会被排除，用来演示"不选最低价并说明理由"。
QUOTES: dict[str, list[tuple[str, float, float, int]]] = {
    "ST-SYR-5ML": [
        ("SUP-A", 68.0, 0.0, 3),
        ("SUP-B", 62.5, 120.0, 5),
        ("SUP-C", 64.0, 0.0, 2),
    ],
    "ST-MASK-50": [
        ("SUP-A", 18.6, 0.0, 3),
        ("SUP-B", 16.9, 120.0, 5),
        ("SUP-C", 19.4, 0.0, 2),
    ],
}

# 历史成交价按报价上下小幅浮动，用于计算价格偏差与历史参考
HISTORY_OFFSETS = (-0.3, 0.0, 0.2)

PURCHASE_HISTORY = [
    "采购 50 箱一次性无菌注射器，手术室日常补充",
    "补充 200 盒医用外科口罩，门诊部领用",
    "采购 30 箱一次性无菌注射器，成本中心 CC-2003",
    "护理部申请 150 盒医用外科口罩",
    "采购 20 箱一次性无菌注射器，预算 1500 元",
    "急诊科领用 300 盒医用外科口罩",
    "采购 40 箱一次性无菌注射器，优先 A 类供应商",
]


def seed_demo_data(engine: Engine) -> None:
    """写入演示数据；已有数据时只做必要的补齐（幂等）。"""
    today = date.today()
    with Session(engine) as session:
        if session.scalar(select(Material).limit(1)) is not None:
            _backfill_qualifications(session, today)
            return

        materials: dict[str, Material] = {}
        for spec in MATERIALS:
            material = Material(**spec)
            session.add(material)
            materials[spec["sku"]] = material
        session.flush()

        suppliers: dict[str, Supplier] = {}
        for spec in SUPPLIERS:
            supplier = Supplier(**spec)
            session.add(supplier)
            suppliers[spec["code"]] = supplier
        session.flush()

        for code, supplier in suppliers.items():
            licence_days = LICENCE_EXPIRY_DAYS[code]
            session.add(
                Qualification(
                    supplier_id=supplier.id,
                    qual_type="营业执照",
                    issued_at=today - timedelta(days=400),
                    expires_at=today + timedelta(days=1200),
                )
            )
            session.add(
                Qualification(
                    supplier_id=supplier.id,
                    qual_type="医疗器械经营许可证",
                    issued_at=today - timedelta(days=365 * 4),
                    expires_at=today + timedelta(days=licence_days),
                )
            )

        for sku, rows in QUOTES.items():
            material = materials[sku]
            for code, unit_price, freight, lead_days in rows:
                supplier = suppliers[code]
                session.add(
                    Quote(
                        supplier_id=supplier.id,
                        material_id=material.id,
                        unit_price=unit_price,
                        freight=freight,
                        lead_days=lead_days,
                        valid_until=today + timedelta(days=30),
                        available=True,
                    )
                )
                for index, offset in enumerate(HISTORY_OFFSETS):
                    session.add(
                        PriceHistory(
                            supplier_id=supplier.id,
                            material_id=material.id,
                            unit_price=round(unit_price + offset, 2),
                            ordered_at=today - timedelta(days=30 * (index + 1)),
                        )
                    )

        now = datetime.now().isoformat(timespec="seconds")
        for text in PURCHASE_HISTORY:
            session.add(
                PurchaseRequest(
                    request_text=text,
                    material_sku=None,
                    quantity=None,
                    cost_center=None,
                    created_at=now,
                )
            )
        session.commit()


def _backfill_qualifications(session: Session, today: date) -> None:
    """为既有演示库补上医疗器械经营许可证。

    早期版本的资质只有营业执照；医疗器械采购必须核验经营许可证，这里做一次幂等补齐，
    避免老库直接跑新规则时"所有供应商都没资质"。
    """
    existing = {
        (row.supplier_id, row.qual_type)
        for row in session.scalars(select(Qualification))
    }
    for supplier in session.scalars(select(Supplier)):
        if (supplier.id, "医疗器械经营许可证") in existing:
            continue
        days = LICENCE_EXPIRY_DAYS.get(supplier.code, 120)
        session.add(
            Qualification(
                supplier_id=supplier.id,
                qual_type="医疗器械经营许可证",
                issued_at=today - timedelta(days=365 * 4),
                expires_at=today + timedelta(days=days),
            )
        )
    session.commit()

