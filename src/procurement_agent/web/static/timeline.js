const MIDDLEWARE_AGENTS = new Set(["context_summarizer", "policy_engine", "policy_guard"]);

// 默认只看关键事件：阶段推进、委派与降级、审批与澄清、重试与错误、任务结束。
// 工具调用/返回、技能加载、记忆读写这些工程细节默认隐藏——它们是"怎么做到的"，
// 不是"发生了什么"，需要时用右上角的「全部事件」展开。
const KEY_EVENT_TYPES = new Set([
  "stage_change",
  "agent_delegation",
  "delegation_result",
  "approval_requested",
  "approval_decided",
  "clarification_requested",
  "clarification_answered",
  "policy_denied",
  "retry",
  "error",
  "task_finished",
]);

let timelineScope = "key";
let latestEvents = [];

const TIMELINE_TONE = {
  stage_change: "ok",
  task_finished: "ok",
  agent_delegation: "ok",
  delegation_result: "ok",
  policy_denied: "warn",
  approval_requested: "warn",
  clarification_requested: "warn",
  retry: "warn",
  error: "error",
  context_summarized: "middleware",
  memory_loaded: "middleware",
  memory_written: "middleware",
};

function renderTimeline(events) {
  const root = document.getElementById("timeline");
  latestEvents = events;
  const agentFilter = document.getElementById("filter-agent").value;
  const typeFilter = document.getElementById("filter-type").value;

  const inScope = events.filter(
    (e) => timelineScope === "all" || KEY_EVENT_TYPES.has(e.event_type)
  );
  const hidden = events.length - inScope.length;
  const rows = inScope.filter(
    (e) =>
      (!agentFilter || e.agent === agentFilter) &&
      (!typeFilter || e.event_type === typeFilter)
  );
  const note = document.getElementById("timeline-note");
  if (note) {
    note.textContent =
      timelineScope === "key" && hidden > 0
        ? `已折叠 ${hidden} 条工程细节事件（工具调用、技能加载、记忆读写），切到「全部事件」可查看`
        : "";
  }
  root.innerHTML = rows
    .map((e) => {
      const time = (e.created_at || "").split("T")[1] || "";
      const tag = MIDDLEWARE_AGENTS.has(e.agent)
        ? `<span class="tag mid-tag">中间件·${e.agent}</span>`
        : e.event_type === "skill_loaded"
        ? '<span class="tag">技能</span>'
        : `<span class="tag">${e.agent}</span>`;
      const tone = TIMELINE_TONE[e.event_type] || "tool";
      return `<div class="tl-item ${tone}" data-seq="${e.seq}">
        <span class="tl-time">${time}</span>
        <span class="tl-body">${tag}${describe(e)}</span>
      </div>`;
    })
    .join("") || '<p class="empty">暂无事件</p>';

  root.querySelectorAll(".tl-item").forEach((el) => {
    el.onclick = () => {
      const payload = rows.find((e) => e.seq === Number(el.dataset.seq));
      if (payload) {
        alert(JSON.stringify(payload.payload, null, 2));
      }
    };
  });
}

function setTimelineScope(scope) {
  timelineScope = scope === "all" ? "all" : "key";
  const keyBtn = document.getElementById("tl-key");
  const allBtn = document.getElementById("tl-all");
  if (keyBtn) keyBtn.classList.toggle("active", timelineScope === "key");
  if (allBtn) allBtn.classList.toggle("active", timelineScope === "all");
  renderTimeline(latestEvents);
}

function bindTimelineScope() {
  const keyBtn = document.getElementById("tl-key");
  const allBtn = document.getElementById("tl-all");
  if (keyBtn) keyBtn.onclick = () => setTimelineScope("key");
  if (allBtn) allBtn.onclick = () => setTimelineScope("all");
}

bindTimelineScope();

function highlightTimeline(seq) {
  document.querySelectorAll(".tl-item.highlight").forEach((el) => el.classList.remove("highlight"));
  const target = document.querySelector(`.tl-item[data-seq="${seq}"]`);
  if (target) {
    target.classList.add("highlight");
    target.scrollIntoView({ block: "center", behavior: "smooth" });
  }
}

function fillFilters(events) {
  const agentSelect = document.getElementById("filter-agent");
  const typeSelect = document.getElementById("filter-type");
  const agents = [...new Set(events.map((e) => e.agent))];
  const types = [...new Set(events.map((e) => e.event_type))];
  const keepAgent = agentSelect.value;
  const keepType = typeSelect.value;
  agentSelect.innerHTML =
    '<option value="">全部 Agent</option>' +
    agents.map((a) => `<option value="${a}">${a}</option>`).join("");
  typeSelect.innerHTML =
    '<option value="">全部事件</option>' +
    types.map((t) => `<option value="${t}">${t}</option>`).join("");
  agentSelect.value = agents.includes(keepAgent) ? keepAgent : "";
  typeSelect.value = types.includes(keepType) ? keepType : "";
}
