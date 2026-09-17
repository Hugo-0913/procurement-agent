let currentTab = "suppliers";

async function loadData() {
  const res = await fetch(`/api/${currentTab}`);
  const rows = await res.json();
  const root = document.getElementById("data-table");
  if (!rows.length) {
    root.innerHTML = '<p class="hint">暂无数据</p>';
    return;
  }
  if (currentTab === "suppliers") {
    root.innerHTML = `<table class="data"><tr><th>编码</th><th>名称</th><th>等级</th><th>资质到期</th><th>状态</th></tr>` +
      rows.map((r) => `<tr class="${r.blacklisted ? "blacklisted" : r.expiring_soon ? "expiring" : ""}">
        <td>${r.code}</td><td>${r.name}</td><td>${r.tier}</td><td>${r.expires_at || "-"}</td>
        <td>${r.blacklisted ? "黑名单" : r.expiring_soon ? "资质临期" : "正常"}</td></tr>`).join("") +
      `</table>`;
  } else if (currentTab === "quotes") {
    root.innerHTML = `<table class="data"><tr><th>供应商</th><th>单价</th><th>运费</th><th>交期</th><th>有效期</th></tr>` +
      rows.map((r) => `<tr><td>${r.supplier_name}</td><td>¥${r.unit_price.toFixed(2)}</td>
        <td>¥${r.freight.toFixed(2)}</td><td>${r.lead_days} 天</td><td>${r.valid_until}</td></tr>`).join("") +
      `</table>`;
  } else {
    root.innerHTML = `<table class="data"><tr><th>订单号</th><th>供应商</th><th>数量</th><th>总额</th><th>状态</th><th>任务</th></tr>` +
      rows.map((r) => `<tr data-task="${r.task_id}"><td>#${r.id}</td><td>${r.supplier_name}</td>
        <td>${r.quantity}</td><td>¥${r.total_amount.toFixed(2)}</td><td>${r.status}</td>
        <td><a href="/tasks/${r.task_id}">查看</a></td></tr>`).join("") +
      `</table>`;
  }
}

async function loadFaults() {
  const res = await fetch("/api/faults");
  const data = await res.json();
  document.getElementById("fault-list").innerHTML = data.flags
    .map(
      (f) => `<label class="switch">
        <input type="checkbox" data-flag="${f.flag}" ${f.enabled ? "checked" : ""}>
        <span>${f.label}</span>${f.enabled ? '<span class="badge orange">已开启</span>' : ""}
      </label>`
    )
    .join("");
  document.querySelectorAll("#fault-list input").forEach((box) => {
    box.onchange = async () => {
      await fetch("/api/faults", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ flag: box.dataset.flag, enabled: box.checked }),
      });
      loadFaults();
      loadData();
    };
  });
}

function bindTabs() {
  ["suppliers", "quotes", "orders"].forEach((tab) => {
    document.getElementById("tab-" + tab).onclick = () => {
      currentTab = tab;
      ["suppliers", "quotes", "orders"].forEach((t) =>
        document.getElementById("tab-" + t).classList.toggle("active", t === tab)
      );
      loadData();
    };
  });
}

bindTabs();
loadData();
loadFaults();

