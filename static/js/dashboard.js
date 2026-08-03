/* Usage dashboard */
(function (global) {
  function $(id) {
    return document.getElementById(id);
  }

  function fmt(n) {
    return Number(n || 0).toLocaleString();
  }

  function renderProviderTable(rows) {
    if (!rows?.length) return "<p class='dashboard-intro'>No usage recorded yet today.</p>";
    const body = rows
      .map((row) => {
        const limit = row.limit != null ? fmt(row.limit) : "—";
        const remaining = row.remaining != null ? fmt(row.remaining) : "—";
        const pct = row.limit ? Math.min(100, Math.round((row.total_tokens / row.limit) * 100)) : 0;
        return `<tr>
          <td>${row.provider}</td>
          <td>${fmt(row.total_tokens)}
            ${row.limit ? `<div class="usage-bar"><span style="width:${pct}%"></span></div>` : ""}
          </td>
          <td>${limit}</td>
          <td>${remaining}</td>
        </tr>`;
      })
      .join("");
    return `<table class="dash-table"><thead><tr><th>Provider</th><th>Used</th><th>Limit</th><th>Left</th></tr></thead><tbody>${body}</tbody></table>`;
  }

  function renderModelTable(rows) {
    if (!rows?.length) return "<p class='dashboard-intro'>No model usage yet.</p>";
    const body = rows
      .map((row) => {
        const limit = row.limit != null ? fmt(row.limit) : "—";
        const remaining = row.remaining != null ? fmt(row.remaining) : "—";
        return `<tr>
          <td>${row.provider}</td>
          <td>${row.model}</td>
          <td>${fmt(row.prompt_tokens)}</td>
          <td>${fmt(row.completion_tokens)}</td>
          <td>${fmt(row.total_tokens)}</td>
          <td>${limit}</td>
          <td>${remaining}</td>
        </tr>`;
      })
      .join("");
    return `<table class="dash-table"><thead><tr><th>Provider</th><th>Model</th><th>Prompt</th><th>Completion</th><th>Total</th><th>Limit</th><th>Left</th></tr></thead><tbody>${body}</tbody></table>`;
  }

  async function refresh() {
    const payload = await API.get("/api/dashboard/usage");
    const data = payload.data || {};
    $("dash-provider-today").innerHTML = renderProviderTable(data.today?.by_provider || []);
    $("dash-model-today").innerHTML = renderModelTable(data.today?.by_model || []);
    $("dash-model-all").innerHTML = renderModelTable(data.all_time?.by_model || []);
  }

  function open() {
    const dialog = $("dashboard-dialog");
    dialog?.showModal();
    refresh().catch((err) => Notify.error(err.message || "Unable to load dashboard."));
  }

  function close() {
    $("dashboard-dialog")?.close();
  }

  function bind() {
    $("btn-open-dashboard")?.addEventListener("click", open);
    $("btn-close-dashboard")?.addEventListener("click", close);
    $("btn-close-dashboard-footer")?.addEventListener("click", close);
    $("btn-refresh-dashboard")?.addEventListener("click", () => {
      refresh().catch((err) => Notify.error(err.message || "Unable to refresh dashboard."));
    });
  }

  global.DashboardUI = { bind, open, refresh };
})(window);
