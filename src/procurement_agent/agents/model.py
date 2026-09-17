from __future__ import annotations

import os


def build_chat_model(**overrides):
    """从环境变量构造 DeepSeek 模型（OpenAI 兼容接口）。"""
    from langchain_deepseek import ChatDeepSeek

    from procurement_agent.config import load_env

    load_env()
    api_key = os.environ.get("DEEPSEEK_API_KEY")
    if not api_key:
        raise RuntimeError("环境变量 DEEPSEEK_API_KEY 未设置")
    return ChatDeepSeek(
        model=os.environ.get("DEEPSEEK_MODEL", "deepseek-chat"),
        api_key=api_key,
        api_base=os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
        temperature=0,
        **overrides,
    )
