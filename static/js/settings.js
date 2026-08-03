/* Settings modal logic */
(function (global) {
  let draft = null;

  function $(id) {
    return document.getElementById(id);
  }

  function open() {
    const dialog = $("settings-dialog");
    if (!dialog) return;
    populate(global.App?.getSettings?.() || {});
    dialog.showModal();
  }

  function close() {
    $("settings-dialog")?.close();
  }

  function populate(settings) {
    draft = { ...settings };
    $("setting-theme").value = settings.theme || "dark";
    $("setting-provider").value = settings.default_provider || "groq";
    $("setting-confirm-delete").checked = settings.confirm_delete !== false;
    $("setting-enter-to-send").checked = settings.enter_to_send !== false;
    $("setting-temperature").value = settings.temperature ?? 0.7;
    $("temperature-value").textContent = String(settings.temperature ?? 0.7);
    $("setting-max-tokens").value = settings.max_tokens ?? 4096;
    $("setting-context-messages").value = settings.context_messages ?? 80;
    $("setting-system-prompt").value = settings.system_prompt || "";
    $("database-path").textContent = settings.database_path || "instance/personal_ai_workspace.db";

    const modelSelect = $("setting-model");
    const topModelSelect = $("model-select");
    if (modelSelect && topModelSelect) {
      modelSelect.innerHTML = topModelSelect.innerHTML;
      const desired = settings.default_model || "";
      if (desired && ![...modelSelect.options].some((o) => o.value === desired)) {
        const opt = document.createElement("option");
        opt.value = desired;
        opt.textContent = desired;
        modelSelect.appendChild(opt);
      }
      modelSelect.value = desired || modelSelect.value;
    }
  }

  function collect() {
    return {
      theme: $("setting-theme").value,
      default_provider: $("setting-provider").value,
      default_model: $("setting-model").value,
      confirm_delete: $("setting-confirm-delete").checked,
      enter_to_send: $("setting-enter-to-send").checked,
      temperature: Number($("setting-temperature").value),
      max_tokens: Number($("setting-max-tokens").value),
      context_messages: Number($("setting-context-messages").value),
      system_prompt: $("setting-system-prompt").value,
    };
  }

  async function save() {
    try {
      const payload = await API.put("/api/settings", collect());
      global.App?.applySettings?.(payload.data);
      Notify.success("Settings saved.");
      close();
    } catch (err) {
      Notify.error(err.message || "Unable to save settings.");
    }
  }

  function bindTabs() {
    document.querySelectorAll(".settings-tab").forEach((tab) => {
      tab.addEventListener("click", () => {
        document.querySelectorAll(".settings-tab").forEach((t) => t.classList.remove("active"));
        document.querySelectorAll(".settings-panel").forEach((p) => p.classList.remove("active"));
        tab.classList.add("active");
        document.querySelector(`.settings-panel[data-panel="${tab.dataset.tab}"]`)?.classList.add("active");
      });
    });
  }

  function bind() {
    bindTabs();
    $("btn-open-settings")?.addEventListener("click", openWithProviders);
    $("btn-top-settings")?.addEventListener("click", openWithProviders);
    $("btn-close-settings")?.addEventListener("click", close);
    $("btn-cancel-settings")?.addEventListener("click", close);
    $("btn-save-settings")?.addEventListener("click", save);

    $("setting-temperature")?.addEventListener("input", (e) => {
      $("temperature-value").textContent = e.target.value;
    });

    $("btn-reset-prompt")?.addEventListener("click", async () => {
      try {
        const payload = await API.post("/api/settings/reset-system-prompt", {});
        $("setting-system-prompt").value = payload.data.system_prompt || "";
        global.App?.applySettings?.(payload.data);
        Notify.success("System prompt reset.");
      } catch (err) {
        Notify.error(err.message || "Unable to reset prompt.");
      }
    });

    $("btn-export-all")?.addEventListener("click", async () => {
      try {
        await API.download("/api/export/all", "personal-ai-workspace-export.json");
        Notify.success("Export downloaded.");
      } catch (err) {
        Notify.error(err.message || "Export failed.");
      }
    });

    $("import-file")?.addEventListener("change", async (event) => {
      const file = event.target.files?.[0];
      if (!file) return;
      const form = new FormData();
      form.append("file", file);
      try {
        const payload = await API.request("/api/import", { method: "POST", body: form });
        Notify.success(
          `Imported ${payload.data.conversations_imported} conversations (${payload.data.messages_imported} messages).`
        );
        await global.App?.refreshConversations?.();
      } catch (err) {
        Notify.error(err.message || "Import failed.");
      } finally {
        event.target.value = "";
      }
    });

    $("btn-clear-all")?.addEventListener("click", async () => {
      const confirmed = await global.App?.confirmAction?.(
        "Clear all conversations",
        "This permanently deletes every conversation and message. Continue?",
        "Clear all"
      );
      if (!confirmed) return;
      try {
        await API.del("/api/settings/conversations");
        Notify.success("All conversations cleared.");
        await global.App?.startFresh?.();
      } catch (err) {
        Notify.error(err.message || "Unable to clear conversations.");
      }
    });
  }

  function renderProviderCards() {
    const host = $("provider-cards");
    if (!host) return;
    const providers = global.App?.getProviders?.() || [];
    host.innerHTML = "";
    providers.forEach((provider) => {
      const card = document.createElement("div");
      card.className = "provider-card";
      card.innerHTML = `
        <div>
          <strong>${provider.name}</strong>
          <p>${provider.status}${provider.default_model ? " · default " + provider.default_model : ""}</p>
        </div>
      `;
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "btn btn-primary";
      btn.textContent = "Test";
      btn.disabled = !provider.configured;
      btn.addEventListener("click", async () => {
        const result = $("connection-result");
        result.hidden = false;
        result.classList.remove("error");
        result.textContent = `Testing ${provider.name}…`;
        try {
          const payload = await API.post(`/api/providers/${provider.id}/test`, {});
          result.textContent = payload.data.message || "Connected successfully.";
        } catch (err) {
          result.classList.add("error");
          result.textContent = err.message || "Connection test failed.";
        }
      });
      card.appendChild(btn);
      host.appendChild(card);
    });
  }

  function openWithProviders() {
    populate(global.App?.getSettings?.() || {});
    renderProviderCards();
    $("settings-dialog")?.showModal();
  }

  global.SettingsUI = { bind, open: openWithProviders, close, populate, renderProviderCards };
})(window);
