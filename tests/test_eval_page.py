import asyncio

import yaml

from tests.conftest import make_client, make_offline_app


def write_small_cases(tmp_path):
    path = tmp_path / "small_cases.yaml"
    data = [
        {
            "id": "E-1",
            "request_text": "采购 50 箱 一次性无菌注射器",
            "quantity": 50,
            "faults": {},
            "expect_state": "COMPLETED",
            "expect_approval": False,
        },
        {
            "id": "E-2",
            "request_text": "采购 3000 箱 一次性无菌注射器",
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

        # 轮询预算给得宽：整包并行跑测试时机器负载高，2 条用例也可能超过 30 秒
        for _ in range(400):
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
        for _ in range(400):
            report = (await client.get("/api/eval/latest")).json()
            if report["status"] == "finished":
                break
            await asyncio.sleep(0.25)
    assert (tmp_path / "eval_latest.json").exists()


async def test_web_app_gets_a_default_eval_runner(tmp_path):
    """网页版必须自带评测运行器，否则评测页点按钮只会返回 503。"""
    import asyncio

    import yaml

    from procurement_agent.web.app import create_app

    cases_file = tmp_path / "cases.yaml"
    cases_file.write_text(
        yaml.safe_dump(
            [
                {
                    "id": "W-1",
                    "request_text": "采购 50 箱一次性无菌注射器",
                    "quantity": 50,
                    "faults": {},
                    "expect_state": "COMPLETED",
                    "expect_approval": False,
                }
            ],
            allow_unicode=True,
        ),
        encoding="utf-8",
    )
    app = create_app(tmp_path / "default.db", offline=True)
    assert app.state.ctx.eval_runner is not None
    app.state.ctx.eval_runner.cases_path = cases_file
    app.state.ctx.eval_runner.workspace = tmp_path / "runs"
    app.state.ctx.eval_runner.output_path = tmp_path / "latest.json"

    async with await make_client(app) as client:
        assert (await client.post("/api/eval/run")).status_code == 200
        for _ in range(120):
            report = (await client.get("/api/eval/latest")).json()
            if report["status"] in {"finished", "failed"}:
                break
            await asyncio.sleep(0.25)
    assert report["status"] == "finished"
    assert report["total"] == 1

