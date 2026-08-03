/* Lightweight API client */
(function (global) {
  async function parseJsonSafe(response) {
    const text = await response.text();
    if (!text) return null;
    try {
      return JSON.parse(text);
    } catch {
      return null;
    }
  }

  async function request(url, options = {}) {
    const opts = {
      headers: {
        Accept: "application/json",
        ...(options.body && !(options.body instanceof FormData)
          ? { "Content-Type": "application/json" }
          : {}),
        ...(options.headers || {}),
      },
      ...options,
    };

    const response = await fetch(url, opts);
    const contentType = response.headers.get("content-type") || "";

    if (contentType.includes("text/event-stream")) {
      return response;
    }

    // File downloads (markdown/json export)
    if (
      contentType.includes("text/markdown") ||
      (contentType.includes("application/json") &&
        (response.headers.get("content-disposition") || "").includes("attachment"))
    ) {
      return response;
    }

    const payload = await parseJsonSafe(response);
    if (!response.ok) {
      const err = new Error(
        payload?.error?.message || `Request failed (${response.status})`
      );
      err.code = payload?.error?.code || "REQUEST_FAILED";
      err.status = response.status;
      err.payload = payload;
      throw err;
    }
    return payload;
  }

  function get(url) {
    return request(url);
  }

  function post(url, body) {
    return request(url, { method: "POST", body: JSON.stringify(body || {}) });
  }

  function put(url, body) {
    return request(url, { method: "PUT", body: JSON.stringify(body || {}) });
  }

  function patch(url, body) {
    return request(url, { method: "PATCH", body: JSON.stringify(body || {}) });
  }

  function del(url) {
    return request(url, { method: "DELETE" });
  }

  async function download(url, fallbackName) {
    const response = await fetch(url);
    if (!response.ok) {
      const payload = await parseJsonSafe(response);
      throw new Error(payload?.error?.message || "Download failed");
    }
    const blob = await response.blob();
    const disposition = response.headers.get("content-disposition") || "";
    const match = /filename="?([^"]+)"?/i.exec(disposition);
    const filename = match?.[1] || fallbackName || "download";
    const objectUrl = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = objectUrl;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(objectUrl);
  }

  /**
   * Consume an SSE response produced by the Flask streaming endpoints.
   */
  async function consumeSSE(response, handlers = {}, signal) {
    if (!response.body) {
      throw new Error("Streaming is not supported in this browser.");
    }
    const reader = response.body.getReader();
    const decoder = new TextDecoder("utf-8");
    let buffer = "";

    while (true) {
      if (signal?.aborted) {
        try {
          await reader.cancel();
        } catch {
          /* ignore */
        }
        throw new DOMException("Aborted", "AbortError");
      }
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const parts = buffer.split("\n\n");
      buffer = parts.pop() || "";
      for (const part of parts) {
        const lines = part.split("\n");
        let event = "message";
        const dataLines = [];
        for (const line of lines) {
          if (line.startsWith("event:")) event = line.slice(6).trim();
          else if (line.startsWith("data:")) dataLines.push(line.slice(5).trim());
        }
        if (!dataLines.length) continue;
        let data = dataLines.join("\n");
        try {
          data = JSON.parse(data);
        } catch {
          /* keep raw */
        }
        const fn = handlers[event];
        if (typeof fn === "function") fn(data);
      }
    }
  }

  global.API = { request, get, post, put, patch, del, download, consumeSSE };
})(window);
