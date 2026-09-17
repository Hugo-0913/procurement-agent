const MIDDLEWARE_AGENTS = new Set(["context_summarizer", "policy_engine", "policy_guard", "human"]);

function renderTimeline(events) {
  const root = document.getElementById("timeline");
  const agentFilter = document.getElementById("filter-agent").value;
  const typeFilter = document.getElementById("filter-type").value;

  const rows = events.filter(
    (e) => (!agentFilter || e.agent === agentFilter) && (!typeFilter || e.event_type === typeFilter)
  );
  root.innerHTML = rows
    .map((e) => {
      const time = (e.created_at || "").split("T")[1] || "";
      const tag = MIDDLEWARE_AGENTS.has(e.agent)
        ? `<span class="tag mid-tag">中间件·${e.agent}</span>`
        : e.event_type === "skill_loaded"
        ? '<span class="tag">技能</span>'
        : `<span class="tag">${e.agent}</span>`;
      return `<div class="tl-item" data-seq="${e.seq}">[${time}] ${tag}${describe(e)}</div>`;
    })
    .join("") || '<p class="hint">暂无事件</p>';

  root.querySelectorAll(".tl-item").forEach((el) => {
    el.onclick = () => {
      const payload = rows.find((e) => e.seq === Number(el.dataset.seq));
      if (payload) {
        alert(JSON.stringify(payload.payload, null, 2));
      }
    };
  });
}

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

