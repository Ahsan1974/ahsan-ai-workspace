/* Application bootstrap and orchestration */
(function () {
  const state = {
    settings: {},
    activeConversationId: null,
    models: [],
    providers: [],
    currentModelMeta: null,
  };

  function $(id) {
    return document.getElementById(id);
  }

  function applyTheme(theme) {
    const mode = theme === "light" ? "light" : "dark";
    document.documentElement.setAttribute("data-theme", mode);
    const icon = $("theme-toggle-icon");
    if (icon) {
      icon.className = mode === "dark" ? "fa-solid fa-sun" : "fa-solid fa-moon";
    }
    const dark = $("hljs-dark");
    const light = $("hljs-light");
    if (dark && light) {
      dark.disabled = mode === "light";
      light.disabled = mode !== "light";
    }
  }

  function applySettings(settings) {
    state.settings = settings || {};
    applyTheme(state.settings.theme || "dark");
    // Do not force a disabled / unconfigured provider into the select.
    if ($("database-path") && settings.database_path) {
      $("database-path").textContent = settings.database_path;
    }
  }

  function syncModelSelects(selected) {
    const selects = [$("model-select"), $("setting-model")].filter(Boolean);
    selects.forEach((select) => {
      const current = selected || select.value;
      if (current && ![...select.options].some((o) => o.value === current)) {
        const opt = document.createElement("option");
        opt.value = current;
        opt.textContent = current;
        select.appendChild(opt);
      }
      if (current) select.value = current;
    });
  }

  function fillModelOptions(models, selected) {
    state.models = models || [];
    const selects = [$("model-select"), $("setting-model")].filter(Boolean);
    if (!state.models.length && selected) {
      state.models = [{ id: selected, name: selected }];
    }
    selects.forEach((select) => {
      select.innerHTML = "";
      state.models.forEach((model) => {
        const opt = document.createElement("option");
        opt.value = model.id;
        opt.textContent = model.name || model.id;
        select.appendChild(opt);
      });
    });
    const pick =
      (selected && state.models.some((m) => m.id === selected) && selected) ||
      state.models[0]?.id ||
      state.settings.default_model;
    syncModelSelects(pick);
    updateModelCapacityLabel();
  }

  function updateModelCapacityLabel() {
    // Kept for compatibility; capacity now implied by model choice + token strip.
  }

  function formatCount(n) {
    if (n == null || Number.isNaN(Number(n))) return "—";
    return Number(n).toLocaleString();
  }

  function applyTokenStrip(total, remaining) {
    const totalEl = $("stat-total-tokens");
    const leftEl = $("stat-left-tokens");
    if (!totalEl || !leftEl) return;
    totalEl.textContent = formatCount(total);
    leftEl.textContent = remaining != null ? formatCount(remaining) : "—";
  }

  function refreshTokenStripFromLocal(provider) {
    const local = globalThis.UsageStore?.todayFor?.(provider);
    if (!local) return false;
    applyTokenStrip(local.total_tokens, local.remaining);
    return true;
  }

  async function refreshTokenStrip() {
    const provider = $("provider-select")?.value || state.settings.default_provider || "groq";
    const totalEl = $("stat-total-tokens");
    const leftEl = $("stat-left-tokens");
    if (!totalEl || !leftEl) return;

    const local = globalThis.UsageStore?.todayFor?.(provider) || {
      total_tokens: 0,
      remaining: globalThis.UsageStore?.limits?.()?.[provider] ?? null,
      limit: globalThis.UsageStore?.limits?.()?.[provider] ?? null,
    };
    // Show browser totals immediately (works on Vercel when server DB is empty).
    applyTokenStrip(local.total_tokens, local.remaining);

    try {
      const payload = await API.get("/api/dashboard/usage");
      const rows = payload.data?.today?.by_provider || [];
      const row = rows.find((r) => r.provider === provider);
      const serverTotal = Number(row?.total_tokens) || 0;
      const limits = payload.data?.limits || globalThis.UsageStore?.limits?.() || {};
      const limit = Number(limits[provider] ?? local.limit) || null;
      // Prefer the higher of local ledger vs server (server is often wiped on Vercel).
      const total = Math.max(local.total_tokens || 0, serverTotal);
      const remaining = limit != null ? Math.max(0, limit - total) : row?.remaining ?? local.remaining;
      applyTokenStrip(total, remaining);
    } catch {
      refreshTokenStripFromLocal(provider);
    }
  }

  function recordUsage(provider, usage) {
    if (!usage || !globalThis.UsageStore) return;
    const pid = provider || $("provider-select")?.value || state.settings.default_provider || "groq";
    globalThis.UsageStore.add(pid, usage.total_tokens, {
      prompt_tokens: usage.prompt_tokens,
      completion_tokens: usage.completion_tokens,
    });
    refreshTokenStripFromLocal(pid);
  }

  function fillProviderOptions(providers, selected) {
    state.providers = providers || [];
    const selects = [$("provider-select"), $("setting-provider")].filter(Boolean);
    selects.forEach((select) => {
      select.innerHTML = "";
      state.providers.forEach((provider) => {
        const opt = document.createElement("option");
        opt.value = provider.id;
        opt.textContent = provider.configured
          ? provider.name
          : `${provider.name} (not configured)`;
        opt.disabled = !provider.configured;
        select.appendChild(opt);
      });
    });
    const firstConfigured = state.providers.find((p) => p.configured)?.id;
    const isConfigured = (id) =>
      Boolean(id && state.providers.find((p) => p.id === id && p.configured));
    const preferred =
      (isConfigured(selected) && selected) ||
      (isConfigured(state.settings.default_provider) && state.settings.default_provider) ||
      firstConfigured ||
      "groq";
    selects.forEach((select) => {
      if ([...select.options].some((o) => o.value === preferred && !o.disabled)) {
        select.value = preferred;
      } else if (firstConfigured) {
        select.value = firstConfigured;
      }
    });
    const label = $("sidebar-provider-label");
    const current = state.providers.find((p) => p.id === ($("provider-select")?.value || preferred));
    if (label && current) label.textContent = current.name;
  }

  function updateProviderStatus(configured, available) {
    const dot = $("provider-status-dot");
    if (!dot) return;
    dot.classList.remove("ok", "bad");
    if (!configured) dot.classList.add("bad");
    else if (available) dot.classList.add("ok");
  }

  async function loadSettings() {
    const payload = await API.get("/api/settings");
    applySettings(payload.data);
    return payload.data;
  }

  async function loadProviders() {
    const payload = await API.get("/api/providers");
    fillProviderOptions(payload.data || [], state.settings.default_provider);
    return payload.data || [];
  }

  async function loadModels(providerId, preferredModelOverride) {
    const provider = providerId || $("provider-select")?.value || state.settings.default_provider || "groq";
    try {
      const payload = await API.get(`/api/providers/${provider}/models`);
      const data = payload.data || {};
      const preferredModel =
        preferredModelOverride ||
        data.fallback_model ||
        data.models?.[0]?.id ||
        state.settings.default_model;
      fillModelOptions(data.models || [], preferredModel);
      if (data.saved_model_unavailable && !preferredModelOverride) {
        const fallback = data.fallback_model;
        if (fallback) {
          syncModelSelects(fallback);
          Notify.warning(`Saved model is unavailable. Switched to ${fallback}.`);
        }
      }
      updateProviderStatus(Boolean(data.configured), Boolean(data.configured));
      const anyConfigured = state.providers.some((p) => p.configured);
      $("api-banner").hidden = anyConfigured;
      const label = $("sidebar-provider-label");
      const current = state.providers.find((p) => p.id === provider);
      if (label && current) label.textContent = current.name;
      await refreshTokenStrip();
      return data;
    } catch (err) {
      const fallback = preferredModelOverride || state.settings.default_model || "llama-3.3-70b-versatile";
      fillModelOptions([{ id: fallback, name: fallback }], fallback);
      updateProviderStatus(false, false);
      Notify.warning(err.message || "Unable to load models.");
      return null;
    }
  }

  async function loadProviderStatus() {
    const provider = $("provider-select")?.value || "groq";
    try {
      const payload = await API.get(`/api/providers/status?provider=${encodeURIComponent(provider)}`);
      updateProviderStatus(payload.data.configured, payload.data.available);
      const anyConfigured = state.providers.some((p) => p.configured);
      $("api-banner").hidden = anyConfigured;
    } catch {
      updateProviderStatus(false, false);
    }
  }

  async function refreshConversations() {
    const conversations = await Sidebar.load($("conversation-search")?.value || "");
    return conversations;
  }

  function guardBusyAction() {
    if (!Chat.isGenerating()) return true;
    if (!Chat.hasActiveRequest?.()) {
      Chat.forceIdle?.();
      return true;
    }
    Notify.warning("Wait for the current response to finish, or press Stop.");
    return false;
  }

  async function openConversation(id) {
    if (!guardBusyAction()) return;
    try {
      const payload = await API.get(`/api/conversations/${id}`);
      const conversation = payload.data;
      state.activeConversationId = conversation.id;
      Sidebar.setActive(conversation.id);
      Chat.setTitle(conversation.title);
      Chat.renderMessages(conversation.messages || []);
      global.ChatStore?.save?.(conversation, conversation.messages || []);
      const provider = conversation.provider || state.settings.default_provider || "groq";
      const providerSelect = $("provider-select");
      if (providerSelect) providerSelect.value = provider;
      await loadModels(provider, conversation.model || undefined);
      if (conversation.model) syncModelSelects(conversation.model);
      updateModelCapacityLabel();
      closeMobileSidebar();
      return;
    } catch (err) {
      if (err.code !== "CONVERSATION_NOT_FOUND") {
        Notify.error(err.message || "Unable to open conversation.");
        return;
      }
    }

    // Restore from browser cache and re-create on the server.
    const cached = ChatStore?.get?.(id);
    if (!cached) {
      Notify.error("Conversation not found.");
      Sidebar.remove(id);
      return;
    }
    try {
      const restored = await API.post("/api/conversations", {
        title: cached.title || "New Chat",
        provider: cached.provider || $("provider-select")?.value || "groq",
        model: cached.model || $("model-select")?.value || "",
        messages: cached.messages || [],
      });
      const conversation = restored.data;
      ChatStore.remove(id);
      ChatStore.save(conversation, conversation.messages || cached.messages || []);
      Sidebar.remove(id);
      Sidebar.upsert(conversation);
      state.activeConversationId = conversation.id;
      Sidebar.setActive(conversation.id);
      Chat.setTitle(conversation.title);
      Chat.renderMessages(conversation.messages || cached.messages || []);
      const provider = conversation.provider || "groq";
      const providerSelect = $("provider-select");
      if (providerSelect) providerSelect.value = provider;
      await loadModels(provider, conversation.model || undefined);
      if (conversation.model) syncModelSelects(conversation.model);
      closeMobileSidebar();
      Notify.success("Chat restored on this server.");
    } catch (err) {
      // Offline-ish fallback: show cached messages locally.
      state.activeConversationId = null;
      Sidebar.setActive(null);
      Chat.setTitle(cached.title || "New Chat");
      Chat.renderMessages(cached.messages || []);
      Notify.warning(err.message || "Opened cached chat. Send a message to re-sync.");
    }
  }

  async function reloadActiveConversation() {
    if (!state.activeConversationId) {
      return;
    }
    try {
      await openConversation(state.activeConversationId);
    } catch {
      /* keep current UI */
    }
  }

  async function createNewChat() {
    if (!guardBusyAction()) return;
    const payload = await API.post("/api/conversations", {
      provider: $("provider-select")?.value || "groq",
      model: $("model-select")?.value || state.settings.default_model || "",
    });
    const conversation = payload.data;
    Sidebar.upsert(conversation);
    state.activeConversationId = conversation.id;
    Sidebar.setActive(conversation.id);
    Chat.setTitle(conversation.title || "New Chat");
    Chat.clearMessages();
    closeMobileSidebar();
  }

  async function startFresh() {
    state.activeConversationId = null;
    Sidebar.setActive(null);
    await refreshConversations();
    Chat.setTitle("New Chat");
    Chat.clearMessages();
  }

  function confirmAction(title, message, okLabel = "Confirm") {
    return new Promise((resolve) => {
      const dialog = $("confirm-dialog");
      $("confirm-title").textContent = title;
      $("confirm-message").textContent = message;
      $("confirm-ok").textContent = okLabel;
      const onClose = () => {
        dialog.removeEventListener("close", onClose);
        resolve(dialog.returnValue === "confirm");
      };
      dialog.addEventListener("close", onClose);
      dialog.showModal();
    });
  }

  async function renameConversation(id, currentTitle) {
    const dialog = $("rename-dialog");
    const input = $("rename-input");
    input.value = currentTitle || "";
    const onClose = async () => {
      dialog.removeEventListener("close", onClose);
      if (dialog.returnValue !== "confirm") return;
      const title = input.value.trim();
      if (!title) return;
      try {
        const payload = await API.patch(`/api/conversations/${id}`, { title });
        Sidebar.upsert(payload.data);
        if (state.activeConversationId === id) Chat.setTitle(payload.data.title);
        Notify.success("Conversation renamed.");
      } catch (err) {
        Notify.error(err.message || "Unable to rename.");
      }
    };
    dialog.addEventListener("close", onClose);
    dialog.showModal();
    input.focus();
    input.select();
  }

  async function deleteConversation(id, title) {
    const needsConfirm = state.settings.confirm_delete !== false;
    if (needsConfirm) {
      const ok = await confirmAction(
        "Delete conversation",
        `Delete “${title || "this conversation"}”? This cannot be undone.`,
        "Delete"
      );
      if (!ok) return;
    }
    let message = "Conversation deleted.";
    try {
      await API.del(`/api/conversations/${id}`);
    } catch (err) {
      // Chat may only exist in this browser (Vercel ephemeral DB).
      if (err?.code !== "CONVERSATION_NOT_FOUND" && err?.status !== 404) {
        message = "Removed from this browser (server delete failed).";
      }
    }
    globalThis.ChatStore?.remove?.(id);
    Sidebar.remove(id);
    if (Number(state.activeConversationId) === Number(id)) {
      state.activeConversationId = null;
      Chat.setTitle("New Chat");
      Chat.clearMessages();
    }
    Notify.success(message);
  }

  function openMobileSidebar() {
    $("app-shell")?.classList.add("sidebar-open");
    $("sidebar-backdrop").hidden = false;
  }

  function closeMobileSidebar() {
    $("app-shell")?.classList.remove("sidebar-open");
    $("sidebar-backdrop").hidden = true;
  }

  function openSidebar() {
    const shell = $("app-shell");
    if (window.matchMedia("(max-width: 960px)").matches) {
      openMobileSidebar();
    } else {
      shell?.classList.remove("sidebar-collapsed");
    }
  }

  function bindShell() {
    $("btn-new-chat")?.addEventListener("click", () => {
      createNewChat().catch((err) => Notify.error(err.message));
    });

    $("btn-collapse-sidebar")?.addEventListener("click", () => {
      const shell = $("app-shell");
      if (window.matchMedia("(max-width: 960px)").matches) {
        closeMobileSidebar();
      } else {
        shell?.classList.add("sidebar-collapsed");
      }
    });

    $("btn-open-sidebar")?.addEventListener("click", openSidebar);
    $("sidebar-backdrop")?.addEventListener("click", closeMobileSidebar);

    $("btn-theme-toggle")?.addEventListener("click", async () => {
      const next = (state.settings.theme || "dark") === "dark" ? "light" : "dark";
      try {
        const payload = await API.put("/api/settings", { theme: next });
        applySettings(payload.data);
      } catch (err) {
        Notify.error(err.message || "Unable to update theme.");
      }
    });

    let searchTimer = null;
    $("conversation-search")?.addEventListener("input", (event) => {
      window.clearTimeout(searchTimer);
      searchTimer = window.setTimeout(() => {
        Sidebar.load(event.target.value).catch((err) => Notify.error(err.message));
      }, 200);
    });

    document.querySelectorAll(".starter-chip").forEach((chip) => {
      chip.addEventListener("click", () => {
        Chat.setInputText(chip.dataset.prompt || chip.textContent || "");
      });
    });

    $("model-select")?.addEventListener("change", async (event) => {
      const model = event.target.value;
      updateModelCapacityLabel();
      try {
        // Update only the active chat — do not rewrite global defaults.
        syncModelSelects(model);
        if (state.activeConversationId) {
          const payload = await API.patch(`/api/conversations/${state.activeConversationId}`, {
            model,
            provider: $("provider-select")?.value || "groq",
          });
          Sidebar.upsert(payload.data);
        }
      } catch (err) {
        Notify.error(err.message || "Unable to update model.");
      }
    });

    $("provider-select")?.addEventListener("change", async (event) => {
      const provider = event.target.value;
      const meta = state.providers.find((p) => p.id === provider);
      if (!meta?.configured) {
        Notify.warning("That provider is not configured in .env.");
        event.target.value = state.settings.default_provider || "groq";
        return;
      }
      try {
        await loadModels(provider);
        const model = $("model-select")?.value || "";
        if (state.activeConversationId) {
          const payload = await API.patch(`/api/conversations/${state.activeConversationId}`, {
            provider,
            model,
          });
          Sidebar.upsert(payload.data);
        }
        Notify.success(`Switched this chat to ${meta.name}. Other chats are unchanged.`);
        await refreshTokenStrip();
      } catch (err) {
        Notify.error(err.message || "Unable to switch provider.");
      }
    });
  }

  window.App = {
    getSettings: () => state.settings,
    applySettings,
    getActiveConversationId: () => state.activeConversationId,
    setActiveConversationId: (id) => {
      state.activeConversationId = id;
    },
    openConversation: (id) => openConversation(id).catch((err) => Notify.error(err.message)),
    reloadActiveConversation,
    refreshConversations,
    startFresh,
    confirmAction,
    renameConversation,
    deleteConversation,
    updateProviderStatus,
    loadModels,
    fillProviderOptions,
    getProviders: () => state.providers,
    refreshTokenStrip,
    recordUsage,
  };

  async function init() {
    Chat.bind();
    SettingsUI.bind();
    DashboardUI.bind();
    bindShell();

    const banner = $("ephemeral-db-banner");
    if (banner) {
      const hosted = Boolean(window.__WORKSPACE__?.hosted);
      const durable = Boolean(window.__WORKSPACE__?.durableDatabase);
      banner.hidden = !(hosted && !durable);
    }

    try {
      await loadSettings();
      await loadProviders();
      await Promise.all([loadModels(), loadProviderStatus(), refreshConversations(), refreshTokenStrip()]);
      const conversations = Sidebar.getConversations();
      if (conversations.length) {
        await openConversation(conversations[0].id);
      } else {
        Chat.clearMessages();
      }
    } catch (err) {
      Notify.error(err.message || "Failed to initialize workspace.");
      Chat.clearMessages();
    }
  }

  document.addEventListener("DOMContentLoaded", init);
})();
