// Synthetic browser observer. No URLs, request bodies, HTML or economic UUIDs exported.
(() => {
  if (window.phase3) return;
  const state = window.phase3 = {flush: [], sync: [], events: [], errors: 0, open: null, submit: null};
  const now = () => performance.now();
  const nativeFetch = window.fetch;
  window.fetch = async function(input, options) {
    const isCart = String(input).includes('/cart-sync/');
    const start = now();
    try {
      const response = await nativeFetch.apply(this, arguments);
      if (isCart) state.sync.push({start, ms: now() - start, method: options?.method || 'GET', status: response.status, trace_id: response.headers.get('X-TPV-Trace')});
      return response;
    } catch (error) {
      if (isCart) state.sync.push({start, ms: now() - start, method: options?.method || 'GET', status: null, cancelled: error.name === 'AbortError'});
      throw error;
    }
  };
  document.addEventListener('click', e => {
    if (e.target.closest('[data-checkout-open]')) state.open = {click: now()};
    if (e.target.closest('.checkout-confirm')) state.submit = {click: now()};
  }, true);
  for (const type of ['beforeRequest', 'afterRequest', 'afterSwap', 'afterSettle', 'sendError', 'responseError', 'timeout', 'sendAbort']) {
    document.addEventListener('htmx:' + type, e => {
      const relevant = e.detail.target?.id === 'checkout-panel' || e.detail.elt?.closest?.('[data-checkout-form]');
      if (!relevant) return;
      state.events.push({type, t: now(), status: e.detail.xhr?.status ?? null});
      const row = state.submit || state.open;
      if (row && type === 'beforeRequest') row.request = now();
      if (row && type === 'afterSwap') row.swap = now();
      if (row && type === 'afterSettle') {
        row.settle = now();
        requestAnimationFrame(() => requestAnimationFrame(() => {
          row.frame = now();
          row.new_sale_enabled = Boolean(document.querySelector('.checkout-success [data-nx-sale-start] button:not(:disabled)'));
          row.processing = document.querySelector('#checkout-dialog')?.dataset.nxProcessing === 'true';
        }));
      }
    });
  }
  window.addEventListener('error', () => state.errors++);
  window.addEventListener('unhandledrejection', () => state.errors++);
  state.installQueue = () => {
    const prototype = window.SalesCartQueue.prototype;
    if (prototype.phase3Installed) return;
    prototype.phase3Installed = true;
    const flush = prototype.flush;
    prototype.flush = function() {
      const row = {start: now(), pending_operations: this.ops.length, initialization_pending: !this.protocolReady, initialization_wait_ms: this.protocolReady ? 0 : null, header_pending: this.headerPending};
      state.flush.push(row);
      if (!this.protocolReady && this.initialization) this.initialization.then(() => row.initialization_wait_ms = now() - row.start, () => {});
      return flush.apply(this, arguments).finally(() => row.ms = now() - row.start);
    };
    const dialog = document.querySelector('#checkout-dialog');
    if (dialog) new MutationObserver(() => {
      if (dialog.open && state.open && state.open.modal === undefined) state.open.modal = now();
    }).observe(dialog, {attributes: true, attributeFilter: ['open']});
  };
})();
