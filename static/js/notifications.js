/* Toast notifications */
(function (global) {
  const root = () => document.getElementById("toast-root");

  function notify(message, type = "info", timeout = 3800) {
    const host = root();
    if (!host || !message) return;
    const el = document.createElement("div");
    el.className = `toast ${type}`;
    el.textContent = message;
    host.appendChild(el);
    window.setTimeout(() => {
      el.style.opacity = "0";
      el.style.transform = "translateY(6px)";
      window.setTimeout(() => el.remove(), 180);
    }, timeout);
  }

  global.Notify = { show: notify, success: (m) => notify(m, "success"), error: (m) => notify(m, "error"), warning: (m) => notify(m, "warning") };
})(window);
