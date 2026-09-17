from langchain_core.messages import AIMessage

from procurement_agent.agents.response import response_text


def test_plain_string():
    assert response_text("hello") == "hello"


def test_aimessage():
    assert response_text(AIMessage(content="hello")) == "hello"


def test_json_fence_stripped():
    raw = AIMessage(content='```json\n{"quantity": 50}\n```')
    assert response_text(raw) == '{"quantity": 50}'


def test_bare_fence_stripped():
    raw = AIMessage(content='```\n{"quantity": 50}\n```')
    assert response_text(raw) == '{"quantity": 50}'


def test_content_blocks_joined():
    raw = AIMessage(content=[{"type": "text", "text": "ab"}, {"type": "text", "text": "cd"}])
    assert response_text(raw) == "abcd"


def test_dict_without_content_attribute():
    assert response_text({"content": "x"}) == "x"


def test_offline_model_returns_aimessage():
    from procurement_agent.agents.offline import OfflineModel, parse_request_text

    model = OfflineModel(default_response=None)
    result = model.invoke([{"role": "user", "content": "采购需求：采购 50 箱 A4 纸"}])
    assert isinstance(result, AIMessage)
    import json

    assert json.loads(response_text(result)) == parse_request_text("采购 50 箱 A4 纸")


def test_fake_model_returns_aimessage():
    from tests.fakes import FakeModel

    model = FakeModel(["payload"])
    result = model.invoke([])
    assert isinstance(result, AIMessage)
    assert response_text(result) == "payload"

