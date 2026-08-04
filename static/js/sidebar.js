/* Sidebar conversation list and actions */
(function (global) {
  const state = {
    conversations: [],
    activeId: null,
    search: "",
  };

  function formatLocalTime(iso) {
    if (!iso) return "";
    const date = new Date(iso);
    if (Number.isNaN(date.getTime())) return "";
    return date.toLocaleString(undefined, {
      month: "short",
      day: "numeric",
      hour: "numeric",
      minute: "2-digit",
    });
  }

  function formatBytes(bytes) {
    const n = Number(bytes) || 0;
    if (n < 1024) return `${n} B`;
    if (n < 1024 * 1024) return `${(n / 1024).toFixed(n < 10 * 1024 ? 1 : 0)} KB`;
    return `${(n / (1024 * 1024)).toFixed(2)} MB`;
  }

  function updateStorageFooterFromList() {
    const el = document.getElementById("storage-usage-label");
    if (!el) return;
    const total = state.conversations.reduce(
      (sum, item) => sum + (Number(item.storage_bytes) || 0),
      0
    );
    el.textContent = `Storage: ${formatBytes(total)} chats`;
    el.title = "Approximate stored chat text size. Delete large chats to free space.";
  }

  async function refreshStorageFooter() {
    const el = document.getElementById("storage-usage-label");
    if (!el) return;
    updateStorageFooterFromList();
    try {
      const payload = await API.get("/api/storage");
      const data = payload.data || {};
      const chat = formatBytes(data.total_chat_bytes || 0);
      const db = formatBytes(data.database_bytes || 0);
      el.textContent = `Storage: ${chat} chats · ${db} DB`;
      el.title = "Approximate chat text size and SQLite database file size";
    } catch {
      updateStorageFooterFromList();
    }
  }

  function closeMenus() {
    document.querySelectorAll(".conversation-menu.open").forEach((m) => m.classList.remove("open"));
  }

  function escapeHtml(value) {
    return String(value)
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#39;");
  }

  function render() {
    const list = document.getElementById("conversation-list");
    if (!list) return;
    const term = state.search.trim().toLowerCase();
    const items = state.conversations.filter((c) =>
      !term ? true : (c.title || "").toLowerCase().includes(term)
    );

    list.innerHTML = "";
    if (!items.length) {
      const empty = document.createElement("div");
      empty.className = "conversation-item";
      empty.style.cursor = "default";
      empty.innerHTML = `<div class="title" style="color:var(--text-muted)">No conversations</div>`;
      list.appendChild(empty);
      return;
    }

    items.forEach((conversation) => {
      const card = document.createElement("div");
      card.className = `conversation-item${conversation.id === state.activeId ? " active" : ""}`;
      const sizeLabel = formatBytes(conversation.storage_bytes || 0);
      card.innerHTML = `
        <div class="title">${escapeHtml(conversation.title || "New Chat")}</div>
        <div class="meta">
          <span>${escapeHtml(formatLocalTime(conversation.updated_at))}</span>
          <span class="storage-chip" title="Approx. stored size for this chat">${escapeHtml(sizeLabel)}</span>
        </div>
      `;
      card.addEventListener("click", (e) => {
        if (e.target.closest(".conversation-actions") || e.target.closest(".conversation-menu")) return;
        closeMenus();
        global.App?.openConversation?.(conversation.id);
      });

      const actions = document.createElement("div");
      actions.className = "conversation-actions";

      const deleteBtn = document.createElement("button");
      deleteBtn.type = "button";
      deleteBtn.className = "icon-btn conversation-delete-btn";
      deleteBtn.title = "Delete chat";
      deleteBtn.setAttribute("aria-label", "Delete chat");
      deleteBtn.innerHTML = `<i class="fa-regular fa-trash-can"></i>`;
      deleteBtn.addEventListener("click", (event) => {
        event.stopPropagation();
        closeMenus();
        global.App?.deleteConversation?.(conversation.id, conversation.title);
      });

      const menuBtn = document.createElement("button");
      menuBtn.type = "button";
      menuBtn.className = "icon-btn conversation-menu-btn";
      menuBtn.title = "More actions";
      menuBtn.setAttribute("aria-label", "More actions");
      menuBtn.innerHTML = `<i class="fa-solid fa-ellipsis"></i>`;

      const menu = document.createElement("div");
      menu.className = "conversation-menu";
      menu.innerHTML = `
        <button type="button" data-action="rename">Rename</button>
        <button type="button" data-action="export-md">Export Markdown</button>
        <button type="button" data-action="export-json">Export JSON</button>
        <button type="button" class="danger" data-action="delete">Delete</button>
      `;

      menuBtn.addEventListener("click", (event) => {
        event.stopPropagation();
        const wasOpen = menu.classList.contains("open");
        closeMenus();
        if (!wasOpen) menu.classList.add("open");
      });

      menu.addEventListener("click", async (event) => {
        const button = event.target.closest("button[data-action]");
        if (!button) return;
        event.stopPropagation();
        closeMenus();
        const action = button.dataset.action;
        if (action === "rename") global.App?.renameConversation?.(conversation.id, conversation.title);
        if (action === "delete") global.App?.deleteConversation?.(conversation.id, conversation.title);
        if (action === "export-md") {
          try {
            await API.download(`/api/conversations/${conversation.id}/export/markdown`, `conversation-${conversation.id}.md`);
            Notify.success("Markdown export downloaded.");
          } catch (err) {
            Notify.error(err.message);
          }
        }
        if (action === "export-json") {
          try {
            await API.download(`/api/conversations/${conversation.id}/export/json`, `conversation-${conversation.id}.json`);
            Notify.success("JSON export downloaded.");
          } catch (err) {
            Notify.error(err.message);
          }
        }
      });

      actions.appendChild(deleteBtn);
      actions.appendChild(menuBtn);
      card.appendChild(actions);
      card.appendChild(menu);
      list.appendChild(card);
    });
  }

  async function load(search) {
    const query = search != null ? search : state.search;
    state.search = query || "";
    const url = state.search
      ? `/api/conversations?search=${encodeURIComponent(state.search)}`
      : "/api/conversations";
    let serverItems = [];
    try {
      const payload = await API.get(url);
      serverItems = payload.data || [];
    } catch {
      serverItems = [];
    }

    const localItems = global.ChatStore?.list?.() || [];
    const byId = new Map();
    localItems.forEach((item) => {
      if (item?.id != null) byId.set(Number(item.id), { ...item });
    });
    serverItems.forEach((item) => {
      const local = byId.get(Number(item.id));
      byId.set(Number(item.id), local ? { ...local, ...item, messages: item.messages || local.messages } : item);
      global.ChatStore?.save?.(item, local?.messages);
    });

    let merged = Array.from(byId.values());
    const term = (state.search || "").trim().toLowerCase();
    if (term) {
      merged = merged.filter((c) => (c.title || "").toLowerCase().includes(term));
    }
    merged.sort((a, b) => String(b.updated_at || "").localeCompare(String(a.updated_at || "")));
    state.conversations = merged;
    render();
    updateStorageFooterFromList();
    refreshStorageFooter().catch(() => {});
    return state.conversations;
  }

  function setActive(id) {
    state.activeId = id;
    render();
  }

  function upsert(conversation) {
    if (!conversation) return;
    const idx = state.conversations.findIndex((c) => c.id === conversation.id);
    if (idx >= 0) state.conversations[idx] = { ...state.conversations[idx], ...conversation };
    else state.conversations.unshift(conversation);
    state.conversations.sort((a, b) => String(b.updated_at).localeCompare(String(a.updated_at)));
    const current = state.conversations.find((c) => c.id === conversation.id);
    global.ChatStore?.save?.(current || conversation, current?.messages || conversation.messages);
    render();
    refreshStorageFooter().catch(() => {});
  }

  function remove(id) {
    state.conversations = state.conversations.filter((c) => c.id !== id);
    if (state.activeId === id) state.activeId = null;
    global.ChatStore?.remove?.(id);
    render();
    refreshStorageFooter().catch(() => {});
  }

  document.addEventListener("click", closeMenus);

  global.Sidebar = {
    load,
    setActive,
    upsert,
    remove,
    refreshStorageFooter,
    getActiveId: () => state.activeId,
    getConversations: () => state.conversations,
  };
})(window);
