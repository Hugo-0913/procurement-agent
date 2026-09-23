"""演示数据：医用耗材采购。

业务域数据全部集中在这里，换品类只需要改这一处。
数据规模刻意保持小（2 种物料、4 家供应商），但每一家、每一个价格都有演示用途：

| 供应商 | 设定 | 演示的规则 |
| --- | --- | --- |
| 华康医疗器械 | 资质齐全、A 类 | 正常路径 |
| 瑞康医械供应链 | 资质齐全、B 类、单价最低 | 正常中选 |
| 济生医疗科技 | 经营许可证临期；经营范围不含防护类；口罩批次接近效期 | 资质临期 / 经营范围不覆盖 / 效期不足 |
| 低价医械网 | 黑名单 | 硬性淘汰 |
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
MATERIALS: list[dict] = [
    {
        "sku": "ST-SYR-5ML",
        "name": "一次性无菌注射器",
        "spec": "5ml 带针，100 支/箱",
        "unit": "箱",
        "category": "注射穿刺器械",
        "aliases": "注射器,无菌注射器,一次性注射器",
        "shelf_life_days": 730,  # 有效期 2 年
    },
    {
        "sku": "ST-MASK-50",
        "name": "医用外科口罩",
        "spec": "一次性，50 只/盒",
        "unit": "盒",
        "category": "医用防护用品",
        "aliases": "口罩,外科口罩,医用口罩",
        "shelf_life_days": 1095,  # 有效期 3 年
    },
]

# ---------- 供应商 ----------
SUPPLIERS: list[dict] = [
    {"code": "SUP-A", "name": "华康医疗器械", "tier": "A", "blacklisted": False, "delivery_rate": 0.98},
    {"code": "SUP-B", "name": "瑞康医械供应链", "tier": "B", "blacklisted": False, "delivery_rate": 0.91},
    {"code": "SUP-C", "name": "济生医疗科技", "tier": "A", "blacklisted": False, "delivery_rate": 0.96},
    {"code": "SUP-D", "name": "低价医械网", "tier": "C", "blacklisted": True, "delivery_rate": 0.72},
]

# 医疗器械经营许可证的有效期（天）与经营范围
LICENCE_EXPIRY_DAYS = {"SUP-A": 120, "SUP-B": 200, "SUP-C": 20, "SUP-D": 150}
LICENCE_SCOPE = {
    "SUP-A": "注射穿刺器械、医用防护用品",
    "SUP-B": "注射穿刺器械、医用防护用品",
    # 济生只登记了注射穿刺类：采购口罩时经营范围不覆盖，会被淘汰
    "SUP-C": "注射穿刺器械",
    "SUP-D": "注射穿刺器械、医用防护用品",
}

# 产品注册证：某供应商的某个具体产品是否已注册、注册证到期日
REGISTRATION_DAYS = {
    ("SUP-A", "ST-SYR-5ML"): 400,
    ("SUP-A", "ST-MASK-50"): 700,
    ("SUP-B", "ST-SYR-5ML"): 300,
    ("SUP-B", "ST-MASK-50"): 500,
    ("SUP-C", "ST-SYR-5ML"): 250,
    ("SUP-C", "ST-MASK-50"): 180,
    ("SUP-D", "ST-SYR-5ML"): 200,
    ("SUP-D", "ST-MASK-50"): 200,
}

# ---------- 报价 ----------
# (供应商, 单价, 运费, 交期, 起订量, 该批货剩余效期天数)
# 设计意图：
# - 济生口罩单价最低，但经营范围不覆盖 + 批次接近效期 → 双重淘汰
# - 济生注射器报价也有竞争力，但经营许可证临期 → 不选最低价并说明理由
QUOTES: dict[str, list[tuple[str, float, float, int, int, int]]] = {
    "ST-SYR-5ML": [
        ("SUP-A", 68.0, 0.0, 3, 50, 650),
        ("SUP-B", 62.5, 120.0, 5, 500, 500),
        ("SUP-C", 64.0, 0.0, 2, 100, 400),
    ],
    "ST-MASK-50": [
        ("SUP-A", 18.6, 0.0, 3, 200, 900),
        ("SUP-B", 16.9, 120.0, 5, 2000, 800),
        ("SUP-C", 15.8, 0.0, 2, 100, 120),  # 剩余效期 120 天 < 1095×0.66，且经营范围不覆盖
    ],
}

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
            _backfill(session, today)
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
                    expires_at=today + timedelta(days=LICENCE_EXPIRY_DAYS[code]),
                    scope=LICENCE_SCOPE[code],
                )
            )

        for (code, sku), days in REGISTRATION_DAYS.items():
            session.add(
                Qualification(
                    supplier_id=suppliers[code].id,
                    material_id=materials[sku].id,
                    qual_type="医疗器械注册证",
                    issued_at=today - timedelta(days=200),
                    expires_at=today + timedelta(days=days),
                )
            )

        for sku, rows in QUOTES.items():
            material = materials[sku]
            for code, unit_price, freight, lead_days, moq, shelf_days in rows:
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
                        min_order_qty=moq,
                        remaining_shelf_life_days=shelf_days,
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


def _backfill(session: Session, today: date) -> None:
    """为既有演示库补上后加的资质与报价字段（幂等）。

    不做这一步，老库在新增规则下会出现"所有供应商都缺注册证"或"起订量全是 1"。
    """
    materials = {m.sku: m for m in session.scalars(select(Material))}
    suppliers = {s.code: s for s in session.scalars(select(Supplier))}
    existing = {
        (row.supplier_id, row.qual_type, row.material_id)
        for row in session.scalars(select(Qualification))
    }

    for code, supplier in suppliers.items():
        if (supplier.id, "医疗器械经营许可证", None) not in existing:
            session.add(
                Qualification(
                    supplier_id=supplier.id,
                    qual_type="医疗器械经营许可证",
                    issued_at=today - timedelta(days=365 * 4),
                    expires_at=today + timedelta(days=LICENCE_EXPIRY_DAYS.get(code, 120)),
                    scope=LICENCE_SCOPE.get(code),
                )
            )
    for (code, sku), days in REGISTRATION_DAYS.items():
        supplier = suppliers.get(code)
        material = materials.get(sku)
        if supplier is None or material is None:
            continue
        if (supplier.id, "医疗器械注册证", material.id) in existing:
            continue
        session.add(
            Qualification(
                supplier_id=supplier.id,
                material_id=material.id,
                qual_type="医疗器械注册证",
                issued_at=today - timedelta(days=200),
                expires_at=today + timedelta(days=days),
            )
        )

    for sku, rows in QUOTES.items():
        material = materials.get(sku)
        if material is None:
            continue
        for code, _price, _freight, _lead, moq, shelf_days in rows:
            supplier = suppliers.get(code)
            if supplier is None:
                continue
            quote = session.scalar(
                select(Quote).where(
                    Quote.supplier_id == supplier.id,
                    Quote.material_id == material.id,
                )
            )
            if quote is None:
                continue
            if quote.min_order_qty in (None, 1):
                quote.min_order_qty = moq
            if quote.remaining_shelf_life_days is None:
                quote.remaining_shelf_life_days = shelf_days

    for sku, spec in {m["sku"]: m for m in MATERIALS}.items():
        material = materials.get(sku)
        if material is None:
            continue
        # 类别必须与经营许可证的经营范围用同一套措辞，否则"经营范围覆盖"校验会全部失败
        material.category = spec["category"]
        material.aliases = material.aliases or spec["aliases"]
        if material.shelf_life_days is None:
            material.shelf_life_days = spec["shelf_life_days"]

    session.commit()
