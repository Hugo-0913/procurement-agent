const SAMPLE = "采购 50 箱 A4 纸，下周一前到货，成本中心 CC-1001";
const STATE_CLASS = {
  PENDING: "blue", PARSING: "blue", QUALIFYING: "blue", SOURCING: "blue",
  ORDER_DRAFTING: "blue", AWAITING_APPROVAL: "orange", REVISION_REQUIRED: "orange",
  ORDERED: "green", COMPLETED: "green", FAILED: "red",
};
let allTasks = [];
let filter = "";

function badge(task) {
  const cls = STATE_CLASS[task.state] || "blue";
  return `<span class="badge ${cls}">${task.state_label}</span>`;
}

function render() {
  const list = document.getElementById("task-list");
  const rows = allTasks.filter((t) => {
    if (!filter) return true;
    if (filter === "RUNNING") {
      return !["COMPLETED", "FAILED", "AWAITING_APPROVAL"].includes(t.state);
    }
    return t.state === filter;
  });
  if (!rows.length) {
    list.innerHTML = '<p class="empty">暂无任务。填一条采购需求，或点「填入示例需求」试试。</p>';
    return;
  }
  list.innerHTML = rows
    .map(
      (t) => `<div class="card" data-id="${t.id}" data-tone="${STATE_CLASS[t.state] || "blue"}">
        <div class="card-title">${t.summary}</div>
        <div class="card-meta">
          ${badge(t)}
          <span class="hint">${t.created_at}</span>
          ${t.human_interventions ? `<span class="badge gray">人工介入 ${t.human_interventions} 次</span>` : ""}
        </div>
      </div>`
    )
    .join("");
  list.querySelectorAll(".card").forEach((el) => {
    el.onclick = () => (window.location.href = "/tasks/" + el.dataset.id);
  });
}

async function loadTasks() {
  const res = await fetch("/api/tasks");
  allTasks = await res.json();
  render();
}

document.getElementById("btn-sample").onclick = () => {
  document.getElementById("request-text").value = SAMPLE;
};

document.getElementById("btn-submit").onclick = async () => {
  const text = document.getElementById("request-text").value.trim();
  const hint = document.getElementById("submit-hint");
  if (!text) {
    hint.textContent = "请先填写采购需求";
    return;
  }
  hint.textContent = "提交中…";
  const res = await fetch("/api/tasks", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ request_text: text }),
  });
  if (!res.ok) {
    hint.textContent = "提交失败：" + res.status;
    return;
  }
  const data = await res.json();
  window.location.href = "/tasks/" + data.task_id;
};

document.querySelectorAll("#status-filters .chip").forEach((chip) => {
  chip.onclick = () => {
    document.querySelectorAll("#status-filters .chip").forEach((c) => c.classList.remove("active"));
    chip.classList.add("active");
    filter = chip.dataset.state;
    render();
  };
});

loadTasks();
setInterval(loadTasks, 4000);
