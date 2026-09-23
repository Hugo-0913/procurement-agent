import pytest

from tests.conftest import make_offline_app, make_client, wait_for_state


async def test_create_task_returns_id(offline_app):
    async with await make_client(offline_app) as client:
        res = await client.post("/api/tasks", json={"request_text": "采购 50 箱 A4 纸"})
        assert res.status_code == 200
        assert res.json()["task_id"].startswith("t-")


async def test_blank_request_rejected(offline_app):
    async with await make_client(offline_app) as client:
        res = await client.post("/api/tasks", json={"request_text": "   "})
        assert res.status_code == 422


async def test_task_list_contains_created_task(offline_app):
    async with await make_client(offline_app) as client:
        created = await client.post("/api/tasks", json={"request_text": "采购 50 箱 A4 纸"})
        task_id = created.json()["task_id"]
        await wait_for_state(client, task_id, {"COMPLETED", "FAILED"})
        res = await client.get("/api/tasks")
        assert res.status_code == 200
        assert any(item["id"] == task_id for item in res.json())


async def test_task_detail_has_state_and_events(offline_app):
    async with await make_client(offline_app) as client:
        created = await client.post("/api/tasks", json={"request_text": "采购 50 箱 A4 纸"})
        task_id = created.json()["task_id"]
        await wait_for_state(client, task_id, {"COMPLETED", "FAILED"})
        detail = (await client.get(f"/api/tasks/{task_id}")).json()
        assert detail["state"] == "COMPLETED"
        assert detail["events"]
        assert detail["loaded_skills"]
        assert detail["metadata_only_skills"] == [] or isinstance(
            detail["metadata_only_skills"], list
        )


async def test_unknown_task_returns_404(offline_app):
    async with await make_client(offline_app) as client:
        assert (await client.get("/api/tasks/nope")).status_code == 404


async def test_reject_without_reason_returns_422(big_order_app):
    async with await make_client(big_order_app) as client:
        created = await client.post("/api/tasks", json={"request_text": "采购 3000 箱 A4 纸"})
        task_id = created.json()["task_id"]
        await wait_for_state(client, task_id, {"AWAITING_APPROVAL"})
        res = await client.post(
            f"/api/tasks/{task_id}/approval",
            json={"decision": "reject", "operator": "bob", "reason": ""},
        )
        assert res.status_code == 422


async def test_orders_endpoint_reflects_created_order(offline_app):
    async with await make_client(offline_app) as client:
        created = await client.post("/api/tasks", json={"request_text": "采购 50 箱 A4 纸"})
        task_id = created.json()["task_id"]
        await wait_for_state(client, task_id, {"COMPLETED", "FAILED"})
        orders = (await client.get("/api/orders")).json()
        assert len(orders) == 1
        assert orders[0]["task_id"] == task_id
        assert orders[0]["total_amount"] > 0


async def test_fault_toggle_persists(offline_app):
    async with await make_client(offline_app) as client:
        before = (await client.get("/api/faults")).json()
        assert all(not flag["enabled"] for flag in before["flags"])
        await client.post(
            "/api/faults",
            json={"flag": "supplier_c_no_quote", "enabled": True},
        )
        after = (await client.get("/api/faults")).json()
        enabled = {flag["flag"]: flag["enabled"] for flag in after["flags"]}
        assert enabled["supplier_c_no_quote"] is True


async def test_suppliers_and_quotes_endpoints(offline_app):
    async with await make_client(offline_app) as client:
        suppliers = (await client.get("/api/suppliers")).json()
        assert len(suppliers) == 4
        quotes = (await client.get("/api/quotes")).json()
        assert len(quotes) == 3


async def test_auto_mode_falls_back_to_offline_without_key(tmp_path, monkeypatch):
    """没有 API key 时不应让任务失败，而应自动使用离线模型跑通全流程。"""
    from procurement_agent.web.app import create_app

    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    app = create_app(tmp_path / "auto.db")
    assert app.state.offline is True

    async with await make_client(app) as client:
        created = await client.post("/api/tasks", json={"request_text": "采购 50 箱 A4 纸"})
        task_id = created.json()["task_id"]
        detail = await wait_for_state(client, task_id, {"COMPLETED", "FAILED"})
        assert detail["state"] == "COMPLETED"
        assert detail["order_id"] is not None


async def test_auto_mode_board_shows_offline_banner(tmp_path, monkeypatch):
    from procurement_agent.web.app import create_app

    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    app = create_app(tmp_path / "auto.db")
    async with await make_client(app) as client:
        html = (await client.get("/")).text
        assert "离线演示模式" in html


async def test_explicit_offline_false_requires_key(tmp_path, monkeypatch):
    from procurement_agent.web.app import create_app

    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    app = create_app(tmp_path / "live.db", offline=False)
    assert app.state.offline is False
    async with await make_client(app) as client:
        created = await client.post("/api/tasks", json={"request_text": "采购 50 箱 A4 纸"})
        task_id = created.json()["task_id"]
        detail = await wait_for_state(client, task_id, {"FAILED", "COMPLETED"})
        assert detail["state"] == "FAILED"
        errors = [e for e in detail["events"] if e["event_type"] == "error"]
        assert errors and "DEEPSEEK_API_KEY" in errors[0]["payload"]["message"]


async def test_demo_app_factory_forces_offline(tmp_path, monkeypatch):
    from procurement_agent.web.app import create_app

    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-dummy-for-this-test")
    app = create_app(tmp_path / "demo.db", offline=True)
    assert app.state.offline is True


async def test_offline_parser_drives_approval_flow(tmp_path, monkeypatch):
    """回归：没有 API key 时，提交"3000 箱"必须真的按 3000 箱解析并触发审批。"""
    from procurement_agent.web.app import create_app

    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    app = create_app(tmp_path / "parser.db")
    async with await make_client(app) as client:
        created = await client.post(
            "/api/tasks", json={"request_text": "采购 3000 箱 A4 纸，成本中心 CC-1001"}
        )
        task_id = created.json()["task_id"]
        detail = await wait_for_state(client, task_id, {"AWAITING_APPROVAL", "FAILED"})
        assert detail["state"] == "AWAITING_APPROVAL"
        assert detail["structured_request"]["quantity"] == 3000
        assert detail["pending_approval"]["order_draft"]["quantity"] == 3000


async def test_vague_request_asks_for_clarification(tmp_path, monkeypatch):
    from procurement_agent.web.app import create_app

    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    app = create_app(tmp_path / "clarify.db")
    async with await make_client(app) as client:
        created = await client.post("/api/tasks", json={"request_text": "帮我再采购一些纸"})
        task_id = created.json()["task_id"]
        detail = await wait_for_state(
            client, task_id, {"AWAITING_CLARIFICATION", "COMPLETED", "FAILED"}
        )
        assert detail["state"] == "AWAITING_CLARIFICATION"
        assert detail["pending_clarification"] is not None
        assert "数量" in detail["pending_clarification"]["question"]
        assert not [
            e for e in detail["events"] if e["event_type"] == "agent_delegation"
        ]


async def test_clarification_endpoint_completes_task(tmp_path, monkeypatch):
    """补齐缺失信息后，任务应继续跑完并落单。"""
    import json

    from procurement_agent.web.app import create_app

    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    app = create_app(
        tmp_path / "clarify2.db",
        offline=True,
        offline_script=[
            # 第一次解析：数量缺失，触发澄清
            json.dumps({"material_name": "A4 纸", "quantity": None}, ensure_ascii=False),
            # 用户补充后再解析：信息完整
            json.dumps(
                {
                    "material_name": "A4 纸",
                    "quantity": 50,
                    "unit": "箱",
                    "expected_date": None,
                    "budget": None,
                    "cost_center": "CC-1001",
                    "note": None,
                },
                ensure_ascii=False,
            ),
        ],
    )
    async with await make_client(app) as client:
        created = await client.post("/api/tasks", json={"request_text": "帮我买点办公用纸"})
        task_id = created.json()["task_id"]
        detail = await wait_for_state(client, task_id, {"AWAITING_CLARIFICATION"})
        assert detail["state"] == "AWAITING_CLARIFICATION"

        blank = await client.post(
            f"/api/tasks/{task_id}/clarification", json={"answer": "   "}
        )
        assert blank.status_code == 422

        answered = await client.post(
            f"/api/tasks/{task_id}/clarification", json={"answer": "50 箱"}
        )
        assert answered.status_code == 200
        finished = await wait_for_state(client, task_id, {"COMPLETED", "FAILED"})
        assert finished["state"] == "COMPLETED"
        assert "50 箱" in finished["request_text"]


async def test_clarification_rejected_when_not_needed(offline_app):
    async with await make_client(offline_app) as client:
        created = await client.post("/api/tasks", json={"request_text": "采购 50 箱 A4 纸"})
        task_id = created.json()["task_id"]
        await wait_for_state(client, task_id, {"COMPLETED", "FAILED"})
        res = await client.post(
            f"/api/tasks/{task_id}/clarification", json={"answer": "50 箱"}
        )
        assert res.status_code == 409


async def test_approval_is_recorded_and_queryable(big_order_app):
    """审批留痕要能通过接口查到，而不是只躺在事件流里。"""
    async with await make_client(big_order_app) as client:
        created = await client.post("/api/tasks", json={"request_text": "采购 3000 箱 A4 纸"})
        task_id = created.json()["task_id"]
        await wait_for_state(client, task_id, {"AWAITING_APPROVAL"})

        empty = await client.get(f"/api/tasks/{task_id}/approvals")
        assert empty.status_code == 200
        assert empty.json() == []

        await client.post(
            f"/api/tasks/{task_id}/approval",
            json={"decision": "approve", "operator": "王主管", "reason": "预算内"},
        )
        await wait_for_state(client, task_id, {"COMPLETED", "FAILED"})

        records = (await client.get(f"/api/tasks/{task_id}/approvals")).json()
        assert len(records) == 1
        assert records[0]["operator"] == "王主管"
        assert records[0]["decision"] == "approve"
        assert any("阈值" in rule for rule in records[0]["matched_rules"])
