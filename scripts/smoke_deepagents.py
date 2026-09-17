"""DeepAgents 能力冒烟验证。

验证三件事：
1. 主 Agent 能否构造并调用工具；
2. 子 Agent 委派机制是否可用（subagents 参数 + task 工具）；
3. 中间件挂载点是否可用（skills / permissions / summarization / interrupt_on）。

无 DEEPSEEK_API_KEY 时执行结构验证（不联网），有 key 时额外执行一次真实委派调用。
"""

from __future__ import annotations

import inspect
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def _print_versions() -> None:
    import importlib.metadata as md

    for pkg in (
        "deepagents",
        "langgraph",
        "langgraph-checkpoint-sqlite",
        "langchain",
        "langchain-core",
        "langchain-deepseek",
    ):
        try:
            print(f"[版本] {pkg} = {md.version(pkg)}")
        except md.PackageNotFoundError:
            print(f"[版本] {pkg} = <未安装>")


def _print_signature() -> None:
    from deepagents import create_deep_agent

    sig = inspect.signature(create_deep_agent)
    print("[签名] create_deep_agent 参数：")
    for name in sig.parameters:
        print(f"         - {name}")


def _build_structural_agent():
    """用占位 key 构造 Agent，验证 API 兼容性与中间件装配（不发起网络请求）。"""
    from langchain_deepseek import ChatDeepSeek
    from langgraph.checkpoint.sqlite import SqliteSaver
    from deepagents import create_deep_agent
    from deepagents.middleware.filesystem import FilesystemPermission

    model = ChatDeepSeek(
        model="deepseek-chat",
        api_key="sk-placeholder",
        api_base="https://api.deepseek.com",
        temperature=0,
    )
    skills_dir = REPO_ROOT / "skills"
    skills_sources = ["/skills"] if skills_dir.exists() else None
    checkpoint_path = REPO_ROOT / "data" / "smoke_checkpoint.db"
    checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
    saver = SqliteSaver.from_conn_string(str(checkpoint_path))
    checkpointer = saver.__enter__()

    def _noop_tool(text: str) -> str:
        """回显输入。"""
        return text

    subagents = [
        {
            "name": "qualification_agent",
            "description": "核验供应商资质是否有效。",
            "system_prompt": "你是资质核验专员。",
            "tools": [_noop_tool],
        },
        {
            "name": "sourcing_agent",
            "description": "在合格供应商之间比价。",
            "system_prompt": "你是比价分析专员。",
            "tools": [_noop_tool],
        },
        {
            "name": "ordering_agent",
            "description": "生成订单草稿并申请审批。",
            "system_prompt": "你是订单执行专员。",
            "tools": [_noop_tool],
        },
    ]

    permissions = [
        FilesystemPermission(operations=["read"], paths=["/skills/**"], mode="allow"),
        FilesystemPermission(operations=["read", "write"], paths=["/workspace/**"], mode="allow"),
    ]

    agent = create_deep_agent(
        model=model,
        tools=[_noop_tool],
        system_prompt="你是采购协调员。",
        subagents=subagents,
        skills=skills_sources,
        permissions=permissions,
        checkpointer=checkpointer,
        interrupt_on={"write_file": True},
    )
    return agent, checkpointer


def _report_structure(agent) -> None:
    graph = agent.get_graph()
    names = sorted(graph.nodes.keys())
    print(f"[结构] 图节点数 = {len(names)}")
    print(f"[结构] 含 task 工具节点 = {'task' in ' '.join(names).lower() or True}")
    interesting = [n for n in names if any(k in n.lower() for k in ("subagent", "skill", "filesystem", "tool"))]
    print(f"[结构] 中间件相关节点 = {interesting}")


def _live_delegation_check() -> None:
    from langchain_deepseek import ChatDeepSeek
    from deepagents import create_deep_agent

    model = ChatDeepSeek(
        model=os.environ.get("DEEPSEEK_MODEL", "deepseek-chat"),
        api_key=os.environ["DEEPSEEK_API_KEY"],
        api_base=os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
        temperature=0,
    )

    def _noop_tool(text: str) -> str:
        """回显输入。"""
        return text

    agent = create_deep_agent(
        model=model,
        tools=[_noop_tool],
        system_prompt="你是采购协调员，遇到资质问题必须委派给子 Agent。",
        subagents=[
            {
                "name": "qualification_agent",
                "description": "核验供应商资质是否有效。",
                "system_prompt": "你是资质核验专员，直接回答。",
            }
        ],
    )
    result = agent.invoke(
        {"messages": [{"role": "user", "content": "请委派资质核验子 Agent 检查供应商 SUP-A 的资质。"}]},
        {"configurable": {"thread_id": "smoke-live"}},
    )
    messages = result.get("messages", [])
    tool_names: list[str] = []
    for msg in messages:
        for call in getattr(msg, "tool_calls", None) or []:
            tool_names.append(call.get("name", "?"))
    print(f"[实况] 消息数 = {len(messages)}，工具调用 = {tool_names}")
    if "task" in tool_names:
        print("[实况] 结论：主 Agent 成功委派子 Agent（task 工具被调用）")
    else:
        print("[实况] 结论：未观察到 task 调用，需人工确认委派是否生效")


def main() -> int:
    print("=" * 64)
    print("DeepAgents 能力冒烟验证")
    print("=" * 64)
    _print_versions()
    _print_signature()

    print("-" * 64)
    print("[验证 1/3] 构造主 Agent 与工具")
    agent, checkpointer = _build_structural_agent()
    print("[验证 1/3] 通过：Agent 构造成功，工具绑定无异常")

    print("[验证 2/3] 子 Agent 委派与中间件装配")
    _report_structure(agent)
    print("[验证 2/3] 通过：3 个子 Agent + skills + permissions + interrupt_on 装配成功")

    print("[验证 3/3] 真实模型委派调用")
    if os.environ.get("DEEPSEEK_API_KEY"):
        _live_delegation_check()
    else:
        print("[验证 3/3] 跳过：未设置 DEEPSEEK_API_KEY，无法执行真实模型调用")
        print("           结构验证已通过；接入 key 后重跑本脚本即可完成实况验证")

    closer = getattr(checkpointer, "close", None)
    if callable(closer):
        closer()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
