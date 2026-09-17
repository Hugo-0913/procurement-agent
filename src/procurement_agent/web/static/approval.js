function renderApproval(detail, onDone) {
  const existing = document.getElementById("approval-card");
  if (existing) existing.remove();
  const pending = detail.pending_approval;
  if (!pending) return;

  const draft = pending.order_draft || {};
  const rules = (pending.matched_rules || [])
    .map((r) => `<div class="rule">命中规则：${r}</div>`)
    .join("");
  const card = document.createElement("div");
  card.className = "approval-card";
  card.id = "approval-card";
  card.innerHTML = `
    <div><strong>需要人工审批</strong></div>
    ${rules}
    <table class="kv" style="margin-top:8px">
      <tr><td>供应商</td><td>${draft.supplier_name || "-"}</td></tr>
      <tr><td>数量</td><td>${draft.quantity ?? "-"}</td></tr>
      <tr><td>单价</td><td>¥${(draft.unit_price ?? 0).toFixed(2)}</td></tr>
      <tr><td>总额</td><td>¥${(draft.total_amount ?? 0).toFixed(2)}</td></tr>
      <tr><td>交期</td><td>${draft.lead_days ?? "-"} 天</td></tr>
      <tr><td>成本中心</td><td>${draft.cost_center || "-"}</td></tr>
    </table>
    <div class="small" style="margin-top:8px">比价结论：${pending.recommendation_reason || "-"}</div>
    <textarea id="approval-reason" rows="2" placeholder="审批意见（驳回或要求修改时必填）"></textarea>
    <div class="row">
      <button id="btn-approve">批准</button>
      <button id="btn-reject" class="ghost">驳回</button>
      <button id="btn-revise" class="ghost">要求修改</button>
      <span id="approval-hint" class="hint"></span>
    </div>`;
  document.getElementById("timeline").prepend(card);

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

