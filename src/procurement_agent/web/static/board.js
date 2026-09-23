/* 任务看板：两种下单方式 + 历史任务列表
   1) 选着买——从采购目录里挑物料和数量，走确定性路径，不调用模型
   2) 说着买——自然语言需求，交给模型解析
   两条路都保留，是为了让「受约束输入」和「自由输入」的差异可被直接对比。 */

const SAMPLE = "采购 50 箱 一次性无菌注射器，下周一前到货，成本中心 CC-1001";

const STATE_CLASS = {
  PENDING: "blue", PARSING: "blue", QUALIFYING: "blue", SOURCING: "blue",
  ORDER_DRAFTING: "blue", AWAITING_APPROVAL: "orange", REVISION_REQUIRED: "orange",
  AWAITING_CLARIFICATION: "orange",
  ORDERED: "green", COMPLETED: "green", FAILED: "red",
};

let allTasks = [];
let filter = "";
let materials = [];
let costCenters = [];

// ---------- 历史任务 ----------

function badge(task) {
  const cls = STATE_CLASS[task.state] || "blue";
  return `<span class="badge ${cls}">${task.state_label}</span>`;
}

function render() {
  const list = document.getElementById("task-list");
  const rows = allTasks.filter((t) => {
    if (!filter) return true;
    if (filter === "RUNNING") {
      return !["COMPLETED", "FAILED", "AWAITING_APPROVAL", "AWAITING_CLARIFICATION"].includes(t.state);
    }
    return t.state === filter;
  });
  if (!rows.length) {
    list.innerHTML = '<p class="empty">还没有采购记录。上面提一条试试。</p>';
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

// ---------- 选着买 ----------

function materialOptions(selectedId) {
  return materials
    .map(
      (m) =>
        `<option value="${m.id}" ${String(m.id) === String(selectedId) ? "selected" : ""}>` +
        `${m.name}（${m.spec}）</option>`
    )
    .join("");
}

function addRow(materialId) {
  const tbody = document.getElementById("item-rows");
  const tr = document.createElement("tr");
  tr.innerHTML = `
    <td><select class="row-material">${materialOptions(materialId)}</select></td>
    <td><input class="row-quantity" type="number" min="1" step="1" value="50"></td>
    <td class="unit"></td>
    <td><button class="row-remove" type="button">移除</button></td>`;
  tbody.appendChild(tr);

  const select = tr.querySelector(".row-material");
  const unitCell = tr.querySelector(".unit");
  const syncUnit = () => {
    const material = materials.find((m) => String(m.id) === select.value);
    unitCell.textContent = material ? material.unit : "-";
  };
  select.onchange = syncUnit;
  syncUnit();
  tr.querySelector(".row-remove").onclick = () => {
    if (document.querySelectorAll("#item-rows tr").length === 1) return;
    tr.remove();
  };
}

function collectSelection() {
  const items = [];
  document.querySelectorAll("#item-rows tr").forEach((tr) => {
    const materialId = tr.querySelector(".row-material").value;
    const quantity = parseInt(tr.querySelector(".row-quantity").value, 10);
    items.push({ material_id: Number(materialId), quantity: quantity });
  });
  return items;
}

async function submitSelection() {
  const hint = document.getElementById("pick-hint");
  const items = collectSelection();
  if (items.some((i) => !i.material_id || !i.quantity || i.quantity <= 0)) {
    hint.textContent = "每一行都要选物料，数量要大于 0";
    return;
  }
  hint.textContent = "提交中…";
  const res = await fetch("/api/tasks", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      items,
      cost_center: document.getElementById("cost-center").value,
      expected_date: document.getElementById("expected-date").value || null,
    }),
  });
  if (!res.ok) {
    const detail = await res.json().catch(() => ({}));
    hint.textContent = "提交失败：" + (detail.detail?.[0]?.msg || res.status);
    return;
  }
  const data = await res.json();
  window.location.href = "/tasks/" + data.task_id;
}

async function loadCatalog() {
  materials = await (await fetch("/api/materials")).json();
  costCenters = await (await fetch("/api/cost-centers")).json();
  const select = document.getElementById("cost-center");
  select.innerHTML = costCenters
    .map((c) => `<option value="${c.code}">${c.name}（${c.code}）</option>`)
    .join("");
  document.getElementById("item-rows").innerHTML = "";
  addRow(materials[0]?.id);
}

// ---------- 说着买 ----------

async function submitText() {
  const text = document.getElementById("request-text").value.trim();
  const hint = document.getElementById("submit-hint");
  if (!text) {
    hint.textContent = "请先写下你要采购的东西";
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
}

// ---------- 绑定 ----------

document.querySelectorAll("#entry-tabs .chip").forEach((chip) => {
  chip.onclick = () => {
    document.querySelectorAll("#entry-tabs .chip").forEach((c) => c.classList.remove("active"));
    chip.classList.add("active");
    const pick = chip.dataset.entry === "pick";
    document.getElementById("entry-pick").classList.toggle("hidden", !pick);
    document.getElementById("entry-type").classList.toggle("hidden", pick);
  };
});

document.getElementById("btn-add-row").onclick = () => addRow(materials[0]?.id);
document.getElementById("btn-submit-pick").onclick = submitSelection;
document.getElementById("btn-sample").onclick = () => {
  document.getElementById("request-text").value = SAMPLE;
};
document.getElementById("btn-submit").onclick = submitText;

document.querySelectorAll("#status-filters .chip").forEach((chip) => {
  chip.onclick = () => {
    document.querySelectorAll("#status-filters .chip").forEach((c) => c.classList.remove("active"));
    chip.classList.add("active");
    filter = chip.dataset.state;
    render();
  };
});

loadCatalog().then(() => {
  loadTasks();
  setInterval(loadTasks, 4000);
});

