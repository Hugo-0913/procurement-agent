const TASK_ID = window.TASK_ID;
const STAGES = [
  { key: "PARSING", label: "需求解析" },
  { key: "QUALIFYING", label: "资质核验" },
  { key: "SOURCING", label: "比价分析" },
  { key: "AWAITING_APPROVAL", label: "订单审批" },
  { key: "COMPLETED", label: "完成" },
];
const STAGE_ORDER = [
  "PENDING", "PARSING", "AWAITING_CLARIFICATION", "QUALIFYING", "SOURCING", "ORDER_DRAFTING",
  "AWAITING_APPROVAL", "ORDERED", "COMPLETED",
];
const STATE_CLASS = {
  AWAITING_APPROVAL: "orange", REVISION_REQUIRED: "orange",
  AWAITING_CLARIFICATION: "orange",
  ORDERED: "green", COMPLETED: "green", FAILED: "red",
};

let events = [];
let lastSeq = 0;
let started = Date.now();

// 耗时口径：任务结束后停在完成时间上，不再跟着墙钟继续涨。
// 早期只用 Date.now() - created_at，导致完成的任务一直显示"已耗时"并持续增加。
const TERMINAL_STATES = new Set(["COMPLETED", "FAILED"]);

function elapsedInfo(detail) {
  const start = Date.parse(detail.created_at);
  if (Number.isNaN(start)) return { seconds: 0, finished: false };
  // 终态优先用 finished_at；老记录缺这个字段时退到 updated_at，避免历史任务永远在涨
  const endSource =
    detail.finished_at || (TERMINAL_STATES.has(detail.state) ? detail.updated_at : null);
  const end = endSource ? Date.parse(endSource) : NaN;
  if (!Number.isNaN(end)) {
    return { seconds: Math.max(0, Math.floor((end - start) / 1000)), finished: true };
  }
  return { seconds: Math.max(0, Math.floor((Date.now() - start) / 1000)), finished: false };
}

function renderStageBar(detail) {
  // 等待澄清时视觉上仍停留在"需求解析"这一步
  const effectiveState = detail.state === "AWAITING_CLARIFICATION" ? "PARSING" : detail.state;
  const currentIndex = STAGE_ORDER.indexOf(effectiveState);
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

  const elapsed = elapsedInfo(detail);
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
     <span class="hint">${elapsed.finished ? "总耗时" : "已耗时"} ${elapsed.seconds}s</span>
     <span class="hint">token ${(detail.token_usage || {}).total || 0}</span>`;
}

function renderLeft(detail) {
  document.getElementById("request-text").textContent = detail.request_text;
  const structured = detail.structured_request || {};
  const items = detail.request_items || [];
  let structuredHtml = "";
  if (items.length) {
    structuredHtml =
      `<tr><td>物料</td><td>${items.length} 种</td></tr>` +
      items
        .map(
          (item) =>
            `<tr><td>· ${item.material_name}</td><td>${item.quantity} ${item.unit || ""}</td></tr>`
        )
        .join("");
  }
  structuredHtml += Object.keys(structured).length
    ? Object.entries(structured)
        .filter(([k]) => k !== "items")
        .map(([k, v]) => `<tr><td>${k}</td><td>${v ?? "-"}</td></tr>`)
        .join("")
    : items.length
    ? ""
    : '<tr><td colspan="2" class="hint">尚未解析</td></tr>';
  document.getElementById("structured").innerHTML = structuredHtml;
  // 记忆全文放折叠区，默认只露一行摘要，避免左栏被大段文字占满
  const memory = detail.memory_block || "";
  document.getElementById("memory-block").textContent = memory;
  const firstLine = memory.split("\n")[0] || "";
  document.getElementById("memory-summary").textContent = memory
    ? firstLine.length > 44
      ? firstLine.slice(0, 44) + "…"
      : firstLine
    : "本次任务未加载记忆";

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
  } else {
    const card = document.getElementById("approval-card");
    if (card) card.remove();
  }
  if (detail.pending_clarification) {
    renderClarification(detail, () => refresh());
  } else {
    const card = document.getElementById("clarify-card");
    if (card) card.remove();
  }
}

function renderClarification(detail, onDone) {
  // 卡片已经存在时直接返回：页面每 5 秒刷新一次，重建会清空用户正在输入的内容
  if (document.getElementById("clarify-card")) return;
  const pending = detail.pending_clarification;
  if (!pending) return;

  const card = document.createElement("div");
  card.className = "clarify-card";
  card.id = "clarify-card";
  card.innerHTML = `
    <div class="card-head"><span class="badge orange">等待补充信息</span></div>
    <div class="small">${pending.question}</div>
    <textarea id="clarify-answer" rows="2" placeholder="例如：50 箱"></textarea>
    <div class="row">
      <button id="btn-clarify">提交补充信息</button>
      <span id="clarify-hint" class="hint"></span>
    </div>`;
  const host = document.getElementById("action-cards");
  if (!host) return;
  host.appendChild(card);

  document.getElementById("btn-clarify").onclick = async () => {
    const answer = document.getElementById("clarify-answer").value.trim();
    const hint = document.getElementById("clarify-hint");
    if (!answer) {
      hint.textContent = "请填写补充信息";
      return;
    }
    hint.textContent = "提交中…";
    const res = await fetch(`/api/tasks/${detail.id}/clarification`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ answer }),
    });
    if (!res.ok) {
      hint.textContent = "提交失败：" + res.status;
      return;
    }
    card.remove();
    onDone();
  };
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
