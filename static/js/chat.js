/* Chat rendering, sending, streaming, and message actions */
(function (global) {
  const els = {};
  let abortController = null;
  let generating = false;
  let currentMessages = [];
  /** @type {{id:string, file:File, previewUrl?:string}[]} */
  let pendingFiles = [];
  const MAX_PENDING_FILES = 5;
  const ALLOWED_EXT = new Set([
    "java", "pdf", "png", "jpg", "jpeg", "txt", "py", "md", "json", "xml",
    "yml", "yaml", "cs", "js", "ts", "sql", "html", "css",
  ]);

  function workspaceConfig() {
    return global.__WORKSPACE__ || {};
  }

  function maxUploadBytes() {
    const mb = Number(workspaceConfig().maxUploadMb);
    return ((Number.isFinite(mb) && mb > 0 ? mb : 8) * 1024 * 1024);
  }

  function preferStream() {
    return workspaceConfig().preferStream !== false;
  }

  function cacheEls() {
    els.messages = document.getElementById("messages");
    els.emptyState = document.getElementById("empty-state");
    els.input = document.getElementById("message-input");
    els.sendBtn = document.getElementById("btn-send");
    els.stopBtn = document.getElementById("btn-stop");
    els.clearBtn = document.getElementById("btn-clear-input");
    els.charCount = document.getElementById("char-count");
    els.title = document.getElementById("current-conversation-title");
    els.fileInput = document.getElementById("file-input");
    els.attachmentPreview = document.getElementById("attachment-preview");
    els.attachBtn = document.getElementById("btn-attach");
  }

  function formatTime(iso) {
    if (!iso) return "";
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return "";
    return d.toLocaleString(undefined, {
      month: "short",
      day: "numeric",
      hour: "numeric",
      minute: "2-digit",
    });
  }

  function scrollToBottom(force = false) {
    if (!els.messages) return;
    const nearBottom =
      els.messages.scrollHeight - els.messages.scrollTop - els.messages.clientHeight < 140;
    if (force || nearBottom) {
      els.messages.scrollTop = els.messages.scrollHeight;
    }
  }

  function setEmptyVisible(visible) {
    if (!els.emptyState) return;
    els.emptyState.classList.toggle("hidden", !visible);
  }

  function setGenerating(isGenerating) {
    generating = isGenerating;
    updateSendEnabled();
    if (els.stopBtn) els.stopBtn.hidden = !isGenerating;
    if (els.input) els.input.dataset.busy = isGenerating ? "1" : "0";
  }

  function canSend() {
    const hasText = Boolean((els.input?.value || "").trim());
    return !generating && (hasText || pendingFiles.length > 0);
  }

  function updateSendEnabled() {
    if (els.sendBtn) els.sendBtn.disabled = !canSend();
  }

  function autoResize() {
    if (!els.input) return;
    els.input.style.height = "auto";
    els.input.style.height = `${Math.min(els.input.scrollHeight, 200)}px`;
    if (els.charCount) els.charCount.textContent = String(els.input.value.length);
    updateSendEnabled();
  }

  function fileExt(name) {
    const parts = String(name || "").toLowerCase().split(".");
    return parts.length > 1 ? parts.pop() : "";
  }

  function clearPendingFiles() {
    pendingFiles.forEach((item) => {
      if (item.previewUrl) URL.revokeObjectURL(item.previewUrl);
    });
    pendingFiles = [];
    renderAttachmentPreview();
    updateSendEnabled();
  }

  function renderAttachmentPreview() {
    const host = els.attachmentPreview;
    if (!host) return;
    host.innerHTML = "";
    if (!pendingFiles.length) {
      host.hidden = true;
      return;
    }
    host.hidden = false;
    pendingFiles.forEach((item) => {
      const chip = document.createElement("div");
      chip.className = "attachment-chip";
      const ext = fileExt(item.file.name);
      if (item.previewUrl) {
        const img = document.createElement("img");
        img.src = item.previewUrl;
        img.alt = item.file.name;
        chip.appendChild(img);
      } else {
        const icon = document.createElement("i");
        icon.className = ext === "pdf" ? "fa-solid fa-file-pdf" : "fa-solid fa-file-code";
        chip.appendChild(icon);
      }
      const name = document.createElement("span");
      name.className = "chip-name";
      name.textContent = item.file.name;
      name.title = item.file.name;
      chip.appendChild(name);
      const remove = document.createElement("button");
      remove.type = "button";
      remove.className = "chip-remove";
      remove.title = "Remove file";
      remove.innerHTML = `<i class="fa-solid fa-xmark"></i>`;
      remove.addEventListener("click", () => {
        pendingFiles = pendingFiles.filter((f) => f.id !== item.id);
        if (item.previewUrl) URL.revokeObjectURL(item.previewUrl);
        renderAttachmentPreview();
        updateSendEnabled();
      });
      chip.appendChild(remove);
      host.appendChild(chip);
    });
  }

  function compressImageFile(file) {
    return new Promise((resolve) => {
      const maxBytes = Math.min(maxUploadBytes(), 1.8 * 1024 * 1024);
      if (file.size <= maxBytes) {
        resolve(file);
        return;
      }
      const url = URL.createObjectURL(file);
      const img = new Image();
      img.onload = () => {
        URL.revokeObjectURL(url);
        const maxDim = 1600;
        let { width, height } = img;
        const scale = Math.min(1, maxDim / Math.max(width, height));
        width = Math.max(1, Math.round(width * scale));
        height = Math.max(1, Math.round(height * scale));
        const canvas = document.createElement("canvas");
        canvas.width = width;
        canvas.height = height;
        const ctx = canvas.getContext("2d");
        if (!ctx) {
          resolve(file);
          return;
        }
        ctx.drawImage(img, 0, 0, width, height);
        let quality = 0.82;
        const finish = (blob) => {
          if (!blob) {
            resolve(file);
            return;
          }
          const name = file.name.replace(/\.(png|jpeg|jpg)$/i, ".jpg");
          resolve(new File([blob], name, { type: "image/jpeg" }));
        };
        const tryQuality = () => {
          canvas.toBlob(
            (blob) => {
              if (blob && blob.size > maxBytes && quality > 0.45) {
                quality -= 0.12;
                tryQuality();
                return;
              }
              finish(blob);
            },
            "image/jpeg",
            quality
          );
        };
        tryQuality();
      };
      img.onerror = () => {
        URL.revokeObjectURL(url);
        resolve(file);
      };
      img.src = url;
    });
  }

  async function addFiles(fileList) {
    const incoming = Array.from(fileList || []);
    const limit = maxUploadBytes();
    const limitMb = Math.round(limit / (1024 * 1024));
    for (const raw of incoming) {
      if (pendingFiles.length >= MAX_PENDING_FILES) {
        Notify.warning(`You can attach at most ${MAX_PENDING_FILES} files.`);
        break;
      }
      const ext = fileExt(raw.name);
      if (!ALLOWED_EXT.has(ext)) {
        Notify.error(`Unsupported file type: ${raw.name}`);
        continue;
      }
      let file = raw;
      if (["png", "jpg", "jpeg"].includes(ext)) {
        try {
          file = await compressImageFile(raw);
        } catch {
          file = raw;
        }
      }
      if (file.size > limit) {
        Notify.error(
          `${raw.name} is larger than ${limitMb} MB` +
            (workspaceConfig().hosted
              ? " (hosting limit). Try a smaller PDF/image."
              : ".")
        );
        continue;
      }
      const item = { id: `${Date.now()}-${Math.random().toString(16).slice(2)}`, file };
      if (["png", "jpg", "jpeg"].includes(fileExt(file.name))) {
        item.previewUrl = URL.createObjectURL(file);
      }
      pendingFiles.push(item);
    }
    renderAttachmentPreview();
    updateSendEnabled();
    if (els.fileInput) els.fileInput.value = "";
  }

  function clearMessages() {
    currentMessages = [];
    if (els.messages) els.messages.innerHTML = "";
    setEmptyVisible(true);
  }

  function renderMessages(messages) {
    currentMessages = Array.isArray(messages) ? messages : [];
    if (!els.messages) return;
    els.messages.innerHTML = "";
    if (!currentMessages.length) {
      setEmptyVisible(true);
      return;
    }
    setEmptyVisible(false);
    currentMessages.forEach((message, index) => {
      const isLatestAssistant =
        message.role === "assistant" &&
        index === currentMessages.length - 1;
      els.messages.appendChild(buildMessageElement(message, { canRegenerate: isLatestAssistant }));
    });
    scrollToBottom(true);
    const activeId = global.App?.getActiveConversationId?.();
    if (activeId) {
      global.ChatStore?.save?.(
        {
          id: activeId,
          title: els.title?.textContent || "New Chat",
          provider: document.getElementById("provider-select")?.value,
          model: document.getElementById("model-select")?.value,
          updated_at: new Date().toISOString(),
        },
        currentMessages
      );
    }
  }

  function buildMessageElement(message, options = {}) {
    const article = document.createElement("article");
    article.className = `message ${message.role}`;
    article.dataset.messageId = message.id || "";

    const meta = document.createElement("div");
    meta.className = "message-meta";
    const who = message.role === "user" ? "You" : "Assistant";
    let extra = "";
    if (message.role === "assistant" && (message.provider || message.model)) {
      const providerLabel = message.provider === "groq" ? "Groq" : message.provider || "";
      extra = ` · ${providerLabel}${message.model ? " / " + message.model : ""}`;
    }
    meta.innerHTML = `<strong>${who}</strong><span>${formatTime(message.created_at)}${extra}</span>`;

    const bubble = document.createElement("div");
    bubble.className = "message-bubble";
    if (message.role === "assistant") {
      bubble.appendChild(Markdown.render(message.content || ""));
    } else {
      const pre = document.createElement("div");
      pre.className = "message-content";
      pre.textContent = message.content || "";
      bubble.appendChild(pre);
    }

    const actions = document.createElement("div");
    actions.className = "message-actions";

    const copyBtn = document.createElement("button");
    copyBtn.type = "button";
    copyBtn.className = "icon-btn";
    copyBtn.title = "Copy message";
    copyBtn.innerHTML = `<i class="fa-regular fa-copy"></i>`;
    copyBtn.addEventListener("click", async () => {
      try {
        await navigator.clipboard.writeText(message.content || "");
        Notify.success("Message copied.");
      } catch {
        Notify.error("Unable to copy message.");
      }
    });
    actions.appendChild(copyBtn);

    if (options.canRegenerate && message.id) {
      const regenBtn = document.createElement("button");
      regenBtn.type = "button";
      regenBtn.className = "icon-btn";
      regenBtn.title = "Regenerate";
      regenBtn.innerHTML = `<i class="fa-solid fa-rotate"></i>`;
      regenBtn.addEventListener("click", () => regenerate(message.id));
      actions.appendChild(regenBtn);
    }

    if (message.id) {
      const delBtn = document.createElement("button");
      delBtn.type = "button";
      delBtn.className = "icon-btn";
      delBtn.title = "Delete message";
      delBtn.innerHTML = `<i class="fa-regular fa-trash-can"></i>`;
      delBtn.addEventListener("click", () => deleteMessage(message.id));
      actions.appendChild(delBtn);
    }

    article.appendChild(meta);
    article.appendChild(bubble);
    article.appendChild(actions);
    return article;
  }

  function createStreamingPlaceholder(provider, model) {
    setEmptyVisible(false);
    const article = document.createElement("article");
    article.className = "message assistant";
    article.id = "streaming-message";

    const meta = document.createElement("div");
    meta.className = "message-meta";
    const providerLabel = provider === "groq" ? "Groq" : provider || "Groq";
    meta.innerHTML = `<strong>Assistant</strong><span>${providerLabel}${model ? " / " + model : ""}</span>`;

    const bubble = document.createElement("div");
    bubble.className = "message-bubble";
    const typing = document.createElement("div");
    typing.className = "typing-indicator";
    typing.id = "typing-indicator";
    typing.innerHTML = `Thinking <span class="dots"><span></span><span></span><span></span></span>`;
    const contentHost = document.createElement("div");
    contentHost.className = "message-content";
    contentHost.id = "streaming-content";
    bubble.appendChild(typing);
    bubble.appendChild(contentHost);

    article.appendChild(meta);
    article.appendChild(bubble);
    els.messages.appendChild(article);
    scrollToBottom(true);
    return { article, contentHost, typing };
  }

  async function ensureConversation(options = {}) {
    const forceNew = Boolean(options.forceNew);
    const seedMessages = Array.isArray(options.messages) ? options.messages : null;
    let id = forceNew ? null : global.App?.getActiveConversationId?.();

    if (id && !forceNew) {
      try {
        await API.get(`/api/conversations/${id}`);
        return id;
      } catch (err) {
        if (err.code !== "CONVERSATION_NOT_FOUND") throw err;
        // Stale id from another serverless instance — recreate below.
        global.App?.setActiveConversationId?.(null);
      }
    }

    const body = {
      provider: document.getElementById("provider-select")?.value || "groq",
      model: document.getElementById("model-select")?.value || "",
      title: (els.title?.textContent || "New Chat").trim() || "New Chat",
    };
    if (seedMessages && seedMessages.length) {
      body.messages = seedMessages
        .filter((m) => m && (m.role === "user" || m.role === "assistant") && m.content)
        .map((m) => ({
          role: m.role,
          content: m.content,
          provider: m.provider,
          model: m.model,
        }));
    }

    const created = await API.post("/api/conversations", body);
    const conversation = created.data;
    Sidebar.upsert(conversation);
    Sidebar.setActive(conversation.id);
    global.App?.setActiveConversationId?.(conversation.id);
    if (els.title) els.title.textContent = conversation.title || "New Chat";
    if (conversation.messages) {
      currentMessages = conversation.messages;
    }
    global.ChatStore?.save?.(conversation, conversation.messages || currentMessages);
    return conversation.id;
  }

  async function sendMessage() {
    if (generating && !abortController) {
      forceIdle();
    }
    if (!canSend()) return;
    const text = (els.input?.value || "").trim();
    const filesToSend = pendingFiles.map((item) => item.file);
    const attachmentNames = filesToSend.map((f) => f.name);

    const provider = document.getElementById("provider-select")?.value || "groq";
    const model = document.getElementById("model-select")?.value || "";

    els.input.value = "";
    clearPendingFiles();
    autoResize();

    let optimisticText = text;
    if (attachmentNames.length) {
      const labels = attachmentNames.map((n) => `📎 ${n}`).join("\n");
      optimisticText = text ? `${text}\n\n${labels}` : labels;
    }

    const optimisticUser = {
      id: null,
      role: "user",
      content: optimisticText,
      created_at: new Date().toISOString(),
      provider,
      model,
    };
    setEmptyVisible(false);
    els.messages.appendChild(buildMessageElement(optimisticUser));
    scrollToBottom(true);

    setGenerating(true);
    abortController = new AbortController();
    const streamUi = createStreamingPlaceholder(provider, model);
    let assembled = "";
    const historyBeforeSend = currentMessages.slice();

    const postOnce = async (conversationId, useStream) => {
      const form = new FormData();
      form.append("content", text);
      form.append("provider", provider);
      form.append("model", model);
      form.append("stream", useStream ? "true" : "false");
      form.append(
        "client_history",
        JSON.stringify(
          historyBeforeSend
            .filter((m) => m && (m.role === "user" || m.role === "assistant") && m.content)
            .map((m) => ({
              role: m.role,
              content: m.content,
              provider: m.provider,
              model: m.model,
            }))
        )
      );
      filesToSend.forEach((file) => form.append("files", file, file.name));
      return fetch(`/api/conversations/${conversationId}/messages`, {
        method: "POST",
        headers: {
          Accept: "text/event-stream, application/json",
        },
        body: form,
        signal: abortController.signal,
      });
    };

    try {
      let conversationId = await ensureConversation();
      let useStream = preferStream();
      let response = await postOnce(conversationId, useStream);
      let contentType = response.headers.get("content-type") || "";

      // Stale conversation on another serverless instance — recreate with history and retry once.
      if (response.status === 404) {
        const payload = await response.json().catch(() => null);
        if (payload?.error?.code === "CONVERSATION_NOT_FOUND") {
          conversationId = await ensureConversation({
            forceNew: true,
            messages: historyBeforeSend,
          });
          response = await postOnce(conversationId, useStream);
          contentType = response.headers.get("content-type") || "";
        }
      }

      if (
        useStream &&
        (!response.ok || !contentType.includes("text/event-stream"))
      ) {
        if (response.status === 413) {
          throw Object.assign(
            new Error(
              `Upload too large for the host (max ~${Number(workspaceConfig().maxUploadMb) || 3} MB).`
            ),
            { code: "ATTACHMENT_TOO_LARGE" }
          );
        }
        if (response.ok && contentType.includes("application/json")) {
          // fall through to JSON handler
        } else if (response.status !== 404) {
          response = await postOnce(conversationId, false);
          contentType = response.headers.get("content-type") || "";
          useStream = false;
        }
      }

      if (!response.ok) {
        if (response.status === 413) {
          throw Object.assign(
            new Error(
              `Upload too large for the host (max ~${Number(workspaceConfig().maxUploadMb) || 3} MB).`
            ),
            { code: "ATTACHMENT_TOO_LARGE" }
          );
        }
        const payload = await response.json().catch(() => null);
        throw Object.assign(new Error(payload?.error?.message || "Failed to send message"), {
          code: payload?.error?.code,
        });
      }

      if (!contentType.includes("text/event-stream")) {
        const payload = await response.json().catch(() => null);
        if (!payload?.success) {
          throw Object.assign(new Error(payload?.error?.message || "Failed to send message"), {
            code: payload?.error?.code,
          });
        }
        const data = payload.data || {};
        const streaming = document.getElementById("streaming-message");
        if (streaming) streaming.remove();
        if (data.user_message) currentMessages.push(data.user_message);
        if (data.assistant_message) currentMessages.push(data.assistant_message);
        renderMessages(currentMessages);
        if (data.conversation) {
          const oldId = global.App?.getActiveConversationId?.();
          if (oldId && data.conversation.id && oldId !== data.conversation.id) {
            Sidebar.remove(oldId);
            global.ChatStore?.remove?.(oldId);
          }
          global.App?.setActiveConversationId?.(data.conversation.id);
          Sidebar.setActive(data.conversation.id);
          Sidebar.upsert({ ...data.conversation, messages: currentMessages });
          if (els.title) els.title.textContent = data.conversation.title || "New Chat";
          global.ChatStore?.save?.(data.conversation, currentMessages);
        }
        if (data.model_switched_for_vision && data.model) {
          Notify.warning(`Switched this chat to ${data.model} for attachments.`);
        }
        if (data.usage) {
          global.App?.recordUsage?.(data.provider || document.getElementById("provider-select")?.value, data.usage);
        } else {
          global.App?.refreshTokenStrip?.();
        }
        global.App?.refreshConversations?.().catch(() => {});
        return;
      }

      await API.consumeSSE(
        response,
        {
          meta: (data) => {
            if (data.user_message) {
              currentMessages.push(data.user_message);
            }
            if (data.conversation) {
              const oldId = global.App?.getActiveConversationId?.();
              if (oldId && data.conversation.id && oldId !== data.conversation.id) {
                Sidebar.remove(oldId);
                global.ChatStore?.remove?.(oldId);
              }
              global.App?.setActiveConversationId?.(data.conversation.id);
              Sidebar.setActive(data.conversation.id);
              Sidebar.upsert(data.conversation);
              if (els.title) els.title.textContent = data.conversation.title || "New Chat";
            }
            if (data.model_switched_for_vision && data.model) {
              Notify.warning(`Switched this chat to ${data.model} for attachments.`);
              const modelSelect = document.getElementById("model-select");
              if (modelSelect) {
                if (![...modelSelect.options].some((o) => o.value === data.model)) {
                  const opt = document.createElement("option");
                  opt.value = data.model;
                  opt.textContent = data.model;
                  modelSelect.appendChild(opt);
                }
                modelSelect.value = data.model;
              }
            }
          },
          token: (data) => {
            if (streamUi.typing) streamUi.typing.remove();
            assembled += data.content || "";
            streamUi.contentHost.replaceWith(
              Object.assign(Markdown.render(assembled), { id: "streaming-content" })
            );
            streamUi.contentHost = document.getElementById("streaming-content");
            scrollToBottom();
          },
          done: (data) => {
            const streaming = document.getElementById("streaming-message");
            if (streaming) streaming.remove();
            if (data.assistant_message) {
              currentMessages.push(data.assistant_message);
              renderMessages(currentMessages);
            }
            if (data.conversation) {
              const oldId = global.App?.getActiveConversationId?.();
              if (oldId && data.conversation.id && oldId !== data.conversation.id) {
                Sidebar.remove(oldId);
                global.ChatStore?.remove?.(oldId);
              }
              global.App?.setActiveConversationId?.(data.conversation.id);
              Sidebar.setActive(data.conversation.id);
              Sidebar.upsert({ ...data.conversation, messages: currentMessages });
              if (els.title) els.title.textContent = data.conversation.title || "New Chat";
              global.ChatStore?.save?.(data.conversation, currentMessages);
            }
            if (data.usage) {
              global.App?.recordUsage?.(data.provider || document.getElementById("provider-select")?.value, data.usage);
            } else {
              global.App?.refreshTokenStrip?.();
            }
            global.App?.refreshConversations?.().catch(() => {});
          },
          error: (data) => {
            const streaming = document.getElementById("streaming-message");
            if (streaming) streaming.remove();
            Notify.error(data?.message || "Generation failed.");
            global.App?.reloadActiveConversation?.();
          },
        },
        abortController.signal
      );
    } catch (err) {
      const streaming = document.getElementById("streaming-message");
      if (streaming) streaming.remove();
      if (err.name === "AbortError") {
        Notify.warning("Generation stopped.");
        global.App?.reloadActiveConversation?.();
      } else {
        Notify.error(err.message || "Failed to send message.");
        global.App?.reloadActiveConversation?.();
      }
    } finally {
      abortController = null;
      setGenerating(false);
      autoResize();
      els.input?.focus();
    }
  }

  async function regenerate(messageId) {
    if (generating || !messageId) return;
    const provider = document.getElementById("provider-select")?.value || "groq";
    const model = document.getElementById("model-select")?.value || "";

    // Optimistically remove the last assistant message from the UI.
    currentMessages = currentMessages.filter((m) => m.id !== messageId);
    renderMessages(currentMessages);

    setGenerating(true);
    abortController = new AbortController();
    const streamUi = createStreamingPlaceholder(provider, model);
    let assembled = "";

    try {
      const response = await fetch(`/api/messages/${messageId}/regenerate`, {
        method: "POST",
        headers: {
          Accept: "text/event-stream, application/json",
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ provider, model, stream: true }),
        signal: abortController.signal,
      });

      const contentType = response.headers.get("content-type") || "";
      if (!response.ok || !contentType.includes("text/event-stream")) {
        const payload = await response.json().catch(() => null);
        throw Object.assign(new Error(payload?.error?.message || "Regenerate failed"), {
          code: payload?.error?.code,
        });
      }

      await API.consumeSSE(
        response,
        {
          token: (data) => {
            if (streamUi.typing) streamUi.typing.remove();
            assembled += data.content || "";
            streamUi.contentHost.replaceWith(
              Object.assign(Markdown.render(assembled), { id: "streaming-content" })
            );
            streamUi.contentHost = document.getElementById("streaming-content");
            scrollToBottom();
          },
          done: (data) => {
            const streaming = document.getElementById("streaming-message");
            if (streaming) streaming.remove();
            if (data.assistant_message) {
              currentMessages.push(data.assistant_message);
              renderMessages(currentMessages);
            }
            if (data.conversation) Sidebar.upsert(data.conversation);
          },
          error: (data) => {
            const streaming = document.getElementById("streaming-message");
            if (streaming) streaming.remove();
            Notify.error(data?.message || "Regenerate failed.");
            global.App?.reloadActiveConversation?.();
          },
        },
        abortController.signal
      );
    } catch (err) {
      const streaming = document.getElementById("streaming-message");
      if (streaming) streaming.remove();
      if (err.name === "AbortError") {
        Notify.warning("Generation stopped.");
      } else {
        Notify.error(err.message || "Regenerate failed.");
      }
      global.App?.reloadActiveConversation?.();
    } finally {
      abortController = null;
      setGenerating(false);
    }
  }

  async function deleteMessage(messageId) {
    if (!messageId || generating) return;
    try {
      await API.del(`/api/messages/${messageId}`);
      currentMessages = currentMessages.filter((m) => m.id !== messageId);
      renderMessages(currentMessages);
      Notify.success("Message deleted.");
    } catch (err) {
      Notify.error(err.message || "Unable to delete message.");
    }
  }

  function stop() {
    if (abortController) {
      try {
        abortController.abort();
      } catch {
        /* ignore */
      }
      abortController = null;
    }
    const streaming = document.getElementById("streaming-message");
    if (streaming) streaming.remove();
    setGenerating(false);
    updateSendEnabled();
    Notify.warning("Generation stopped.");
  }

  function hasActiveRequest() {
    return Boolean(abortController);
  }

  function forceIdle() {
    abortController = null;
    const streaming = document.getElementById("streaming-message");
    if (streaming) streaming.remove();
    setGenerating(false);
  }

  function setInputText(text) {
    if (!els.input) return;
    els.input.value = text || "";
    autoResize();
    els.input.focus();
  }

  function bind() {
    cacheEls();
    els.input?.addEventListener("input", autoResize);
    els.sendBtn?.addEventListener("click", sendMessage);
    els.stopBtn?.addEventListener("click", stop);
    els.clearBtn?.addEventListener("click", () => {
      setInputText("");
      clearPendingFiles();
    });
    els.fileInput?.addEventListener("change", (event) => {
      addFiles(event.target.files);
    });
    els.attachBtn?.addEventListener("click", () => {
      els.fileInput?.click();
    });
    els.input?.addEventListener("paste", (event) => {
      const items = event.clipboardData?.files;
      if (items && items.length) {
        addFiles(items);
      }
    });
    els.input?.addEventListener("dragover", (event) => {
      event.preventDefault();
    });
    els.input?.addEventListener("drop", (event) => {
      event.preventDefault();
      if (event.dataTransfer?.files?.length) addFiles(event.dataTransfer.files);
    });
    els.input?.addEventListener("keydown", (event) => {
      const enterToSend = global.App?.getSettings?.()?.enter_to_send !== false;
      if (event.key === "Enter" && !event.shiftKey && enterToSend) {
        event.preventDefault();
        sendMessage();
      }
    });
    autoResize();
  }

  global.Chat = {
    bind,
    renderMessages,
    clearMessages,
    setInputText,
    sendMessage,
    stop,
    forceIdle,
    hasActiveRequest,
    getMessages: () => currentMessages.slice(),
    isGenerating: () => generating,
    setTitle: (title) => {
      if (els.title) els.title.textContent = title || "New Chat";
    },
  };
})(window);
