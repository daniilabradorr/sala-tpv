// Test-only timings. No request values, URLs, cookies, UUIDs or HTML are retained.
(() => {
  if (window.checkoutDProbe) return;
  const records = [];
  const note = (name, extra = {}) => records.push({name, ms: performance.now(), ...extra});
  const requests = new WeakMap();
  for (const event of ['beforeRequest', 'afterRequest', 'afterSwap', 'afterSettle']) {
    document.addEventListener('htmx:' + event, e => {
      if (e.detail.target?.id !== 'checkout-panel') return;
      if (event === 'beforeRequest') requests.set(e.detail.xhr, (e.detail.requestConfig?.verb || '').toUpperCase());
      const method = requests.get(e.detail.xhr);
      if (method) {
        note(event, {method, status: e.detail.xhr.status});
        if (event === 'afterSettle') requestAnimationFrame(() => requestAnimationFrame(() => note('settled-painted', {method})));
      }
    });
  }
  window.addEventListener('click', e => {
    if (e.target.closest('[data-checkout-open]')) note('checkout-click');
    if (e.target.closest('[data-checkout-form] [type="submit"]')) note('confirm-click');
    if (e.target.closest('a[href*="/print/"]')) note('print-click');
  }, true);
  if (window.SalesCartQueue) {
    const prototype = window.SalesCartQueue.prototype;
    const original = prototype.flush;
    prototype.flush = function (...args) {
      note('flush-start');
      return original.apply(this, args).finally(() => note('flush-end'));
    };
  }
  const seen = new WeakSet();
  new MutationObserver(() => {
    for (const [selector, name] of [['[data-checkout-form]', 'form-visible'], ['.checkout-success', 'success-visible']]) {
      const element = document.querySelector(selector);
      if (!element || seen.has(element) || !element.getBoundingClientRect().width) continue;
      seen.add(element);note(name);
      requestAnimationFrame(() => requestAnimationFrame(() => {
        if (element.isConnected) note(name.replace('visible', 'painted'));
      }));
    }
  }).observe(document, {childList: true, subtree: true});
  window.addEventListener('load', () => requestAnimationFrame(() => requestAnimationFrame(() => note('page-painted'))));
  window.checkoutDProbe = {records, timeOrigin: performance.timeOrigin};
})();
