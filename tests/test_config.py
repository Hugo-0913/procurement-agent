from pathlib import Path

import pytest

from procurement_agent.config import load_procurement_config


def test_load_config(tmp_path: Path):
    cfg_file = tmp_path / "procurement.yaml"
    cfg_file.write_text(
        "approval_threshold: 50000\n"
        "retry_max_attempts: 3\n"
        "context_token_threshold: 12000\n"
        "min_quote_count: 2\n"
        "freshness_warn_days: 30\n",
        encoding="utf-8",
    )
    cfg = load_procurement_config(cfg_file)
    assert cfg.approval_threshold == 50000
    assert cfg.retry_max_attempts == 3
    assert cfg.freshness_warn_days == 30


def test_missing_field_raises(tmp_path: Path):
    cfg_file = tmp_path / "procurement.yaml"
    cfg_file.write_text("approval_threshold: 50000\n", encoding="utf-8")
    with pytest.raises(ValueError):
        load_procurement_config(cfg_file)


def test_default_config_file_loads():
    cfg = load_procurement_config()
    assert cfg.approval_threshold == 50000
    assert cfg.min_quote_count == 2
    assert cfg.single_quote_policy == "approval"
    # 采购偏好：优先 A 类供应商，只在成本差异不超过 2% 时生效
    assert cfg.prefer_tier == "A"
    assert cfg.tier_preference_tolerance == pytest.approx(0.02)


def test_invalid_prefer_tier_rejected(tmp_path: Path):
    cfg_file = tmp_path / "procurement.yaml"
    cfg_file.write_text(
        "approval_threshold: 1\n"
        "retry_max_attempts: 1\n"
        "context_token_threshold: 1\n"
        "min_quote_count: 1\n"
        "freshness_warn_days: 1\n"
        "prefer_tier: 甲\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="prefer_tier"):
        load_procurement_config(cfg_file)


def test_invalid_single_quote_policy_rejected(tmp_path: Path):
    cfg_file = tmp_path / "procurement.yaml"
    cfg_file.write_text(
        "approval_threshold: 1\n"
        "retry_max_attempts: 1\n"
        "context_token_threshold: 1\n"
        "min_quote_count: 1\n"
        "freshness_warn_days: 1\n"
        "single_quote_policy: whatever\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="single_quote_policy"):
        load_procurement_config(cfg_file)
