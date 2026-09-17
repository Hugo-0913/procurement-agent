const TASK_ID = window.TASK_ID;
const STAGES = [
  { key: "PARSING", label: "需求解析" },
  { key: "QUALIFYING", label: "资质核验" },
  { key: "SOURCING", label: "比价分析" },
  { key: "AWAITING_APPROVAL", label: "订单审批" },
  { key: "COMPLETED", label: "完成" },
];
const STAGE_ORDER = [
  "PENDING", "PARSING", "QUALIFYING", "SOURCING", "ORDER_DRAFTING",
  "AWAITING_APPROVAL", "ORDERED", "COMPLETED",
];
const STATE_CLASS = {
  AWAITING_APPROVAL: "orange", REVISION_REQUIRED: "orange",
  ORDERED: "green", COMPLETED: "green", FAILED: "red",
};

let events = [];
let lastSeq = 0;
let started = Date.now();

function renderStageBar(detail) {
  const currentIndex = STAGE_ORDER.indexOf(detail.state);
  const rejected = detail.events.some(
    (e) => e.event_type === "stage_change" && e.payload.to === "REVISION_REQUIRED"
  );
  const nodes = STAGES.map((stage) => {
    const stageIndex = STAGE_ORDER.indexOf(stage.key);
    let cls = "stage";
    if (detail.state === "FAILED") cls += " rejected";
    else if (stage.key === "AWAITING_APPROVAL" && rejected) cls += " rejected";
    else if (currentIndex > stageIndex) cls += " done";
    else if (currentIndex === stageIndex) cls += " current";
    return `<span class="${cls}">${stage.label}</span>`;
  }).join('<span class="hint">→</span>');

  const elapsed = Math.floor((Date.now() - Date.parse(detail.created_at)) / 1000);
  const badge = STATE_CLASS[detail.state] || "blue";
  const bar = document.getElementById("stage-bar");
  const stages = bar.querySelectorAll(".stage");
  stages.forEach((el, index) => {
    const cls = ["stage"];
    if (detail.state === "FAILED") cls.push("rejected");
    else if (currentIndex > index) cls.push("done");
    else if (currentIndex === index) cls.push("current");
    if (rejected && index === 3) cls.push("rejected");
    el.className = cls.join(" ");
  });
  bar.querySelectorAll(".arrow").forEach((el) => el.remove());
  document.getElementById("stage-meta").innerHTML =
    `<span class="badge ${badge}">${detail.state_label}</span>
     <span class="hint">已耗时 ${elapsed}s</span>
     <span class="hint">token ${(detail.token_usage || {}).total || 0}</span>`;
}

function renderLeft(detail) {
  document.getElementById("request-text").textContent = detail.request_text;
  const structured = detail.structured_request || {};
  document.getElementById("structured").innerHTML = Object.keys(structured).length
    ? Object.entries(structured)
        .map(([k, v]) => `<tr><td>${k}</td><td>${v ?? "-"}</td></tr>`)
        .join("")
    : '<tr><td colspan="2" class="hint">尚未解析</td></tr>';
  document.getElementById("memory-block").textContent = detail.memory_block || "";

  document.getElementById("skill-status").innerHTML = [
    ...(detail.loaded_skills || []).map(
      (s) => `<span class="tag-skill loaded" title="已加载全文">${s}</span>`
    ),
    ...(detail.metadata_only_skills || []).map(
      (s) => `<span class="tag-skill metadata-only" title="仅加载了描述，正文未加载">${s}</span>`
    ),
  ].join("");
}

function renderResult(detail) {
  const card = document.getElementById("result-card");
  if (detail.state !== "COMPLETED") {
    card.classList.add("hidden");
    return;
  }
  const comparisons = (detail.sourcing || {}).comparisons || [];
  const draft = comparisons.length
    ? comparisons.find((c) => c.code === (detail.sourcing.recommended || {}).code)
    : null;
  const highest = comparisons.length
    ? Math.max(...comparisons.map((c) => c.total))
    : null;
  const saved = draft && highest ? (highest - draft.total).toFixed(2) : "-";
  card.classList.remove("hidden");
  card.innerHTML = `
    <strong>采购完成</strong>
    <div class="small" style="margin-top:6px">
      订单号 #${detail.order_id ?? "-"} · 供应商 ${draft ? draft.name : "-"} ·
      总额 ¥${draft ? draft.total.toFixed(2) : "-"} ·
      相比最高报价节省 ¥${saved} ·
      人工介入 ${detail.human_interventions} 次
    </div>`;
}

function renderAll(detail) {
  renderStageBar(detail);
  renderLeft(detail);
  renderResult(detail);
  fillFilters(events);
  renderTree(events);
  renderTimeline(events);
  if (detail.pending_approval) {
    renderApproval(detail, () => refresh());
  }
}

async function refresh() {
  const res = await fetch(`/api/tasks/${TASK_ID}`);
  if (!res.ok) return;
  const detail = await res.json();
  events = detail.events;
  lastSeq = events.length ? events[events.length - 1].seq : 0;
  renderAll(detail);
}

function connect() {
  const source = new EventSource(`/api/tasks/${TASK_ID}/events?after_seq=${lastSeq}`);
  source.onmessage = async () => {
    source.close();
    await refresh();
    connect();
  };
  source.onerror = () => {
    source.close();
    setTimeout(connect, 2000);
  };
}

window.addEventListener("step-selected", (e) => highlightTimeline(e.detail.seq));
document.getElementById("filter-agent").onchange = () => renderTimeline(events);
document.getElementById("filter-type").onchange = () => renderTimeline(events);

refresh().then(connect);
setInterval(refresh, 5000);
