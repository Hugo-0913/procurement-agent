const EVENT_LABELS = {
  stage_change: (p) => `阶段切换 ${p.from} → ${p.to}`,
  agent_delegation: (p) => `委派给 ${p.to}`,
  delegation_result: (p) =>
    p.mode === "framework"
      ? `框架委派成功：${p.to}`
      : `未委派，降级为直接执行：${p.to}${p.reason ? "（" + p.reason + "）" : ""}`,
  clarification_requested: (p) => `需要澄清：${p.question || "缺少必要信息"}`,
  clarification_answered: (p) => `用户补充：${p.answer || ""}`,
  tool_call: (p) => `调用 ${p.tool}`,
  tool_result: (p) => `${p.tool}: ${p.summary || "完成"}`,
  skill_loaded: (p) => `已加载技能 ${p.skill}`,
  policy_denied: (p) => `策略拦截：${p.reason}`,
  retry: (p) => `第 ${p.attempt} 次重试 · 原因：${p.reason}`,
  context_summarized: (p) => `上下文压缩 ${p.before_tokens} → ${p.after_tokens} tokens`,
  approval_requested: () => "请求人工审批",
  approval_decided: (p) => `审批${p.decision === "approve" ? "通过" : p.decision === "reject" ? "驳回" : "要求修改"}`,
  memory_loaded: () => "加载采购偏好记忆",
  memory_written: () => "回写采购记忆",
  error: (p) => `错误：${p.error}`,
  task_finished: () => "任务结束",
};

const STEP_EVENTS = new Set(["tool_call", "tool_result", "retry", "policy_denied"]);

function describe(event) {
  const fn = EVENT_LABELS[event.event_type];
  return fn ? fn(event.payload || {}) : event.event_type;
}

function renderTree(events) {
  const root = document.getElementById("task-tree");
  const delegations = events.filter((e) => e.event_type === "agent_delegation");
  const stepsByAgent = {};
  const pendingByAgent = {};

  events.forEach((e) => {
    const agent = e.agent;
    if (!stepsByAgent[agent]) stepsByAgent[agent] = [];
    if (e.event_type === "tool_call") {
      pendingByAgent[agent] = {
        seq: e.seq,
        name: e.payload.tool,
        status: "running",
        detail: [],
      };
      stepsByAgent[agent].push(pendingByAgent[agent]);
    } else if (STEP_EVENTS.has(e.event_type)) {
      const target = pendingByAgent[agent];
      if (target) {
        if (e.event_type === "tool_result") {
          target.status = "done";
          target.detail.push(describe(e));
        } else if (e.event_type === "retry") {
          target.retries = (target.retries || 0) + 1;
          target.detail.push(describe(e));
        } else if (e.event_type === "policy_denied") {
          target.status = "denied";
          target.detail.push(describe(e));
        }
      }
    }
  });

  const rootSteps = (stepsByAgent["coordinator"] || [])
    .map(renderStep)
    .join("");
  const branches = delegations
    .map((d) => {
      const agent = d.payload.to;
      const steps = (stepsByAgent[agent] || []).map(renderStep).join("") ||
        '<div class="hint">（无工具调用记录）</div>';
      return `<div class="tree-node"><div class="node-head"><span class="tag">子 Agent</span>${agent}</div>${steps}</div>`;
    })
    .join("");

  const otherAgents = Object.keys(stepsByAgent).filter(
    (a) => a !== "coordinator" && !delegations.some((d) => d.payload.to === a)
  );
  const extras = otherAgents
    .map(
      (a) =>
        `<div class="tree-node"><div class="node-head"><span class="tag mid-tag">中间件</span>${a}</div>${
          stepsByAgent[a].map(renderStep).join("")
        }</div>`
    )
    .join("");

  root.innerHTML =
    `<div class="tree-node tree-root"><div class="node-head"><span class="tag">主 Agent</span>coordinator</div>${rootSteps}</div>` +
    branches +
    extras;

  root.querySelectorAll(".step").forEach((el) => {
    el.onclick = () => {
      document.querySelectorAll(".step.selected").forEach((s) => s.classList.remove("selected"));
      el.classList.add("selected");
      window.dispatchEvent(
        new CustomEvent("step-selected", { detail: { seq: Number(el.dataset.seq) } })
      );
    };
  });
}

function renderStep(step) {
  const cls =
    step.status === "denied"
      ? "step denied"
      : step.status === "failed"
      ? "step failed"
      : step.status === "done"
      ? "step done"
      : "step";
  const retry = step.retries ? `<span class="hint">第 ${step.retries + 1} 次重试</span>` : "";
  const flag = step.status === "denied" ? '<span class="hint">等待审批</span>' : "";
  return `<div class="${cls}" data-seq="${step.seq}">
      <span class="step-name">${step.name}</span>${retry}${flag}
      <span class="hint">${step.detail[step.detail.length - 1] || ""}</span>
    </div>`;
}
