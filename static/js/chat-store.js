/* Browser chat store — primary history on Vercel (no external database required). */
(function (global) {
  const KEY = "ahsan_ai_workspace_chats_v1";

  function readAll() {
    try {
      const raw = localStorage.getItem(KEY);
      if (!raw) return {};
      const parsed = JSON.parse(raw);
      return parsed && typeof parsed === "object" ? parsed : {};
    } catch {
      return {};
    }
  }

  function writeAll(map) {
    try {
      localStorage.setItem(KEY, JSON.stringify(map));
    } catch {
      /* quota / private mode */
    }
  }

  function list() {
    return Object.values(readAll()).sort((a, b) =>
      String(b.updated_at || "").localeCompare(String(a.updated_at || ""))
    );
  }

  function get(id) {
    if (id == null) return null;
    return readAll()[String(id)] || null;
  }

  function save(conversation, messages) {
    if (!conversation || conversation.id == null) return;
    const map = readAll();
    const key = String(conversation.id);
    const prev = map[key] || {};
    const nextMessages = Array.isArray(messages)
      ? messages
      : Array.isArray(conversation.messages)
        ? conversation.messages
        : prev.messages || [];
    map[key] = {
      ...prev,
      ...conversation,
      id: conversation.id,
      messages: nextMessages,
      storage_bytes:
        conversation.storage_bytes != null
          ? conversation.storage_bytes
          : nextMessages.reduce((sum, m) => sum + String(m.content || "").length, 0),
      updated_at: conversation.updated_at || new Date().toISOString(),
    };
    writeAll(map);
  }

  function remove(id) {
    const map = readAll();
    delete map[String(id)];
    writeAll(map);
  }

  function clear() {
    writeAll({});
  }

  global.ChatStore = { list, get, save, remove, clear };
})(window);
