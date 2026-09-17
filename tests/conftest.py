from __future__ import annotations

from types import SimpleNamespace
from pathlib import Path

import pytest
import httpx

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


@pytest.fixture(autouse=True)
def isolate_env_file(monkeypatch):
    """测试不允许读取开发者的 .env，避免本地密钥或配置影响断言。"""
    noop = lambda *args, **kwargs: False  # noqa: E731
    monkeypatch.setattr("procurement_agent.config.load_env", noop)
    monkeypatch.setattr("procurement_agent.web.app.load_env", noop)


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


def make_offline_app(tmp_path, quantity: int = 50, cases_path=None):
    import json

    from procurement_agent.eval.runner import EvalRunner
    from procurement_agent.web.app import create_app

    response = json.dumps(
        {
            "material_name": "A4 纸",
            "quantity": quantity,
            "unit": "箱",
            "expected_date": None,
            "budget": None,
            "cost_center": "CC-1001",
            "note": None,
        },
        ensure_ascii=False,
    )
    eval_runner = EvalRunner(
        cases_path=cases_path,
        workspace=tmp_path / "eval_runs",
        output_path=tmp_path / "eval_latest.json",
    )
    app = create_app(
        tmp_path / "web.db",
        offline=True,
        offline_response=response,
        eval_runner=eval_runner,
    )
    return app


@pytest.fixture
def offline_app(tmp_path):
    return make_offline_app(tmp_path)


@pytest.fixture
def big_order_app(tmp_path):
    return make_offline_app(tmp_path, quantity=3000)


async def make_client(app):
    transport = httpx.ASGITransport(app=app)
    return httpx.AsyncClient(transport=transport, base_url="http://test")


@pytest.fixture
async def client(offline_app):
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=offline_app), base_url="http://test"
    ) as http_client:
        yield http_client


async def wait_for_state(client, task_id: str, targets, timeout: float = 15.0):
    import asyncio
    import time

    deadline = time.time() + timeout
    detail = {}
    while time.time() < deadline:
        res = await client.get(f"/api/tasks/{task_id}")
        detail = res.json()
        if detail["state"] in targets:
            return detail
        await asyncio.sleep(0.1)
    return detail
