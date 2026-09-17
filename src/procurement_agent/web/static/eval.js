function renderReport(report) {
  const metrics = [
    ["用例总数", report.total ?? 0],
    ["成功率", ((report.success_rate ?? 0) * 100).toFixed(1) + "%"],
    ["人工介入率", ((report.intervention_rate ?? 0) * 100).toFixed(1) + "%"],
    ["平均耗时", (report.avg_duration_ms ?? 0) + " ms"],
    ["上下文 token 峰值", report.token_peak ?? 0],
    ["上下文压缩率", ((report.context_reduction_rate ?? 0) * 100).toFixed(1) + "%"],
  ];
  document.getElementById("eval-metrics").innerHTML = metrics
    .map(([label, value]) => `<div class="metric"><div class="hint">${label}</div><div class="value">${value}</div></div>`)
    .join("");
  const failures = report.failures || [];
  document.getElementById("eval-failures").innerHTML = failures.length
    ? `<table class="data"><tr><th>用例</th><th>期望</th><th>实际</th><th>任务</th></tr>` +
      failures.map((f) => `<tr><td>${f.case_id}</td><td>${f.expect_state}</td>
        <td>${f.actual_state}</td><td><a href="/tasks/${f.task_id}">查看</a></td></tr>`).join("") +
      `</table>`
    : '<p class="hint">没有失败用例</p>';
}

async function poll() {
  const res = await fetch("/api/eval/latest");
  const report = await res.json();
  document.getElementById("eval-status").textContent =
    report.status === "finished" ? "已完成" : report.status === "running" ? "运行中…" : "尚未运行";
  if (report.status === "finished") {
    renderReport(report);
    return true;
  }
  return false;
}

document.getElementById("eval-run").onclick = async () => {
  document.getElementById("eval-status").textContent = "已提交…";
  await fetch("/api/eval/run", { method: "POST" });
  const timer = setInterval(async () => {
    if (await poll()) clearInterval(timer);
  }, 1500);
};

poll();
