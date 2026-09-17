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
    return ProcurementConfig(
        **{field: raw[field] for field in REQUIRED_FIELDS}, single_quote_policy=policy
    )
