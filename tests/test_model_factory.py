import pytest

from procurement_agent.agents.model import build_chat_model


def test_missing_api_key_raises(monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="DEEPSEEK_API_KEY"):
        build_chat_model()


def test_build_with_key(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test-dummy")
    monkeypatch.setenv("DEEPSEEK_MODEL", "deepseek-chat")
    model = build_chat_model()
    assert model.model_name == "deepseek-chat"

