# 决策与验证记录

本文件记录关键技术决策、验证结论与偏差，作为后续实现的依据。

---

## D-001 运行环境与依赖隔离（2026-09-17）

**决策：** 项目使用仓库内虚拟环境 `.venv`，所有命令通过 `.venv\Scripts\python.exe` 执行。

**原因：** 首次在 Anaconda base 环境安装依赖时，pip 升级了 base 环境中的 pydantic（1.10→2.13）、fastapi（0.94→0.141）、sqlalchemy（1.4→2.0）、websockets、anyio 等包，并报出与 gradio、jupyter-server 的冲突；随后仍因 base 环境残留的 aiohttp 3.8.3 过旧导致 `openai` 导入失败。因此改用独立虚拟环境，避免继续影响 base 环境。

**遗留影响：** base 环境中的 gradio、jupyter-server 可能因 websockets / anyio 升级而不可用，需要时用 conda 单独修复。

---

## D-002 依赖版本锁定（2026-09-17，Task 2 冒烟验证产出）

| 包 | 版本 |
| --- | --- |
| deepagents | 0.7.15 |
| langgraph | 1.2.11 |
| langgraph-checkpoint-sqlite | 3.1.1 |
| langchain | 1.4.1 |
| langchain-core | 1.6.3 |
| langchain-deepseek | 1.1.0 |
| fastapi | 0.141.1 |
| pydantic | 2.13.5 |
| sqlalchemy | 2.0.54 |
| pytest | 9.1.1 |

---

## D-003 `create_deep_agent` 实际签名（2026-09-17，Task 2 验证）

```
create_deep_agent(
    model=None, tools=None, *, system_prompt=None, middleware=(),
    subagents=None, skills=None, memory=None, permissions=None, backend=None,
    interrupt_on=None, response_format=None, state_schema=None,
    context_schema=None, checkpointer=None, store=None, debug=False,
    name=None, cache=None,
)
```

---

## D-004 框架原生能力盘查（2026-09-17，Task 2 验证）

deepagents 0.7.15 原生提供以下能力，与 PRD 的功能需求高度重合：

| 框架能力 | 对应需求 | 说明 |
| --- | --- | --- |
| `subagents=[SubAgent]` | 主 Agent + 三类子 Agent | 主 Agent 获得 `task` 工具进行委派；SubAgent 支持 `name`、`description`、`system_prompt`、`mode`（isolated/fork）、`tools`、`model`、`middleware`、`interrupt_on`、`skills`、`permissions` |
| `skills=[路径]` | FR-06 技能系统与渐进式加载 | `SkillsMiddleware` 实现 Anthropic agent skills 模式：SKILL.md frontmatter 作为索引常驻，正文按需加载；技能按来源分层覆盖 |
| `memory=[路径]` | FR-08 持久化记忆 | `MemoryMiddleware` 加载 AGENTS.md 类文件，启动即注入系统提示（常驻，非按需） |
| `permissions=[FilesystemPermission]` | FR-07 / FR-10 层一 | `FilesystemMiddleware` 在工具层强制路径权限，规则按声明顺序首个匹配生效 |
| `interrupt_on={工具名: 配置}` | FR-05 人工审批 | `HumanInTheLoopMiddleware`，需要 checkpointer |
| `backend=` | FR-07 虚拟文件系统 | 可选 `StateBackend` / `FilesystemBackend` / `StoreBackend` / `CompositeBackend` / `LocalShellBackend` / `LangSmithSandbox` |
| `create_summarization_middleware(model, backend)` | FR-09 上下文摘要 | 内建摘要中间件，产生 `SummarizationEvent` |
| `checkpointer=` | 任务恢复 | 支持传入 LangGraph checkpointer（本项目用 `SqliteSaver`） |

**框架未提供、必须自研的部分：** 任务状态机（阶段流转与唯一状态源）、向 SQLite 落库的事件流、业务规则判定（资质核验、比价、金额阈值）、mock ERP 与故障注入、Web 界面与 SSE、评测运行器与指标。

---

## D-005 实现策略调整：复用原生能力 + 自研治理层（2026-09-17）

**偏差说明：** 原 `plan.md` 中 Task 7（技能）、Task 13（虚拟文件系统）、Task 14（记忆）、Task 15（摘要）按"完全自研"编写。冒烟验证后确认为**复用框架原生实现 + 保留我方薄层**。

**调整后的分工：**

1. `skills_loader.py` 保留：它是**离线可测的元数据层**，为 Web 界面提供"已加载全文 / 仅描述"的可观测状态，并让测试不依赖框架内部实现；同时把 `skills=["/skills"]` 传给 `create_deep_agent`，让真实 Agent 走框架的渐进式加载。
2. `vfs.py` 保留为**策略层**（路径逃逸防护、独立可测），并同时通过 `permissions` 在框架工具层强制约束。
3. `memory/store.py` 保留为**业务记忆**（采购偏好、供应商历史，落 SQLite，可被 Web 展示）；框架的 `memory=` 用于承载静态约定（AGENTS.md 类），两者职责不同。
4. `context_summarizer.py` 保留 `estimate_tokens` 与 `SummaryResult`，用于产生可观测的 token 指标与事件；长对话的实际压缩交给框架摘要中间件。
5. 审批拦截以**我方状态机的持久化中断为主**（保证状态落库、页面可渲染、跨进程可恢复），框架 `interrupt_on` 作为工具级的补充拦截。

**理由：** 需求与框架能力重合时重复造轮子会削弱工程判断力；但业务确定性、可观测性与离线可测性必须掌握在自己手里。该分工同时让简历表述更准确——"复用框架原生能力并自研治理层"比"全部手写"更有说服力。

---

## D-006 冒烟验证结论（2026-09-17）

脚本：`scripts/smoke_deepagents.py`

| 验证项 | 结果 |
| --- | --- |
| 构造主 Agent 并绑定工具 | 通过 |
| 装配 3 个子 Agent + `skills` + `permissions` + `interrupt_on` + `SqliteSaver` checkpointer | 通过（编译出的图包含 6 个节点） |
| 主 Agent 委派子 Agent 的实况调用 | **待验证** —— 本机未设置 `DEEPSEEK_API_KEY`，脚本已跳过并保留实况分支 |

**待办：** 配置 `DEEPSEEK_API_KEY` 后重跑 `python scripts/smoke_deepagents.py`，确认 `task` 工具被调用，并把结论补记到本文件。在此之前，委派相关代码按"接口已确认、运行时行为待验证"处理，且所有自动化测试必须使用模型替身离线运行。

