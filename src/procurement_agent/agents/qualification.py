from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from procurement_agent.config import ProcurementConfig
from procurement_agent.erp.repository import ErpRepository
from procurement_agent.skills_loader import SkillRegistry


@dataclass(frozen=True)
class QualifiedSupplier:
    supplier_id: int
    code: str
    name: str
    tier: str
    expiring_soon: bool


@dataclass(frozen=True)
class RejectedSupplier:
    supplier_id: int
    code: str
    name: str
    reason: str


@dataclass
class QualificationOutcome:
    qualified: list[QualifiedSupplier] = field(default_factory=list)
    rejected: list[RejectedSupplier] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def run_qualification(
    repo: ErpRepository,
    config: ProcurementConfig,
    material_id: int,
    *,
    skills: SkillRegistry | None = None,
) -> QualificationOutcome:
    """医疗器械供应商资质核验。

    判定顺序：黑名单 → 资质缺失 → 经营范围不覆盖 → 缺产品注册证 → 资质过期 → 临期标记。
    顺序固定、先命中先生效，避免同一供应商出现多条矛盾原因。
    """
    if skills is not None:
        skills.load("supplier_qualification")

    today = date.today()
    outcome = QualificationOutcome()
    material = repo.get_material(material_id)
    category = (material.category or "") if material else ""

    for supplier in repo.list_suppliers():
        if supplier.blacklisted:
            outcome.rejected.append(
                RejectedSupplier(
                    supplier_id=supplier.id,
                    code=supplier.code,
                    name=supplier.name,
                    reason="命中黑名单，禁止参与采购",
                )
            )
            continue

        qualifications = repo.list_qualifications(supplier.id)
        licences = [q for q in qualifications if q.qual_type == "医疗器械经营许可证"]
        if not licences:
            outcome.rejected.append(
                RejectedSupplier(
                    supplier_id=supplier.id,
                    code=supplier.code,
                    name=supplier.name,
                    reason="资质缺失：未登记医疗器械经营许可证",
                )
            )
            continue

        # 经营范围必须覆盖所采购的器械类别，否则属于超范围经营
        licence = licences[0]
        scope = licence.scope or ""
        if category and scope and category not in scope:
            outcome.rejected.append(
                RejectedSupplier(
                    supplier_id=supplier.id,
                    code=supplier.code,
                    name=supplier.name,
                    reason=f"经营范围不覆盖「{category}」（许可证范围：{scope}）",
                )
            )
            continue

        # 具体产品必须有有效的医疗器械注册证
        registrations = [
            q
            for q in qualifications
            if q.qual_type == "医疗器械注册证" and q.material_id == material_id
        ]
        if not registrations:
            outcome.rejected.append(
                RejectedSupplier(
                    supplier_id=supplier.id,
                    code=supplier.code,
                    name=supplier.name,
                    reason=f"缺少「{material.name if material else material_id}」的医疗器械注册证",
                )
            )
            continue

        relevant = [*licences, *registrations]
        expired = [q for q in relevant if q.expires_at < today]
        if expired:
            earliest = min(q.expires_at for q in expired)
            what = next(q.qual_type for q in expired if q.expires_at == earliest)
            outcome.rejected.append(
                RejectedSupplier(
                    supplier_id=supplier.id,
                    code=supplier.code,
                    name=supplier.name,
                    reason=f"资质过期：{what} 于 {earliest.isoformat()} 已失效",
                )
            )
            continue

        nearest_expiry = min(q.expires_at for q in relevant)
        expiring_soon = (nearest_expiry - today).days < config.freshness_warn_days
        if expiring_soon:
            what = next(
                q.qual_type for q in relevant if q.expires_at == nearest_expiry
            )
            outcome.notes.append(
                f"{supplier.name} 的{what}将于 {nearest_expiry.isoformat()} 到期（临期），"
                "不淘汰但需在比价结论中披露"
            )
        outcome.qualified.append(
            QualifiedSupplier(
                supplier_id=supplier.id,
                code=supplier.code,
                name=supplier.name,
                tier=supplier.tier,
                expiring_soon=expiring_soon,
            )
        )

    return outcome
