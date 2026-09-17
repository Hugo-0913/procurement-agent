import asyncio

import yaml

from tests.conftest import make_client, make_offline_app


def write_small_cases(tmp_path):
    path = tmp_path / "small_cases.yaml"
    data = [
        {
            "id": "E-1",
            "request_text": "采购 50 箱 A4 纸",
            "quantity": 50,
            "faults": {},
            "expect_state": "COMPLETED",
            "expect_approval": False,
        },
        {
            "id": "E-2",
            "request_text": "采购 3000 箱 A4 纸",
            "quantity": 3000,
            "faults": {"all_quotes_over_budget": True},
            "expect_state": "AWAITING_APPROVAL",
            "expect_approval": True,
        },
    ]
    path.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    return path


async def test_eval_endpoints_run_and_report(tmp_path):
    app = make_offline_app(tmp_path, cases_path=write_small_cases(tmp_path))
    async with await make_client(app) as client:
        assert (await client.get("/eval")).status_code == 200
        latest = (await client.get("/api/eval/latest")).json()
        assert latest["status"] in {"idle", "finished"}

        started = await client.post("/api/eval/run")
        assert started.status_code == 200

        for _ in range(120):
            report = (await client.get("/api/eval/latest")).json()
            if report["status"] == "finished":
                break
            await asyncio.sleep(0.25)

        assert report["status"] == "finished"
        assert report["total"] == 2
        assert "success_rate" in report
        assert report["failures"] == []


async def test_eval_report_persisted_to_disk(tmp_path):
    app = make_offline_app(tmp_path, cases_path=write_small_cases(tmp_path))
    async with await make_client(app) as client:
        await client.post("/api/eval/run")
        for _ in range(120):
            report = (await client.get("/api/eval/latest")).json()
            if report["status"] == "finished":
                break
            await asyncio.sleep(0.25)
    assert (tmp_path / "eval_latest.json").exists()

