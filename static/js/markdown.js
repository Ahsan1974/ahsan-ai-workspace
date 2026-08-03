/* Markdown rendering with sanitization and code copy buttons */
(function (global) {
  function configureMarked() {
    if (!global.marked) return;
    marked.setOptions({
      gfm: true,
      breaks: true,
      headerIds: false,
      mangle: false,
    });
  }

  function highlightCode(root) {
    if (!global.hljs || !root) return;
    root.querySelectorAll("pre code").forEach((block) => {
      hljs.highlightElement(block);
    });
  }

  function addCopyButtons(root) {
    if (!root) return;
    root.querySelectorAll("pre").forEach((pre) => {
      if (pre.querySelector(".copy-code-btn")) return;
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "copy-code-btn";
      btn.textContent = "Copy";
      btn.addEventListener("click", async () => {
        const code = pre.querySelector("code");
        const text = code ? code.innerText : pre.innerText;
        try {
          await navigator.clipboard.writeText(text);
          btn.textContent = "Copied";
          window.setTimeout(() => (btn.textContent = "Copy"), 1200);
        } catch {
          Notify.error("Unable to copy code.");
        }
      });
      pre.appendChild(btn);
    });
  }

  function renderMarkdown(text) {
    configureMarked();
    const raw = global.marked ? marked.parse(text || "") : (text || "");
    const clean = global.DOMPurify
      ? DOMPurify.sanitize(raw, {
          USE_PROFILES: { html: true },
          ADD_ATTR: ["target", "rel"],
        })
      : raw;
    const wrapper = document.createElement("div");
    wrapper.className = "message-content";
    wrapper.innerHTML = clean;
    wrapper.querySelectorAll("a[href]").forEach((a) => {
      a.setAttribute("target", "_blank");
      a.setAttribute("rel", "noopener noreferrer");
    });
    highlightCode(wrapper);
    addCopyButtons(wrapper);
    return wrapper;
  }

  global.Markdown = { render: renderMarkdown };
})(window);
