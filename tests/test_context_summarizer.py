from procurement_agent.config import ProcurementConfig
from procurement_agent.middleware.context_summarizer import (
    ContextSummarizer,
    SummaryResult,
    estimate_tokens,
)
from tests.fakes import FixedModelFactory

SMALL_THRESHOLD = ProcurementConfig(50000.0, 3, 100, 2, 30)


def test_estimate_tokens_mixed_language():
    assert estimate_tokens("采购订单") == 4
    assert estimate_tokens("abcdefgh") == 2
    assert estimate_tokens("") == 0
    assert estimate_tokens("A4 纸") == 2  # 1 个汉字 + 3 个非中文（0.75 → 1）


def test_below_threshold_returns_original():
    summarizer = ContextSummarizer(SMALL_THRESHOLD, FixedModelFactory(["摘要"]))
    messages = [{"role": "user", "content": "短消息"}]
    result, summary = summarizer.maybe_summarize(messages, {"quantity": 50})
    assert result is messages
    assert summary is None


def test_above_threshold_compresses_tool_results():
    summarizer = ContextSummarizer(SMALL_THRESHOLD, FixedModelFactory(["已压缩的结论"]))
    messages = [
        {"role": "user", "content": "采购 50 箱 A4 纸"},
        {"role": "tool", "content": "x" * 4000},
    ]
    essential = {"quantity": 50, "material": "A4 纸"}
    result, summary = summarizer.maybe_summarize(messages, essential)

    assert isinstance(summary, SummaryResult)
    assert summary.after_tokens < summary.before_tokens
    assert "tool_result" in summary.dropped_categories
    assert summary.summary == "已压缩的结论"
    assert len(result) == len(messages) + 2  # 关键要素块 + 摘要块


def test_essential_fields_survive_compression():
    summarizer = ContextSummarizer(SMALL_THRESHOLD, FixedModelFactory(["摘要"]))
    messages = [{"role": "tool", "content": "y" * 4000}]
    essential = {"quantity": 50, "material": "A4 纸", "cost_center": "CC-1001"}
    result, summary = summarizer.maybe_summarize(messages, essential)
    joined = " ".join(str(m["content"]) for m in result)
    assert summary is not None
    assert "CC-1001" in joined
    assert "A4 纸" in joined
    assert "50" in joined


def test_non_tool_messages_are_preserved():
    summarizer = ContextSummarizer(SMALL_THRESHOLD, FixedModelFactory(["摘要"]))
    messages = [
        {"role": "user", "content": "采购 50 箱 A4 纸"},
        {"role": "tool", "content": "z" * 4000},
    ]
    result, _ = summarizer.maybe_summarize(messages, {})
    assert {"role": "user", "content": "采购 50 箱 A4 纸"} in result
    assert any(str(m["content"]).startswith("[工具结果摘要]") for m in result)
