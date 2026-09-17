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

