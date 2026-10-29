// UI recovery only: backend services remain authoritative for all economic effects.
const attempts = new WeakMap();
const reads = new WeakMap();
const prefix = 'netxodo:checkout-recovery:v1:';
const allowed = /^(mode|method|cash_received|external_reference|series|cart_version|payment_idempotency_key|billing_idempotency_key|payments-(TOTAL_FORMS|INITIAL_FORMS|MIN_NUM_FORMS|MAX_NUM_FORMS|\d+-(method|amount|cash_received|external_reference|idempotency_key|DELETE)))$/;
const memory = new Map();
const checkoutForm = detail => (detail.elt || detail.requestConfig?.elt)?.closest?.('[data-checkout-form]');
const readKey = checkout => checkout?.dataset.checkoutRecoveryKey;
const load = key => {
  if (!key) return null;
  let raw;
  try { raw = sessionStorage.getItem(prefix + key); } catch { /* Use the current-tab memory fallback when storage is blocked. */ }
  try {
    const saved = memory.get(key) || (raw ? JSON.parse(raw) : null);
    if (!saved) return null;
    if (!Array.isArray(saved.fields) || saved.fields.length > 500 ||
        !saved.fields.every(pair => Array.isArray(pair) && pair.length === 2 && allowed.test(pair[0]) && typeof pair[1] === 'string')) return {damaged: true};
    return saved;
  } catch { return {damaged: true}; }
};
const keep = record => {
  memory.set(record.key, record);
  try { sessionStorage.setItem(prefix + record.key, JSON.stringify(record)); } catch { /* Current DOM and memory still retain this attempt. */ }
};
const forget = key => {
  memory.delete(key);
  try { sessionStorage.removeItem(prefix + key); } catch { /* No economic mutation depends on browser storage. */ }
};
const setUnknown = form => {
  if (!form?.isConnected) return;
  form.dataset.nxUnknown = 'true';
  form.querySelectorAll('[type="submit"]').forEach(button => { button.disabled = true; });
};

export const rememberCheckout = detail => {
  if ((detail.requestConfig?.verb || detail.verb || '').toUpperCase() !== 'POST') {
    const trigger = detail.elt || detail.requestConfig?.elt;
    const key = trigger?.dataset.nxCheckoutStatus || trigger?.dataset.nxCheckoutReadInline;
    const region = document.getElementById('nx-feedback');
    if (key && region) region.dataset.checkoutRecoveryKey = key;
    return;
  }
  const form = checkoutForm(detail);
  if (!form || !detail.xhr) return;
  const key = readKey(form.closest('[data-checkout]'));
  if (!key) return;
  attempts.set(detail.xhr, {
    key,
    action: new URL(form.action, location.href).pathname,
    fields: [...new FormData(form)].filter(([name, value]) => allowed.test(name) && typeof value === 'string'),
    form,
  });
};

export const checkoutUnknown = detail => {
  const attempt = attempts.get(detail.xhr);
  if (!attempt) return null;
  // Persist only the allowlisted intent fields; never CSRF, credentials or cookies.
  const record = {key: attempt.key, action: attempt.action, fields: attempt.fields};
  keep(record);
  setUnknown(attempt.form);
  return record;
};

const offerRead = (region, attempt) => {
  if (!attempt || !region) return;
  region.dataset.checkoutRecoveryKey = attempt.key;
  region.querySelector('[data-nx-checkout-status]')?.remove();
  const button = document.createElement('button');
  button.type = 'button';
  button.className = 'button button-secondary';
  button.textContent = 'CONSULTAR ESTADO';
  button.dataset.nxCheckoutStatus = attempt.key;
  button.setAttribute('hx-get', attempt.action);
  button.setAttribute('hx-target', '#checkout-panel');
  button.setAttribute('hx-swap', 'innerHTML');
  button.setAttribute('hx-sync', 'this:drop');
  button.setAttribute('hx-disabled-elt', 'this');
  region.querySelector('[data-nx-feedback-action]')?.after(button);
  window.htmx?.process(button);
  if (attempt.form?.isConnected && !attempt.form.querySelector('[data-nx-checkout-read-inline]')) {
    const inline = button.cloneNode(true);
    delete inline.dataset.nxCheckoutStatus;
    inline.dataset.nxCheckoutReadInline = attempt.key;
    attempt.form.append(inline);
    window.htmx?.process(inline);
  }
};

export const offerCheckoutRead = (region, detail) => offerRead(region, attempts.get(detail.xhr));

export const resumeCheckoutUncertainty = () => {
  const checkout = document.querySelector('[data-checkout]');
  const key = readKey(checkout);
  const record = load(key);
  if (!record) return false;
  if (checkout.dataset.checkoutComplete === 'true') { forget(key); return false; }
  const form = checkout.querySelector('[data-checkout-form]');
  if (!form) return false;
  // An existing journal makes a reload conservative: no mutation until a read.
  if (!record.damaged) for (const [name, value] of record.fields) {
    if (!name.endsWith('idempotency_key')) continue;
    const input = [...form.elements].find(field => field.name === name);
    if (input) input.value = value;
  }
  setUnknown(form);
  const region = document.getElementById('nx-feedback');
  if (region) {
    region.querySelector('[data-nx-feedback-message]').textContent = 'Hay una operación cuyo resultado debe comprobarse.';
    region.querySelector('[data-nx-feedback-action]').textContent = 'Consulta el estado antes de repetir.';
    region.hidden = false;
    region.dataset.checkoutRecoveryKey = key;
    offerRead(region, {key, action: new URL(form.action, location.href).pathname, form});
  }
  return true;
};

export const prepareCheckoutRead = detail => {
  if (detail.xhr.status !== 200 || detail.target?.id !== 'checkout-panel') return;
  const verb = (detail.requestConfig?.verb || '').toUpperCase();
  if (verb !== 'GET') return;
  const template = document.createElement('template');
  template.innerHTML = detail.serverResponse;
  const checkout = template.content.querySelector('[data-checkout]');
  const key = readKey(checkout);
  if (!key) return;
  const record = load(key);
  if (!record) return;
  if (checkout.dataset.checkoutComplete === 'true') {
    reads.set(detail.xhr, {key, complete: true});
    return;
  }
  const form = checkout.querySelector('[data-checkout-form]');
  if (!form) return;
  const action = new URL(form.action || form.getAttribute('action'), location.href);
  if (record.damaged || action.origin !== location.origin || action.pathname !== record.action) {
    form.hidden = true;
    const warning = document.createElement('p');
    warning.className = 'tpv-errors';
    warning.setAttribute('role', 'alert');
    warning.textContent = 'No se puede recuperar la operación guardada. Consulta la venta y solicita ayuda antes de volver a cobrar.';
    checkout.append(warning);
  } else {
    // Replay the same intent only after an explicit authorized GET. Do not turn
    // a split into a new single payment, rewrite cart_version, or generate UUIDs.
    const csrf = form.querySelector('[name="csrfmiddlewaretoken"]');
    form.replaceChildren(...(csrf ? [csrf] : []));
    for (const [name, value] of record.fields) {
      const input = document.createElement('input');
      input.type = 'hidden'; input.name = name; input.value = value;
      form.append(input);
    }
    const note = document.createElement('p');
    note.className = 'recovery-note';
    const paid = checkout.dataset.paymentStatus === 'paid';
    const partial = checkout.dataset.paymentStatus === 'partial';
    note.textContent = paid ? 'El cobro está confirmado. Solo falta completar la emisión del documento.' :
      partial ? 'Hay un pago parcial confirmado. Se conserva la operación original para recuperar lo pendiente.' :
        'No consta el pago completo en esta lectura. La operación anterior podría seguir procesándose. Puedes volver a consultar o reintentar la misma operación.';
    const button = document.createElement('button');
    button.type = 'submit'; button.className = 'checkout-confirm';
    button.dataset.loadingText = 'Procesando…';
    button.textContent = paid ? 'REINTENTAR EMISIÓN' : 'REINTENTAR OPERACIÓN ORIGINAL';
    form.append(note, button);
  }
  reads.set(detail.xhr, {key, complete: false});
  detail.serverResponse = template.innerHTML;
};

export const checkoutReadFinished = detail => {
  const read = reads.get(detail.xhr);
  if (!read) return false;
  const region = document.getElementById('nx-feedback');
  if (read.complete) {
    forget(read.key);
    if (region?.dataset.checkoutRecoveryKey === read.key) region.querySelector('[data-nx-checkout-status]')?.remove();
  }
  // The read result and any remaining uncertainty are now shown inline. Do not
  // leave a fixed alert over the recovery controls on a small standalone page,
  // or clear another operation's feedback.
  return region?.dataset.checkoutRecoveryKey === read.key;
};

export const checkoutResponseFinished = detail => {
  const attempt = attempts.get(detail.xhr);
  if (!attempt) return;
  const status = detail.xhr.status;
  // A rendered validation/conflict response is known; retain its bound form.
  // A 200 without a confirmed-operation header can still be paid/Billing pending.
  if ((status === 409 && detail.xhr.getResponseHeader('X-Netxodo-Allow-Error-Swap') === 'true') || status === 422 ||
      (status === 200 && detail.xhr.getResponseHeader('X-Netxodo-Confirmed-Operation'))) forget(attempt.key);
  const originalKey = attempt.fields.find(([name]) => name === 'payment_idempotency_key')?.[1];
  const confirmed = status === 200 && originalKey && detail.xhr.getResponseHeader('X-Netxodo-Confirmed-Operation') === originalKey;
  const region = document.getElementById('nx-feedback');
  const ownsFeedback = region?.dataset.checkoutRecoveryKey === attempt.key;
  if (confirmed && ownsFeedback) region.querySelector('[data-nx-checkout-status]')?.remove();
  return Boolean(confirmed && ownsFeedback);
};
