from procurement_agent.agents.offline import OfflineModel, parse_request_text
from procurement_agent.agents.response import response_text


def test_parses_quantity_material_and_cost_center():
    result = parse_request_text("采购 50 箱 一次性无菌注射器，成本中心 CC-1001")
    assert result["quantity"] == 50
    assert result["unit"] == "箱"
    assert result["material_name"] == "一次性无菌注射器"
    assert result["cost_center"] == "CC-1001"


def test_parses_large_quantity():
    result = parse_request_text("采购 3000 箱 一次性无菌注射器（报价整体上浮）")
    assert result["quantity"] == 3000


def test_quantity_falls_back_to_plain_number():
    result = parse_request_text("采购 一次性无菌注射器 50")
    assert result["quantity"] == 50
    assert result["unit"] is None


def test_unknown_material_returns_none():
    result = parse_request_text("采购 10 台呼吸机")
    assert result["material_name"] is None
    assert result["quantity"] == 10


def test_vague_request_has_no_quantity():
    result = parse_request_text("帮我再采购一些注射器")
    assert result["quantity"] is None
    assert result["material_name"] == "一次性无菌注射器"


def test_model_returns_json_for_parse_prompt():
    model = OfflineModel(default_response=None)
    prompt = "字段要求：material_name\n采购需求：采购 3000 箱 一次性无菌注射器"
    payload = response_text(model.invoke([{"role": "user", "content": prompt}]))
    assert '"quantity": 3000' in payload


def test_model_returns_summary_for_summary_prompt():
    # 摘要识别属于 Agent 模式的行为（应用里由 offline_model_factory 统一开启）
    model = OfflineModel(default_response=None, agent_mode=True)
    payload = response_text(
        model.invoke([{"role": "user", "content": "请把以下对话压缩为不超过 3 行的中文摘要"}])
    )
    assert "推荐" in payload
    assert "quantity" not in payload


def test_explicit_response_still_honoured():
    model = OfflineModel(default_response='{"material_name": "X", "quantity": 1}')
    payload = response_text(model.invoke([{"role": "user", "content": "采购需求：随便"}]))
    assert payload == '{"material_name": "X", "quantity": 1}'
