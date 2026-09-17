from tests.conftest import make_client, wait_for_state


async def test_large_order_awaits_approval_with_rules(big_order_app):
    async with await make_client(big_order_app) as client:
        created = await client.post("/api/tasks", json={"request_text": "采购 3000 箱 A4 纸"})
        task_id = created.json()["task_id"]
        detail = await wait_for_state(client, task_id, {"AWAITING_APPROVAL"})

        assert detail["state"] == "AWAITING_APPROVAL"
        pending = detail["pending_approval"]
        assert pending is not None
        assert any("阈值" in rule for rule in pending["matched_rules"])
        draft = pending["order_draft"]
        assert draft["supplier_name"]
        assert draft["total_amount"] > 50000
        assert draft["lead_days"] > 0
        assert draft["cost_center"] == "CC-1001"
        assert pending["recommendation_reason"]


async def test_approve_writes_order(big_order_app):
    async with await make_client(big_order_app) as client:
        created = await client.post("/api/tasks", json={"request_text": "采购 3000 箱 A4 纸"})
        task_id = created.json()["task_id"]
        await wait_for_state(client, task_id, {"AWAITING_APPROVAL"})

        res = await client.post(
            f"/api/tasks/{task_id}/approval",
            json={"decision": "approve", "operator": "李经理", "reason": "年度备货，预算内"},
        )
        assert res.status_code == 200
        detailed = await wait_for_state(client, task_id, {"COMPLETED", "FAILED"})
        assert detailed["state"] == "COMPLETED"
        assert detailed["order_id"] is not None
        orders = (await client.get("/api/orders")).json()
        assert any(order["task_id"] == task_id for order in orders)


async def test_reject_reruns_sourcing(big_order_app):
    async with await make_client(big_order_app) as client:
        created = await client.post("/api/tasks", json={"request_text": "采购 3000 箱 A4 纸"})
        task_id = created.json()["task_id"]
        await wait_for_state(client, task_id, {"AWAITING_APPROVAL"})

        res = await client.post(
            f"/api/tasks/{task_id}/approval",
            json={"decision": "reject", "operator": "李经理", "reason": "价格不合理"},
        )
        assert res.status_code == 200
        detail = await wait_for_state(
            client, task_id, {"COMPLETED", "FAILED", "AWAITING_APPROVAL"}
        )
        events = detail["events"]
        assert any(
            event["event_type"] == "stage_change" and event["payload"].get("to") == "REVISION_REQUIRED"
            for event in events
        )
        sourcing_delegations = [
            event
            for event in events
            if event["event_type"] == "agent_delegation"
            and event["payload"].get("to") == "sourcing_agent"
        ]
        assert len(sourcing_delegations) >= 2
        decided = [e for e in events if e["event_type"] == "approval_decided"]
        assert decided and decided[-1]["payload"]["reason"] == "价格不合理"


async def test_approval_rejected_when_task_not_waiting(offline_app):
    async with await make_client(offline_app) as client:
        created = await client.post("/api/tasks", json={"request_text": "采购 50 箱 A4 纸"})
        task_id = created.json()["task_id"]
        await wait_for_state(client, task_id, {"COMPLETED", "FAILED"})
        res = await client.post(
            f"/api/tasks/{task_id}/approval",
            json={"decision": "approve", "operator": "x", "reason": ""},
        )
        assert res.status_code == 409

