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

