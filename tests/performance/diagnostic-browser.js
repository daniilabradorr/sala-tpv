// Paste only in a synthetic test environment. No URLs, fields or HTML exported.
(() => {
  if (window.tpvDiagnostic) return;
  const rows = [];
  const requests = new WeakMap();
  const handlers = [];
  let intent = null;
  const on = (type, listener, capture = false) => {
    document.addEventListener(type, listener, capture);
    handlers.push([type, listener, capture]);
  };
  on("click", () => { intent = performance.now(); }, true);
  on("keydown", e => { if (e.key === "Enter") intent = performance.now(); }, true);
  on("htmx:configRequest", e => {
    e.detail.headers["X-TPV-Trace"] = crypto.randomUUID();
  });
  on("htmx:beforeRequest", e => {
    const start = performance.now();
    const row = {start, intent: intent !== null && start - intent < 60000 ? intent : null};
    intent = null;
    requests.set(e.detail.xhr, row);
  });
  on("htmx:afterRequest", e => {
    const xhr = e.detail.xhr;
    const row = requests.get(xhr);
    if (!row) return;
    row.response = performance.now();
    const traceId = xhr.getResponseHeader("X-TPV-Trace");
    row.trace_id = /^[0-9a-f-]{36}$/.test(traceId || "") ? traceId : null;
    row.server_timing_ms = {};
    for (const part of (xhr.getResponseHeader("Server-Timing") || "").split(",")) {
      const match = part.trim().match(/^(django|sql);dur=([0-9.]+)$/);
      if (match) row.server_timing_ms[match[1]] = Number(match[2]);
    }
    row.status = xhr.status;
    // Keep resource names only transiently for matching, never in exported rows.
    const resource = performance.getEntriesByType("resource").filter(
      r => r.initiatorType === "xmlhttprequest" && r.name === xhr.responseURL
        && r.startTime >= row.start - 1 && r.responseEnd <= performance.now()
    ).at(-1);
    row.response_end_known = Boolean(resource);
    row.response = resource ? resource.responseEnd : row.response;
    row.http_ms = resource ? resource.responseEnd - resource.startTime : null;
    row.ttfb_ms = resource ? resource.responseStart - resource.requestStart : null;
    row.download_ms = resource ? resource.responseEnd - resource.responseStart : null;
    row.dns_ms = resource ? resource.domainLookupEnd - resource.domainLookupStart : null;
    row.connect_ms = resource ? resource.connectEnd - resource.connectStart : null;
    row.client_wait_ms = row.intent === null ? null : row.start - row.intent;
    row.xhr_ms = row.response - row.start;
    if (row.status === 0 || row.status >= 400) {
      row.finished = true;
      rows.push({trace_id: row.trace_id, status: row.status,
        http_ms: row.http_ms, xhr_ms: row.xhr_ms,
        visual_ms: null, outcome: "error_or_unknown"});
      if (rows.length > 1000) rows.shift();
    }
  });
  on("htmx:afterSwap", e => {
    const row = requests.get(e.detail.xhr);
    if (row) row.swap = performance.now();
  });
  on("htmx:afterSettle", e => {
    const row = requests.get(e.detail.xhr);
    if (!row || row.finished) return;
    row.finished = true;
    const settle = performance.now();
    requestAnimationFrame(() => requestAnimationFrame(() => {
      const frame = performance.now();
      rows.push({
        trace_id: row.trace_id,
        status: row.status,
        server_timing_ms: row.server_timing_ms,
        http_ms: row.http_ms,
        ttfb_ms: row.ttfb_ms,
        download_ms: row.download_ms,
        dns_ms: row.dns_ms,
        connect_ms: row.connect_ms,
        client_wait_ms: row.client_wait_ms,
        xhr_ms: row.xhr_ms,
        response_to_swap_ms: row.response_end_known && row.swap ? row.swap - row.response : null,
        response_to_settle_ms: row.response_end_known ? settle - row.response : null,
        response_to_frame_ms: row.response_end_known ? frame - row.response : null,
        interaction_to_frame_ms: row.intent === null ? null : frame - row.intent,
      });
      if (rows.length > 1000) rows.shift();
    }));
  });
  window.tpvDiagnostic = {
    rows,
    stop() {
      for (const args of handlers) document.removeEventListener(...args);
      delete window.tpvDiagnostic;
    },
  };
})();
