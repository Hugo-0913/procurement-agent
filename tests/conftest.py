from __future__ import annotations

from types import SimpleNamespace
from pathlib import Path

import pytest

from procurement_agent.config import ProcurementConfig
from procurement_agent.db.models import init_db, seed_demo_data
from procurement_agent.erp.faults import FaultRegistry
from procurement_agent.erp.repository import ErpRepository

TEST_CONFIG = ProcurementConfig(
    approval_threshold=50000.0,
    retry_max_attempts=3,
    context_token_threshold=12000,
    min_quote_count=2,
    freshness_warn_days=30,
)


def build_env(tmp_path: Path) -> SimpleNamespace:
    engine = init_db(tmp_path / "erp.db")
    seed_demo_data(engine)
    faults = FaultRegistry(engine)
    repo = ErpRepository(engine, faults)
    material = repo.find_material_by_name("A4 纸")
    return SimpleNamespace(
        engine=engine,
        faults=faults,
        repo=repo,
        config=TEST_CONFIG,
        material=material,
    )


@pytest.fixture
def env(tmp_path):
    return build_env(tmp_path)

