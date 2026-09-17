from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

DEFAULT_CONFIG_PATH = Path("config/procurement.yaml")

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


def load_procurement_config(path: Path | None = None) -> ProcurementConfig:
    target = Path(path) if path is not None else DEFAULT_CONFIG_PATH
    raw = yaml.safe_load(target.read_text(encoding="utf-8")) or {}
    missing = [field for field in REQUIRED_FIELDS if field not in raw]
    if missing:
        raise ValueError(f"缺少必需配置项: {', '.join(missing)}")
    return ProcurementConfig(**{field: raw[field] for field in REQUIRED_FIELDS})

