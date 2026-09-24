function renderApproval(detail, onDone) {
  // 卡片已存在时不重建，否则会清空审批人正在填写的意见
  if (document.getElementById("approval-card")) return;
  const pending = detail.pending_approval;
  if (!pending) return;

  const draft = pending.order_draft || {};
  const lines = pending.order_lines && pending.order_lines.length
    ? pending.order_lines
    : [draft];
  const rules = (pending.matched_rules || [])
    .map((r) => `<div class="rule">命中规则：${r}</div>`)
    .join("");
  const card = document.createElement("div");
  card.className = "approval-card";
  card.id = "approval-card";
  const lineRows = lines
    .map(
      (line) => `<tr>
        <td>${line.material_name || "-"}</td>
        <td>${line.supplier_name || "-"}</td>
        <td>${line.quantity ?? "-"}</td>
        <td>¥${(line.unit_price ?? 0).toFixed(2)}</td>
        <td>¥${(line.total_amount ?? 0).toFixed(2)}</td>
        <td>${line.lead_days ?? "-"} 天</td>
      </tr>`
    )
    .join("");
  const total = pending.total_amount ?? (draft.total_amount || 0);

  card.innerHTML = `
    <div class="card-head"><span class="badge orange">需要人工审批</span></div>
    ${rules}
    <table class="data" style="margin-top:10px">
      <tr><th>物料</th><th>供应商</th><th>数量</th><th>单价</th><th>小计</th><th>交期</th></tr>
      ${lineRows}
      <tr><td colspan="4"><strong>合计（${lines.length} 行）</strong></td>
          <td colspan="2"><strong>¥${Number(total).toFixed(2)}</strong></td></tr>
    </table>
    <div class="hint" style="margin-top:6px">成本中心：${draft.cost_center || "-"}</div>
    <div class="small" style="margin-top:8px">比价结论：${pending.recommendation_reason || "-"}</div>
    <textarea id="approval-reason" rows="2" placeholder="审批意见（驳回或要求修改时必填）"></textarea>
    <div class="row">
      <button id="btn-approve">批准</button>
      <button id="btn-reject" class="ghost">驳回</button>
      <button id="btn-revise" class="ghost">要求修改</button>
      <span id="approval-hint" class="hint"></span>
    </div>`;
  const host = document.getElementById("action-cards");
  if (!host) return;
  host.appendChild(card);

  const send = async (decision) => {
    const reason = document.getElementById("approval-reason").value.trim();
    const hint = document.getElementById("approval-hint");
    if ((decision === "reject" || decision === "revise") && !reason) {
      hint.textContent = "驳回必须填写理由";
      return;
    }
    const res = await fetch(`/api/tasks/${detail.id}/approval`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ decision, operator: "采购主管", reason }),
    });
    if (!res.ok) {
      hint.textContent = "提交失败：" + res.status;
      return;
    }
    card.remove();
    onDone();
  };

  document.getElementById("btn-approve").onclick = () => send("approve");
  document.getElementById("btn-reject").onclick = () => send("reject");
  document.getElementById("btn-revise").onclick = () => send("revise");
}
