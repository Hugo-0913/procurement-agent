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
    """确定性资质核验：黑名单 → 资质缺失 → 资质过期 → 临期标记。"""
    del material_id  # 保留参数以匹配阶段处理器签名
    if skills is not None:
        skills.load("supplier_qualification")

    today = date.today()
    outcome = QualificationOutcome()

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
        if not qualifications:
            outcome.rejected.append(
                RejectedSupplier(
                    supplier_id=supplier.id,
                    code=supplier.code,
                    name=supplier.name,
                    reason="资质缺失：未登记营业执照",
                )
            )
            continue

        expired = [q for q in qualifications if q.expires_at < today]
        if expired:
            earliest = min(q.expires_at for q in expired)
            outcome.rejected.append(
                RejectedSupplier(
                    supplier_id=supplier.id,
                    code=supplier.code,
                    name=supplier.name,
                    reason=f"资质过期：{earliest.isoformat()} 已失效",
                )
            )
            continue

        nearest_expiry = min(q.expires_at for q in qualifications)
        expiring_soon = (nearest_expiry - today).days < config.freshness_warn_days
        if expiring_soon:
            outcome.notes.append(
                f"{supplier.name} 资质临期（{nearest_expiry.isoformat()} 到期），"
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

