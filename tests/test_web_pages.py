from tests.conftest import make_client


async def test_board_page_renders(offline_app):
    async with await make_client(offline_app) as client:
        res = await client.get("/")
        assert res.status_code == 200
        html = res.text
        for label in ("全部", "运行中", "等待审批", "已完成", "失败"):
            assert label in html
        assert "填入示例需求" in html
        assert 'id="task-list"' in html
        assert 'id="new-request"' in html or 'id="request-text"' in html


async def test_board_static_files_served(offline_app):
    async with await make_client(offline_app) as client:
        assert (await client.get("/static/app.css")).status_code == 200
        assert (await client.get("/static/board.js")).status_code == 200


async def test_task_page_has_required_blocks(offline_app):
    async with await make_client(offline_app) as client:
        res = await client.get("/tasks/t-demo")
        assert res.status_code == 200
        html = res.text
        for block in ("stage-bar", "left-panel", "task-tree", "timeline", "result-card"):
            assert f'id="{block}"' in html
        assert "已加载记忆" in html
        assert "技能状态" in html
        for stage in ("需求解析", "资质核验", "比价分析", "订单审批", "完成"):
            assert stage in html


async def test_task_page_scripts_served(offline_app):
    async with await make_client(offline_app) as client:
        for name in ("task.js", "tree.js", "timeline.js", "approval.js"):
            assert (await client.get(f"/static/{name}")).status_code == 200


async def test_data_page_renders(offline_app):
    async with await make_client(offline_app) as client:
        res = await client.get("/data")
        assert res.status_code == 200
        html = res.text
        assert "模拟异常情况" in html
        for label in (
            "让瑞康医械供应链的经营许可证过期",
            "让济生医疗科技停止报价",
            "让全部报价涨到三倍",
        ):
            assert label in html
        # 数据台改成了业务视角的三个问题，不再是技术字段罗列
        assert "供应商能不能用" in html
        assert "谁家报价划算" in html
        assert "买到的东西" in html
        assert (await client.get("/static/data.js")).status_code == 200


async def test_eval_page_renders(offline_app):
    async with await make_client(offline_app) as client:
        res = await client.get("/eval")
        assert res.status_code == 200
        html = res.text
        assert "运行评测" in html
        assert (await client.get("/static/eval.js")).status_code == 200


async def test_fault_panel_labels_come_from_api(offline_app):
    async with await make_client(offline_app) as client:
        flags = (await client.get("/api/faults")).json()["flags"]
        labels = {flag["label"] for flag in flags}
        assert "让瑞康医械供应链的经营许可证过期" in labels
        assert "让全部报价涨到三倍" in labels
