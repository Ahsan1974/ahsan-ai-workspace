/* Browser token usage — survives Vercel’s ephemeral server DB. */
(function (global) {
  const KEY = "ahsan_ai_workspace_usage_v1";
  const DEFAULT_LIMITS = {
    groq: 200000,
    sambanova: 200000,
    gemini: 1000000,
    openrouter: 100000,
    mistral: 200000,
    cohere: 100000,
  };

  function dayKey(date = new Date()) {
    const y = date.getFullYear();
    const m = String(date.getMonth() + 1).padStart(2, "0");
    const d = String(date.getDate()).padStart(2, "0");
    return `${y}-${m}-${d}`;
  }

  function read() {
    try {
      const raw = localStorage.getItem(KEY);
      if (!raw) return { byDay: {} };
      const parsed = JSON.parse(raw);
      return parsed && typeof parsed === "object" ? parsed : { byDay: {} };
    } catch {
      return { byDay: {} };
    }
  }

  function write(data) {
    try {
      localStorage.setItem(KEY, JSON.stringify(data));
    } catch {
      /* ignore */
    }
  }

  function add(provider, totalTokens, extras = {}) {
    const tokens = Math.max(0, Number(totalTokens) || 0);
    if (!tokens) return;
    const pid = String(provider || "unknown").toLowerCase();
    const store = read();
    const day = dayKey();
    if (!store.byDay[day]) store.byDay[day] = {};
    const row = store.byDay[day][pid] || {
      total_tokens: 0,
      prompt_tokens: 0,
      completion_tokens: 0,
    };
    row.total_tokens += tokens;
    row.prompt_tokens += Math.max(0, Number(extras.prompt_tokens) || 0);
    row.completion_tokens += Math.max(0, Number(extras.completion_tokens) || 0);
    store.byDay[day][pid] = row;
    write(store);
  }

  function todayFor(provider) {
    const pid = String(provider || "").toLowerCase();
    const row = (read().byDay || {})[dayKey()]?.[pid];
    return {
      total_tokens: Number(row?.total_tokens) || 0,
      prompt_tokens: Number(row?.prompt_tokens) || 0,
      completion_tokens: Number(row?.completion_tokens) || 0,
      limit: DEFAULT_LIMITS[pid] ?? null,
      remaining:
        DEFAULT_LIMITS[pid] != null
          ? Math.max(0, DEFAULT_LIMITS[pid] - (Number(row?.total_tokens) || 0))
          : null,
    };
  }

  function limits() {
    return { ...DEFAULT_LIMITS };
  }

  global.UsageStore = { add, todayFor, limits, dayKey };
})(window);
