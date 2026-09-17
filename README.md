# 耗材采购自动化 Agent 系统

基于 DeepAgents 的多 Agent 采购流程自动化系统：主 Agent 委派三类子 Agent，完成「需求输入 → 资质核验 → 比价分析 → 订单审批 → 订单生成」的完整闭环，并提供本地 Web 界面实时观察委派过程、审批拦截与异常重试。

需求范围见 [PRD.md](PRD.md)，实施计划见 [plan.md](plan.md)，技术方案见 [docs/architecture.md](docs/architecture.md)，关键决策见 [docs/decision-log.md](docs/decision-log.md)。

## 架构

```mermaid
flowchart TD
    A[Web 层 FastAPI + 原生 JS + SSE] --> B[编排层 LangGraph 状态机 + SqliteSaver]
    B --> C[智能体层 DeepAgents 主 Agent + 3 子 Agent]
    C --> D[治理层 策略守卫 / 上下文摘要 / 反思重试]
    D --> E[能力层 技能 / 虚拟文件系统 / 记忆 / mock ERP / 沙箱]
    E --> F[(SQLite)]
```

设计要点：状态机在外层作为**唯一状态源**，让长任务可中断、可恢复、可在页面上渲染；业务判定（资质筛选、成本计算、阈值判断）实现为**确定性纯函数**，模型只负责需求解析与自然语言说明，从而把不可靠的部分压到最小。

## 快速开始

```bash
# 1. 创建虚拟环境并安装依赖
python -m venv .venv
.venv\Scripts\python.exe -m pip install -e ".[dev]"

# 2. 配置模型（真实运行时需要）
copy .env.example .env
# 编辑 .env，填入 DEEPSEEK_API_KEY

# 3. 启动 Web 服务
.venv\Scripts\python.exe -m uvicorn procurement_agent.web.app:create_app --factory --port 8000
```

打开 http://127.0.0.1:8000 即可看到任务看板页。

**模型模式是自动判断的**：未配置 `DEEPSEEK_API_KEY` 时，应用会自动切换到内置离线解析器（正则规则，不联网），
页面顶部显示橙色"离线演示模式"横幅，全流程仍可完整跑通（不联网）。配置 key 后重启即用真实
模型，横幅消失。想强制离线可用 `.venv\Scripts\python.exe -m uvicorn procurement_agent.web.app:create_demo_app --factory --port 8000`。

评测与测试全程离线运行，不需要任何 API key。

## 目录结构

```
config/            agents.yaml（Agent 定义）、procurement.yaml（阈值等业务参数）
skills/            四类领域技能，SKILL.md + frontmatter，按需加载
src/procurement_agent/
  agents/          主 Agent 编排、三个子 Agent、模型工厂、离线模型
  state/           任务状态机、事件存储、LangGraph 流程图
  sandbox/         策略引擎（层一）与受限执行器（层二）
  middleware/      上下文摘要、策略守卫、反思重试
  memory/          采购偏好与供应商历史
  erp/             mock ERP 仓储与故障注入
  web/             FastAPI 接口、SSE 推送与四个页面
  eval/            30 条固定用例集与评测运行器
tests/             144 项测试
docs/              架构、安全、决策记录、演示脚本
```

## 演示路径

1. 任务看板页点「填入示例需求」→ 提交，进入采购执行页。
2. 执行页观察：左侧技能标签从「仅描述」逐个变为「已加载全文」；中间任务树展开三类子 Agent 与其工具调用；右侧时间线实时滚动，中间件动作单独标记。
3. 打开数据台，开启「让供应商 B 资质过期」，回到看板重新提交，观察系统淘汰该供应商并在比价结论中说明改选理由。
4. 提交 `采购 3000 箱 A4 纸`，金额超阈值触发审批卡片，现场批准或驳回（驳回会回退到比价阶段重跑）。
5. 打开评测页，点「运行评测」，查看指标与失败用例。

详细分镜与讲解要点见 [docs/demo-script.md](docs/demo-script.md)。

## 评测

```bash
.venv\Scripts\python.exe -m procurement_agent.eval.runner --out eval_results/latest.json
```

30 条固定用例覆盖正常路径 12 条、单故障 15 条、组合故障 3 条；每条用例使用独立数据库与固定脚本模型，结果可复现。当前结果（离线确定性模式）：

| 指标 | 数值 |
| --- | --- |
| 用例总数 | 30 |
| 成功率 | 100%（30/30） |
| 人工介入率 | 26.7%（8 条审批用例） |
| 平均耗时 | 约 153 ms（离线模式，不含真实模型时延） |
| 上下文压缩率 | 87.6%（4670 → 578 token，12 段工具返回的长对话基准） |
| 自动化测试 | 144 项全部通过 |

**指标口径说明：** 以上数字由离线确定性模式产出，用于验证流程编排与治理逻辑的正确性与可复现性，不代表真实模型下的端到端时延与成功率。真实模型下的指标需要配置 `DEEPSEEK_API_KEY` 后单独跑一遍，两者必须分开陈述，不可混用。

## v1 范围

已实现：状态机与持久化审批中断、四类技能渐进式加载、三类子 Agent 委派、虚拟文件系统与路径逃逸防护、持久化记忆、上下文摘要、双层沙箱、反思重试、四个页面、可复现评测。

明确不做：真实 ERP 对接、容器级隔离、多租户与 SSO、支付/收货/入库/对账、寻源与招投标、技能热插拔、向量检索记忆、并发多任务、多模型路由、移动端适配、性能压测。详见 PRD 3.2。
