/* 数据台：只回答三个业务问题
   1) 这家供应商能不能供货？不能是因为什么？
   2) 同一种耗材，谁家报价划算？
   3) 我们买到了什么？
   技术字段（证书编号、内部状态码之类）不在这里展示。 */

let currentTab = "suppliers";

function availability(supplier) {
  if (supplier.blacklisted) {
    return { text: "不可供货", tone: "red", reason: "已被列入黑名单" };
  }
  if (supplier.expiring_soon) {
    return { text: "可供货（需审批）", tone: "orange", reason: "经营许可证 30 天内到期" };
  }
  return { text: "可供货", tone: "green", reason: "资质齐全且在有效期内" };
}

async function loadData() {
  const res = await fetch(`/api/${currentTab}`);
  const rows = await res.json();
  const root = document.getElementById("data-table");

  if (!rows.length) {
    root.innerHTML = '<p class="empty">暂无数据</p>';
    return;
  }

  if (currentTab === "suppliers") {
    root.innerHTML =
      `<table class="data"><tr><th>供应商</th><th>等级</th><th>能不能供货</th><th>说明</th><th>资质到期</th></tr>` +
      rows
        .map((r) => {
          const state = availability(r);
          return `<tr class="${r.blacklisted ? "blacklisted" : r.expiring_soon ? "expiring" : ""}">
            <td>${r.name}</td>
            <td>${r.tier} 类</td>
            <td><span class="badge ${state.tone}">${state.text}</span></td>
            <td class="hint">${state.reason}</td>
            <td>${r.expires_at || "-"}</td>
          </tr>`;
        })
        .join("") +
      `</table>`;
    return;
  }

  root.innerHTML =
    `<table class="data"><tr><th>订单号</th><th>物料</th><th>数量</th><th>金额</th><th>供应商</th><th>状态</th><th>操作</th></tr>` +
    rows
      .map(
        (r) => `<tr>
          <td>#${r.id}</td>
          <td>${r.material_name}</td>
          <td>${r.quantity}</td>
          <td>¥${r.total_amount.toFixed(2)}</td>
          <td>${r.supplier_name}</td>
          <td><span class="badge green">已下单</span></td>
          <td><a href="/tasks/${r.task_id}">查看采购过程</a></td>
        </tr>`
      )
      .join("") +
    `</table>`;
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
  ["suppliers", "orders"].forEach((tab) => {
    document.getElementById("tab-" + tab).onclick = () => {
      currentTab = tab;
      ["suppliers", "orders"].forEach((t) =>
        document.getElementById("tab-" + t).classList.toggle("active", t === tab)
      );
      loadData();
    };
  });
}

bindTabs();
loadData();
loadFaults();
