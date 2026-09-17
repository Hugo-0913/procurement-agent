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

---

## D-007 实施阶段偏差与缺陷修复记录（2026-09-17）

按 `plan.md` 逐阶段实施时产生的偏差与发现的问题，逐条记录如下。

### 1. 测试期望比原计划更严格（非放宽）

原计划 Task 12 断言"`skill_loaded` 不含未使用的 `order_compliance`"。实际完整流程四个技能都会被加载（每个阶段各用一个），该断言与设计不符。改为两条更精确的断言：

- 完整任务按阶段顺序依次加载四个技能：`requirement_parsing → supplier_qualification → price_comparison → order_compliance`；
- 在需求解析阶段就因缺字段中止的任务，**只**加载 `requirement_parsing`，三个子 Agent 的委派事件为空。

后者才是渐进式加载的真实证据：未走到后面的阶段，后面的技能就不会被加载。

### 2. 发现并修复的缺陷

| 编号 | 缺陷 | 现象 | 修复 |
| --- | --- | --- | --- |
| BUG-01 | 审批决策残留在图状态中 | 驳回后重跑到第二轮，路由函数再次执行 `AWAITING_APPROVAL → REVISION_REQUIRED` 转移，触发非法转移，任务被判为 `FAILED` | 路由前先检查当前状态，只有确实处于 `AWAITING_APPROVAL` 时才执行转移 |
| BUG-02 | 订单总额未按实际数量重算 | `run_ordering` 直接复用比价阶段按旧数量算出的总额，数量变化时草稿金额错误（如 3000 箱仍显示 50 箱的金额） | 在 `run_ordering` 内按传入数量重算总额与差额比例 |
| BUG-03 | 虚拟文件系统拒绝 `.` | 受限执行器的默认 `cwd="."` 被判定为路径穿越，所有命令都执行失败 | `resolve` 显式将 `.` / `./` / 空串映射为工作区根 |
| BUG-04 | 子 Agent 技能加载事件重复或缺失 | 先由子 Agent 内部加载技能、再在协调器中补发事件，顺序不确定 | 改为协调器统一调用 `_load_skill`，子 Agent 不再自行加载 |

### 3. 有意的实现调整

| 调整 | 原因 |
| --- | --- |
| `run_ordering` 增加 `material_id` 参数 | 订单草稿必须携带物料主键，原签名无法提供 |
| 种子数据中 `SUP-C` 单价由 23.0 改为 20.2 | 使其成为"最低价但资质临期"，才能演示 PRD 场景 S2（最优供应商临期、系统改选次优并说明理由） |
| 环境变量白名单增加 `SYSTEMROOT` / `PATHEXT` / `COMSPEC` | Windows 下缺少这些变量解释器无法启动，属平台约束 |
| 阶段名与故障开关改为服务端渲染 | 首屏不闪空，且页面标签可被测试直接断言 |
| 新增上下文压缩率指标 | 原描述声称"上下文占用降低 70%"，必须给出可复现出处，见 D-008 |
| `.git` 目录在沙箱中为只读 | git 提交必须提权执行，属环境事实，不影响仓库本身 |

### 4. 与框架能力的分工（落实 D-005）

框架原生的 `subagents` / `skills` / `memory` / `permissions` / `interrupt_on` / 摘要中间件全部保留可用；自研部分集中在框架未覆盖的地方：任务状态机与事件落库、业务规则判定、mock ERP 与故障注入、Web 可视化、评测运行器。`skills_loader.py` 保留为薄的可观测层，供页面与离线测试使用。

---

## D-008 实测指标（离线确定性模式，2026-09-17）

运行命令：`.venv\Scripts\python.exe -m procurement_agent.eval.runner --out eval_results/latest.json`

| 指标 | 数值 | 口径 |
| --- | --- | --- |
| 用例总数 | 30 | 正常路径 12、单故障 15、组合故障 3 |
| 成功率 | 100%（30/30） | 实际终态与期望终态一致，且审批触发与期望一致 |
| 人工介入率 | 26.7%（8/30） | 触发人工审批的用例占比 |
| 平均耗时 | 约 153 ms | 离线模式墙钟时间，**不含真实模型时延** |
| 上下文压缩率 | 87.6%（4670 → 578 token） | 12 段工具返回、每段约 1500 字符的长对话基准 |
| 自动化测试 | 144 项全部通过 | `pytest tests/ -q` |

**重要口径说明：** 上述指标全部由离线确定性模式产出，模型调用由固定脚本替代，验证的是流程编排、状态机、策略与治理逻辑的正确性与可复现性，**不代表真实模型下的端到端成功率与时延**。真实模型指标需配置 `DEEPSEEK_API_KEY` 后单独运行，两者不可混用陈述。

---

## D-009 尚未完成与待验证事项（2026-09-17）

1. **真实模型冒烟验证未完成**：本机无 `DEEPSEEK_API_KEY`，`scripts/smoke_deepagents.py` 的实况委派验证（第 3 项）仍为待验证状态。配置 key 后重跑该脚本即可补齐，结论需回填至 D-006。
2. **真实模型端到端评测未运行**：`eval/runner.py` 默认使用离线模型工厂；切换为 `build_chat_model` 后需要重新评估用例期望值（真实模型可能对同一需求给出不同解析结果）。
3. **并发多任务未支持**：技能注册表为进程内共享状态，Web 层以线程方式启动任务，当前面向单任务演示。若需并发，应把技能加载状态改为按任务隔离（事件流已按任务记录，改造点集中在 `SkillRegistry`）。
4. **真实 ERP 对接未实现**：按 PRD 3.2 属于明确不做项，mock 仓储的接口边界（`ErpRepository`）已是替换点。

---

## D-010 真实模型验证完成（2026-09-17）

配置 `DEEPSEEK_API_KEY` 后完成 D-006 遗留的实况验证，并跑通真实模型下的端到端与全量评测。

### 冒烟验证（D-006 第 3 项，已闭环）

`scripts/smoke_deepagents.py`：

```
[实况] 消息数 = 4，工具调用 = ['task']
[实况] 结论：主 Agent 成功委派子 Agent（task 工具被调用）
```

同时观察到装配了 `skills` 后中间件节点由 2 个变为 3 个（新增 `SkillsMiddleware.before_agent`），确认技能中间件确实挂载。

### 真实模型实测指标

| 指标 | 离线确定性模式 | 真实模型模式 |
| --- | --- | --- |
| 用例总数 | 30 | 30 |
| 成功率 | 100% | 100%（30/30） |
| 人工介入率 | 26.7% | 26.7% |
| 平均耗时 | 约 259 ms | 约 1237 ms |
| 上下文压缩率 | 87.3% | 87.3% |

运行命令：`.venv\Scripts\python.exe -m procurement_agent.eval.runner --live --out eval_results/live_full.json`

真实模型下单条采购任务端到端约 6 秒完成（含 1 次模型调用 + 3 个子 Agent 的确定性执行）。

### 真机暴露并修复的问题（共 5 个）

这些问题**全部是离线测试与单元测试无法发现的**，只有把服务真正跑起来、用真实模型跑一遍才会暴露：

| 编号 | 问题 | 影响 | 修复 |
| --- | --- | --- | --- |
| LIVE-01 | 未配置 key 时仍走真实模型 | 演示时每条需求都直接失败，而 README 声称"无需 key 也能体验" | `offline=None` 时自动判断并降级为离线解析器，页面显示离线横幅 |
| LIVE-02 | 离线模型不读取输入（写死 50 箱） | 演示脚本要求的"3000 箱触发审批"永远不会发生，第三段演示直接哑火 | 改为正则规则解析器，真正读取数量、单位、成本中心、物料 |
| LIVE-03 | 解析阶段未纳入重试，SDK 连接异常未归类为可重试 | 一次网络抖动就让任务失败 | 模型调用与 JSON 校验合并进同一个可重试单元；按类名 MRO 识别 `APIConnectionError` 等 SDK 异常 |
| LIVE-04 | 真实模型返回 `AIMessage`，而测试替身返回字符串 | `json.loads(AIMessage)` 直接抛 `TypeError`，代码只对替身有效 | 新增 `response_text()` 统一处理 AIMessage / 内容块 / ```json 围栏；**测试替身一并改为返回 AIMessage** |
| LIVE-05 | 物料名匹配过于脆弱 | 模型把"A4 纸"写成"A4纸"或"A4复印纸"时匹配不到主数据，流程反复要求用户澄清 | 归一化（去空白转小写）+ 关键词全覆盖匹配，兼容 SKU 直查 |

**其中 LIVE-04 是最值得记住的一条：** 测试替身与真实对象的返回类型不一致，会让整套测试在错误的前提上全绿。修复方式不是只改代码去兼容，而是同时把替身改成与真实一致的类型，让测试重新具备发现这类问题的能力。同类问题在 LIVE-02 上重复出现——离线实现"不看输入"，使得所有离线测试都通过而演示完全失效。

### 仍未解决 / 待改进

1. **`expected_date` 未按技能要求转换为 ISO 日期**：真实模型对"下周一前到货"返回字面量 `"下周一"`，而技能文件明确要求换算成具体日期。当前不影响流程（该字段可选），但属于模型未遵守技能指令的证据，需要更强的输出约束或后置校验。
2. **token 记账未接入真实用量**：`token_usage` 只统计摘要中间件的估算值，没有采集模型 API 返回的真实 token 数，因此"token 峰值 43"这个数字不能代表真实消耗。
3. **生产路径未使用框架的委派机制**：`create_deep_agent` 的子 Agent 委派能力已在冒烟脚本中验证可用，但生产流程中主 Agent 是通过状态机阶段**以确定性函数调用**子 Agent 的（见 ADR-002）。也就是说 `agent_delegation` 事件目前是对状态机行为的记录，而不是框架 `task` 工具的真实调用链。这一点必须在面试中如实说明，或后续改造为真实委派，不能含糊其辞。

> **第 3 项已于 D-011 改造完成，不再是遗留项。**

---

## D-011 子 Agent 改为框架真实委派（2026-09-17）

### 改造内容

此前生产流程里主 Agent 以确定性函数调用子 Agent，`agent_delegation` 事件只是状态机的记账。
现在改为真正的框架委派，落地方式如下：

1. **主 Agent 运行在 `create_deep_agent` 构造的图上**，通过模型自己决定调用 `task` 工具把工作交给子 Agent（`agents/delegation.py`）。
2. **子 Agent 的能力以零参数工具形式暴露**（`qualification_query` / `quote_query` / `order_draft`）。工具从当前任务上下文读取参数、调用确定性函数、把结构化结果写回上下文。模型负责"决定调用哪个工具"，不负责计算金额或判断资质——ADR-002 的确定性原则保持不变。
3. **事件来自真实轨迹**：`delegation_result` 事件的 `mode` 字段标明本次委派是 `framework`（模型真的调用了 `task`）还是 `fallback`（模型没委派，系统降级为直接执行并写明原因）。降级绝不伪装成成功。
4. **离线模式与真实模式走同一条代码路径**：`OfflineChatModel` 是合规的 `BaseChatModel`，能参与框架的 Agent 循环并发出 `task` 工具调用。测试替身直接复用它，因此测试覆盖的正是生产代码。

### 真机验证结果

```
state = COMPLETED
委派模式 = ['framework', 'framework', 'framework']
结构化 = {"material_name": "A4 纸", "quantity": 50, "unit": "箱",
          "expected_date": "2026-09-21", "cost_center": "CC-1001"}
token_usage = {"total": 59484, "peak": 4188}
```

三条委派全部为 `framework`，子 Agent 的工具调用以自己的身份出现在事件流中。

### 顺带修复的两项

| 项 | 修复前 | 修复后 |
| --- | --- | --- |
| `expected_date` | 模型原样返回"下周一" | 新增 `agents/dates.py`，用确定性规则把中文相对日期换算为 ISO（`下周一` → `2026-09-21`），模型给不出 ISO 时由代码兜底 |
| token 记账 | 只统计摘要中间件的估算值（峰值 43） | 新增 `middleware/token_usage.py`，通过 LangChain 回调采集每次模型调用的真实 `usage_metadata`；离线模型无用量时不记录，不造假数据 |

**关于真实 token 用量值得注意：** 单个采购任务消耗约 5.9 万 token（峰值单次调用 4188），
主要来自框架自身的系统提示、技能索引与子 Agent 提示词。这个数字比"上下文占用降低 70%"更
值得在面试里讲——它是真实开销，也说明多 Agent 架构的提示词成本并不便宜，属于可量化的取舍。

### 本次改造中踩到的坑

1. **测试替身是鸭子类型对象**：`create_deep_agent` 需要真正的 `BaseChatModel`，替身必须实现 `bind_tools` 并参与 Agent 循环，否则只能验证到"函数被调用"这一层。
2. **角色识别不能靠整段提示匹配**：系统提示里列出了全部子 Agent 的职责说明，在整段提示里扫关键词会把委派目标判错，必须只看"当前这条指令"。
3. **提示词与检测标记必须一致**：提示词写的是"采购**的**协调者"，而检测用的是"采购协调者"，一个"的"字就让整条委派链路失效。这类脆弱字符串匹配是隐患，已改为显式角色标记。

### 改造后的真实模型全量评测（30 条用例）

| 指标 | 改造前（直接函数调用） | 改造后（框架委派） |
| --- | --- | --- |
| 成功率 | 100%（30/30） | 100%（30/30） |
| 人工介入率 | 26.7% | 26.7% |
| 平均单任务耗时 | 1.24 s | 28.1 s |
| 框架委派 / 降级 | 不适用（非真实委派） | **90 / 0**（全部走框架，零降级） |
| 每任务 token 总量 | 未采集 | 均值 57,863（中位数 58,378，最大 62,170） |
| 单次调用峰值 | 未采集 | 均值 4,056，最大 4,274 |

**结论：** 框架委派在真实模型下稳定可用（90 次委派零降级），代价是每任务约 7 次模型调用、
约 28 秒与约 5.8 万 token。这个取舍必须在面试中主动说明：真实委派换来了架构与实现的一致性，
但如果目标是低延迟低成本，确定性函数调用是更优选择——两种方案本项目的代码都保留着
（`mode` 字段区分），可以现场对比。

评测报告已把 `delegation_framework` / `delegation_fallback` / `token_total_mean` 固化为常规字段，
后续任何一次评测都会自动暴露委派降级与 token 成本变化。

---

## D-012 技能加载状态改为按任务隔离（2026-09-17）

**问题：** `SkillRegistry` 的 `loaded_names` 是进程级共享状态。改造为真实委派后，
`_load_skill` 依据它判断"是否已加载"，导致并发跑第二个任务时不会发出 `skill_loaded` 事件，
页面会把本已加载的技能错误显示成"仅描述"。

**修复：** 技能加载状态改为挂在任务上下文（`TaskContext.loaded_skills`），并随流程上下文
在阶段之间传递；注册表只负责缓存技能正文，不再承担"是否已对某任务加载"的判断。

**验证：** 连续跑两个任务，两者都完整记录了四个技能的加载事件（`tests/test_coordinator.py::test_each_task_records_its_own_skill_events`）；真机连续两个任务也各自返回 4 个已加载技能。

**同时修复的展示问题：** 时间线缺少 `delegation_result` 的中文文案，会直接显示英文事件名。
现已区分显示"框架委派成功"与"未委派，降级为直接执行（原因）"——委派与降级在界面上必须一眼可辨。
