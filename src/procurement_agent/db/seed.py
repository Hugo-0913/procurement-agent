"""演示数据：医用耗材采购。

业务域数据全部集中在这里，换品类只需要改这一处。
数据规模刻意保持小（5 种物料 × 4 家可用供应商 + 1 家黑名单），但每一家、每一个价格都有演示用途：

| 供应商 | 设定 | 演示的规则 |
| --- | --- | --- |
| 华康医疗器械 | 资质齐全、A 类 | 正常路径；起订量低，小批量中选 |
| 瑞康医械供应链 | 资质齐全、B 类、单价最低 | 大批量中选；起订量高，小批量出局 |
| 济生医疗科技 | 经营许可证临期；经营范围不含医用敷料；部分批次接近效期 | 资质临期 / 经营范围不覆盖 / 效期不足 |
| 安泰医疗物资 | 资质齐全、A 类、起订量低 | 口罩与纱布中选 |
| 低价医械网 | 黑名单（但有报价） | 硬性淘汰：报价最低也不可用 |

中选者刻意分散到三家：注射器看数量（小批量华康、大批量瑞康）、输液器华康（成本接近时优先 A 类）、
口罩与纱布安泰、手套瑞康。这样"我的订单"里不会全是同一家。
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
        "sku": "ST-INF-SET",
        "name": "一次性使用输液器",
        "spec": "带针，20 套/箱",
        "unit": "箱",
        "category": "注射穿刺器械",
        "aliases": "输液器,一次性输液器,静脉输液器",
        "shelf_life_days": 730,
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
    {
        "sku": "ST-GLOVE-N",
        "name": "医用丁腈检查手套",
        "spec": "无粉，100 只/盒",
        "unit": "盒",
        "category": "医用防护用品",
        "aliases": "手套,丁腈手套,检查手套",
        "shelf_life_days": 1095,
    },
    {
        "sku": "ST-GAUZE-10",
        "name": "无菌纱布块",
        "spec": "8cm×10cm，100 片/包",
        "unit": "包",
        "category": "医用敷料",
        "aliases": "纱布,纱布块,无菌纱布",
        "shelf_life_days": 1095,
    },
]

# ---------- 供应商 ----------
SUPPLIERS: list[dict] = [
    {"code": "SUP-A", "name": "华康医疗器械", "tier": "A", "blacklisted": False, "delivery_rate": 0.98},
    {"code": "SUP-B", "name": "瑞康医械供应链", "tier": "B", "blacklisted": False, "delivery_rate": 0.91},
    {"code": "SUP-C", "name": "济生医疗科技", "tier": "A", "blacklisted": False, "delivery_rate": 0.96},
    {"code": "SUP-D", "name": "低价医械网", "tier": "C", "blacklisted": True, "delivery_rate": 0.72},
    {"code": "SUP-E", "name": "安泰医疗物资", "tier": "A", "blacklisted": False, "delivery_rate": 0.94},
]

# 医疗器械经营许可证的有效期（天）与经营范围
# 济生（SUP-C）只有 20 天，用于演示"临期：不淘汰但改选并说明理由"
LICENCE_EXPIRY_DAYS = {"SUP-A": 120, "SUP-B": 200, "SUP-C": 20, "SUP-D": 150, "SUP-E": 300}
LICENCE_SCOPE = {
    "SUP-A": "注射穿刺器械、医用防护用品、医用敷料",
    "SUP-B": "注射穿刺器械、医用防护用品、医用敷料",
    # 济生没登记医用敷料：采购纱布块时经营范围不覆盖，会被淘汰
    "SUP-C": "注射穿刺器械、医用防护用品",
    "SUP-D": "注射穿刺器械、医用防护用品、医用敷料",
    "SUP-E": "注射穿刺器械、医用防护用品、医用敷料",
}

# 产品注册证：某供应商的某个具体产品是否已注册、注册证到期日
REGISTRATION_DAYS = {
    ("SUP-A", "ST-SYR-5ML"): 400,
    ("SUP-A", "ST-INF-SET"): 380,
    ("SUP-A", "ST-MASK-50"): 700,
    ("SUP-A", "ST-GLOVE-N"): 650,
    ("SUP-A", "ST-GAUZE-10"): 500,
    ("SUP-B", "ST-SYR-5ML"): 300,
    ("SUP-B", "ST-INF-SET"): 320,
    ("SUP-B", "ST-MASK-50"): 500,
    ("SUP-B", "ST-GLOVE-N"): 450,
    ("SUP-B", "ST-GAUZE-10"): 400,
    ("SUP-C", "ST-SYR-5ML"): 250,
    ("SUP-C", "ST-INF-SET"): 240,
    ("SUP-C", "ST-MASK-50"): 180,
    ("SUP-C", "ST-GLOVE-N"): 300,
    ("SUP-C", "ST-GAUZE-10"): 260,
    ("SUP-D", "ST-SYR-5ML"): 200,
    ("SUP-D", "ST-INF-SET"): 200,
    ("SUP-D", "ST-MASK-50"): 200,
    ("SUP-D", "ST-GLOVE-N"): 200,
    ("SUP-D", "ST-GAUZE-10"): 200,
    ("SUP-E", "ST-SYR-5ML"): 600,
    ("SUP-E", "ST-INF-SET"): 580,
    ("SUP-E", "ST-MASK-50"): 720,
    ("SUP-E", "ST-GLOVE-N"): 700,
    ("SUP-E", "ST-GAUZE-10"): 660,
}

# ---------- 报价 ----------
# (供应商, 单价, 运费, 交期, 起订量, 该批货剩余效期天数)
# 设计意图：
# - 济生（SUP-C）报价普遍有竞争力，但经营许可证临期 → 不选最低价并说明理由；
#   纱布缺乏经营资质覆盖，直接淘汰（即使它报价最低）
# - 低价医械网（SUP-D）在黑名单，报价最低也不可用 → 演示"先淘汰再看价格"
# - 安泰（SUP-E）起订量低、价格居中：口罩、纱布中选
QUOTES: dict[str, list[tuple[str, float, float, int, int, int]]] = {
    "ST-SYR-5ML": [
        ("SUP-A", 68.0, 0.0, 3, 50, 650),
        ("SUP-B", 62.5, 120.0, 5, 500, 500),
        ("SUP-C", 64.0, 0.0, 2, 100, 400),
        ("SUP-E", 70.0, 0.0, 4, 20, 600),
        ("SUP-D", 58.0, 0.0, 7, 10, 600),
    ],
    "ST-INF-SET": [
        ("SUP-A", 86.0, 0.0, 3, 50, 700),
        ("SUP-B", 84.0, 60.0, 6, 50, 650),
        ("SUP-C", 88.0, 0.0, 2, 100, 600),
        ("SUP-E", 92.0, 0.0, 4, 30, 700),
        ("SUP-D", 80.0, 0.0, 7, 20, 650),
    ],
    "ST-MASK-50": [
        ("SUP-A", 18.6, 0.0, 3, 200, 900),
        ("SUP-B", 16.9, 120.0, 5, 2000, 800),
        # 剩余效期 120 天 < 1095×0.66 → 效期不足被淘汰；报价刻意不做到「明显最低」，
        # 否则安泰中选时会连带触发"差额超 10%"审批，把效期规则和差额规则混在一起
        ("SUP-C", 16.2, 0.0, 2, 100, 120),
        ("SUP-E", 17.4, 0.0, 4, 50, 900),
        ("SUP-D", 14.5, 0.0, 7, 10, 800),
    ],
    "ST-GLOVE-N": [
        ("SUP-A", 43.0, 0.0, 3, 100, 800),
        ("SUP-B", 39.5, 120.0, 5, 100, 800),
        ("SUP-C", 41.0, 0.0, 2, 100, 800),
        ("SUP-E", 42.0, 0.0, 4, 100, 800),
        ("SUP-D", 37.0, 0.0, 7, 50, 800),
    ],
    "ST-GAUZE-10": [
        ("SUP-A", 24.0, 0.0, 3, 100, 900),
        ("SUP-B", 21.5, 80.0, 5, 100, 900),
        # 济生报价最低，但经营范围不含医用敷料 → 淘汰（不是"价高"，是"不能卖"）
        ("SUP-C", 20.5, 0.0, 2, 100, 900),
        ("SUP-E", 21.8, 0.0, 4, 50, 900),
        ("SUP-D", 19.0, 0.0, 7, 50, 900),
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
    "供应室申请 120 箱一次性使用输液器，成本中心 CC-1004",
    "体检中心领用 200 盒医用丁腈检查手套",
    "外科换药室申请 300 包无菌纱布块，成本中心 CC-2002",
    "采购 150 盒医用丁腈检查手套，门诊换药使用",
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
    扩充物料与供应商时同样走这里：老库不重建也能获得新数据，避免丢掉已经跑出来的任务与订单。
    """
    materials = {m.sku: m for m in session.scalars(select(Material))}
    suppliers = {s.code: s for s in session.scalars(select(Supplier))}

    # 1) 先补齐缺失的物料与供应商，后面的资质、报价才有挂靠对象
    for spec in MATERIALS:
        if spec["sku"] not in materials:
            material = Material(**spec)
            session.add(material)
            materials[spec["sku"]] = material
    for spec in SUPPLIERS:
        if spec["code"] not in suppliers:
            supplier = Supplier(**spec)
            session.add(supplier)
            suppliers[spec["code"]] = supplier
    session.flush()

    existing = {
        (row.supplier_id, row.qual_type, row.material_id): row
        for row in session.scalars(select(Qualification))
    }

    for code, supplier in suppliers.items():
        if (supplier.id, "营业执照", None) not in existing:
            session.add(
                Qualification(
                    supplier_id=supplier.id,
                    qual_type="营业执照",
                    issued_at=today - timedelta(days=400),
                    expires_at=today + timedelta(days=1200),
                )
            )
        licence = existing.get((supplier.id, "医疗器械经营许可证", None))
        if licence is None:
            session.add(
                Qualification(
                    supplier_id=supplier.id,
                    qual_type="医疗器械经营许可证",
                    issued_at=today - timedelta(days=365 * 4),
                    expires_at=today + timedelta(days=LICENCE_EXPIRY_DAYS.get(code, 120)),
                    scope=LICENCE_SCOPE.get(code),
                )
            )
        else:
            # 经营范围与有效期以 seed.py 为准同步：只补"缺失的行"是不够的——
            # 改过经营范围的供应商在老库里会留着旧措辞，新物料类别会被判成"超范围经营"，
            # 表现为"新建库正常、老库少一家可用供应商"。
            licence.scope = LICENCE_SCOPE.get(code, licence.scope)
            licence.expires_at = today + timedelta(days=LICENCE_EXPIRY_DAYS.get(code, 120))
    for (code, sku), days in REGISTRATION_DAYS.items():
        supplier = suppliers.get(code)
        material = materials.get(sku)
        if supplier is None or material is None:
            continue
        registration = existing.get((supplier.id, "医疗器械注册证", material.id))
        if registration is not None:
            registration.expires_at = today + timedelta(days=days)
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
        for code, price, freight, lead, moq, shelf_days in rows:
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
                # 新物料/新供应商的报价：整条补上，含历史成交价
                session.add(
                    Quote(
                        supplier_id=supplier.id,
                        material_id=material.id,
                        unit_price=price,
                        freight=freight,
                        lead_days=lead,
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
                            unit_price=round(price + offset, 2),
                            ordered_at=today - timedelta(days=30 * (index + 1)),
                        )
                    )
                continue
            if quote.min_order_qty in (None, 1):
                quote.min_order_qty = moq
            if quote.remaining_shelf_life_days is None:
                quote.remaining_shelf_life_days = shelf_days
            # 报价以 seed.py 为准：改这里的数字后重启即生效，不必重建演示库。
            # （故障注入只改内存对象、不落库，所以不会被这一步覆盖掉。）
            quote.unit_price = price
            quote.freight = freight
            quote.lead_days = lead
            quote.min_order_qty = moq
            quote.remaining_shelf_life_days = shelf_days
            quote.valid_until = today + timedelta(days=30)
            quote.available = True

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
