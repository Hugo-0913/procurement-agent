from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

DEFAULT_CONFIG_PATH = Path("config/procurement.yaml")
DEFAULT_ENV_PATH = Path(".env")

REQUIRED_FIELDS = (
    "approval_threshold",
    "retry_max_attempts",
    "context_token_threshold",
    "min_quote_count",
    "freshness_warn_days",
)


@dataclass(frozen=True)
class ProcurementConfig:
    approval_threshold: float
    retry_max_attempts: int
    context_token_threshold: int
    min_quote_count: int
    freshness_warn_days: int
    # 可用报价不足 min_quote_count 时的处置策略：
    #   approval —— 以唯一报价继续，但必须转人工审批（默认，业务更合理）
    #   fail     —— 直接判定任务失败
    single_quote_policy: str = "approval"
    # 采购偏好：综合成本接近时优先的供应商等级与"接近"的容忍区间。
    # 偏好只在成本差异不超过容忍比例时生效，避免偏好压过价格。
    prefer_tier: str = "A"
    tier_preference_tolerance: float = 0.02


def load_env(path: Path | None = None) -> bool:
    """加载 .env 中的环境变量（已存在的变量不覆盖）。返回是否找到文件。"""
    from dotenv import load_dotenv

    target = Path(path) if path is not None else DEFAULT_ENV_PATH
    if not target.exists():
        return False
    load_dotenv(dotenv_path=target, override=False)
    return True


def load_procurement_config(path: Path | None = None) -> ProcurementConfig:
    target = Path(path) if path is not None else DEFAULT_CONFIG_PATH
    raw = yaml.safe_load(target.read_text(encoding="utf-8")) or {}
    missing = [field for field in REQUIRED_FIELDS if field not in raw]
    if missing:
        raise ValueError(f"缺少必需配置项: {', '.join(missing)}")
    policy = str(raw.get("single_quote_policy", "approval"))
    if policy not in {"approval", "fail"}:
        raise ValueError("single_quote_policy 只能是 approval 或 fail")
    prefer_tier = str(raw.get("prefer_tier", "A")).upper()
    if prefer_tier not in {"A", "B", "C"}:
        raise ValueError("prefer_tier 只能是 A / B / C")
    tolerance = float(raw.get("tier_preference_tolerance", 0.02))
    if tolerance < 0:
        raise ValueError("tier_preference_tolerance 不能为负数")
    return ProcurementConfig(
        **{field: raw[field] for field in REQUIRED_FIELDS},
        single_quote_policy=policy,
        prefer_tier=prefer_tier,
        tier_preference_tolerance=tolerance,
    )
