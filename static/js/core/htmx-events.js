import { rememberCheckout, checkoutUnknown, offerCheckoutRead, prepareCheckoutRead, checkoutReadFinished, checkoutResponseFinished, resumeCheckoutUncertainty } from "./checkout-recovery.js";

let initialized = false;
const mutating = new Set(["POST", "PUT", "PATCH", "DELETE"]);
const requestSurfaces = new WeakMap();
// Ownership is visual only. Never cancel an economic POST or infer rollback.
const checkoutPanels = new WeakMap();
const checkoutRequests = new WeakMap();
const requestElement = (detail) => detail.elt || detail.requestConfig?.elt;
const targetElement = (detail) => detail.target || detail.requestConfig?.target;
const requestVerb = (detail) => (detail.requestConfig?.verb || detail.verb || "GET").toUpperCase();
const beginCheckoutRequest = (event) => {
  const detail = event.detail, target = targetElement(detail);
  if (target?.id !== "checkout-panel") return true;
  const previous = checkoutPanels.get(target);
  const mutation = mutating.has(requestVerb(detail));
  if (previous?.processing || (mutation && target.querySelector('[data-checkout-form][data-nx-unknown="true"]'))) {
    event.preventDefault();
    return false;
  }
  const revision = (previous?.revision || 0) + 1;
  checkoutPanels.set(target, { revision, processing: mutation });
  checkoutRequests.set(detail.xhr, { target, revision });
  // Bounded browser waiting; timeout still means an unknown server outcome.
  // Existing explicit per-request deadlines take precedence.
  if (mutation && !detail.xhr.timeout) detail.xhr.timeout = 60000;
  return true;
};
const staleCheckoutRequest = (detail) => {
  const request = checkoutRequests.get(detail.xhr);
  if (!request) return targetElement(detail)?.id === "checkout-panel";
  return !request.target.isConnected || checkoutPanels.get(request.target)?.revision !== request.revision;
};
const criticalForm = (detail) => requestElement(detail)?.closest?.("[data-nx-critical-form]");
const requestSurface = (detail) => criticalForm(detail)?.closest("[data-nx-modal], [data-nx-drawer]") || targetElement(detail)?.closest?.("[data-nx-modal], [data-nx-drawer]");
const setBusy = (detail, busy) => {
  const target = targetElement(detail);
  if (!target || target === document.body) return;
  target.classList.toggle("is-loading", busy);
  if (busy) target.setAttribute("aria-busy", "true"); else target.removeAttribute("aria-busy");
};
const setProcessing = (detail, processing) => {
  if (!mutating.has(requestVerb(detail))) return;
  const form = criticalForm(detail);
  const xhr = detail.xhr;
  let surface = requestSurface(detail);
  if (processing && xhr && surface) requestSurfaces.set(xhr, surface);
  if (!surface && xhr) surface = requestSurfaces.get(xhr);
  if (form?.isConnected) form.dataset.nxProcessing = String(processing);
  if (surface?.isConnected) {
    if (processing) surface.dataset.nxProcessing = "true";
    else surface.removeAttribute("data-nx-processing");
  }
  const button = detail.requestConfig?.triggeringEvent?.submitter || form?.querySelector('[type="submit"]');
  if (!button?.isConnected) return;
  if (processing) { button.dataset.nxOriginalText = button.textContent; button.disabled = true; if (button.dataset.loadingText) button.textContent = button.dataset.loadingText; }
  else { button.disabled = form?.dataset.nxUnknown === "true"; if (button.dataset.nxOriginalText) button.textContent = button.dataset.nxOriginalText; }
};
const resolvedRequestSurface = (detail) =>
  requestSurface(detail) || (detail.xhr ? requestSurfaces.get(detail.xhr) : null);
const feedback = (message, action = "", surface = null, operation = "") => {
  const region = document.getElementById("nx-feedback"); if (!region) return;
  const host = document.querySelector("[data-nx-feedback-host]");
  region.querySelector("[data-nx-checkout-status]")?.remove();
  delete region.dataset.checkoutRecoveryKey;
  if (surface?.isConnected) {
    surface.prepend(region);
    region.classList.add("nx-feedback--in-surface");
  } else if (host) {
    host.append(region);
    region.classList.remove("nx-feedback--in-surface");
  }
  region.querySelector("[data-nx-feedback-message]").textContent = message;
  region.querySelector("[data-nx-feedback-action]").textContent = action;
  region.dataset.operation = operation;
  region.dataset.surface = surface?.id || "";
  region.hidden = false;
};
const restoreFeedbackHost = ({ hide = false } = {}) => {
  const region = document.getElementById("nx-feedback");
  const host = document.querySelector("[data-nx-feedback-host]");
  if (!region || !host) return;
  if (hide) region.hidden = true;
  host.append(region);
  region.classList.remove("nx-feedback--in-surface");
};
const finishRequest = (detail) => {
  if (staleCheckoutRequest(detail)) return;
  setBusy(detail, false); setProcessing(detail, false);
  const request = checkoutRequests.get(detail.xhr);
  if (request) checkoutPanels.get(request.target).processing = false;
};
export const initHtmxEvents = () => {
  if (initialized) return;
  document.addEventListener("submit", (event) => {
    if (event.target.matches("[data-nx-critical-form]") && (event.target.dataset.nxProcessing === "true" || event.target.dataset.nxUnknown === "true")) {
      event.preventDefault();
      event.stopImmediatePropagation();
    }
  }, true);
  document.body.addEventListener("htmx:configRequest", (event) => {
    // UX hint only: the server never uses this header as authentication authority.
    if (document.querySelector("[data-app-shell]")) {
      event.detail.headers["X-Netxodo-Authenticated-Shell"] = "1";
    }
    if (mutating.has(event.detail.verb.toUpperCase())) {
      const token = document.querySelector('meta[name="csrf-token"]')?.content;
      if (token) event.detail.headers["X-CSRFToken"] = token;
    }
  });
  document.body.addEventListener("htmx:beforeRequest", (event) => {
    if (!beginCheckoutRequest(event)) return;
    rememberCheckout(event.detail); setBusy(event.detail, true); setProcessing(event.detail, true);
  });
  document.body.addEventListener("htmx:afterRequest", (event) => { finishRequest(event.detail); checkoutResponseFinished(event.detail); });
  document.body.addEventListener("htmx:afterSwap", (event) => {
    if (checkoutReadFinished(event.detail) || checkoutResponseFinished(event.detail)) restoreFeedbackHost({ hide: true });
    const confirmed = event.detail.xhr?.getResponseHeader("X-Netxodo-Confirmed-Operation");
    const region = document.getElementById("nx-feedback");
    const surface = resolvedRequestSurface(event.detail);
    if (confirmed && region?.dataset.operation === confirmed
        && region.dataset.surface === surface?.id) restoreFeedbackHost({ hide: true });
  });
  const transportError = (event) => {
    if (staleCheckoutRequest(event.detail)) {
      // Retain a disconnected POST's identity without replacing newer feedback.
      if (mutating.has(requestVerb(event.detail))) checkoutUnknown(event.detail);
      return;
    }
    const uncertain = mutating.has(requestVerb(event.detail)) || Boolean(criticalForm(event.detail));
    const surface = resolvedRequestSurface(event.detail);
    finishRequest(event.detail);
    if (uncertain) feedback("No podemos confirmar el resultado de la operación.", "Comprueba el estado antes de repetir.", surface,
      String(event.detail.requestConfig?.parameters?.payment_idempotency_key || ""));
    else feedback("No se ha podido cargar la información.", "Comprueba la conexión e inténtalo de nuevo.", surface);
    if (uncertain) {
      checkoutUnknown(event.detail);
      offerCheckoutRead(document.getElementById("nx-feedback"), event.detail);
    }
  };
  for (const type of ["htmx:sendError", "htmx:timeout", "htmx:sendAbort"]) document.body.addEventListener(type, transportError);
  document.body.addEventListener("htmx:beforeSwap", (event) => {
    if (staleCheckoutRequest(event.detail)) {
      event.detail.shouldSwap = false; event.detail.isError = false;
      return;
    }
    prepareCheckoutRead(event.detail);
    const status = event.detail.xhr.status;
    if (status === 422) { event.detail.shouldSwap = true; event.detail.isError = false; return; }
    if (status === 409 && event.detail.xhr.getResponseHeader("X-Netxodo-Allow-Error-Swap") === "true") {
      event.detail.shouldSwap = true; event.detail.isError = false; return;
    }
    const messages = {403: "No tienes permiso para realizar esta acción.", 404: "Este recurso ya no está disponible.", 409: "La información ha cambiado. Actualiza los datos antes de continuar."};
    const message = messages[status] || (status >= 500 ? "Se ha producido un error inesperado." : null);
    if (message) {
      event.detail.shouldSwap = false;
      const uncertain = status >= 500 && mutating.has(requestVerb(event.detail));
      feedback(uncertain ? "No podemos confirmar el resultado de la operación." : message,
        uncertain ? "Comprueba el estado antes de repetir." : "", resolvedRequestSurface(event.detail),
        uncertain ? String(event.detail.requestConfig?.parameters?.payment_idempotency_key || "") : "");
      if (uncertain) {
        checkoutUnknown(event.detail);
        offerCheckoutRead(document.getElementById("nx-feedback"), event.detail);
      }
    }
  });
  document.body.addEventListener("htmx:responseError", (event) => finishRequest(event.detail));
  document.addEventListener("nx:refresh-region", (event) => {
    const selector = event.detail?.selector;
    if (typeof selector !== "string" || !/^#[A-Za-z][\w:.-]*$/.test(selector)) return;
    document.querySelector(selector)?.dispatchEvent(new CustomEvent("nx:refresh", { bubbles: true }));
  });
  document.addEventListener("click", (event) => { if (event.target.closest("[data-nx-feedback-close]")) restoreFeedbackHost({ hide: true }); });
  document.addEventListener("close", (event) => { if (event.target.matches?.("[data-nx-modal], [data-nx-drawer]")) restoreFeedbackHost(); }, true);
  resumeCheckoutUncertainty();
  initialized = true;
};
