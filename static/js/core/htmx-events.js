let initialized = false;
const mutating = new Set(["POST", "PUT", "PATCH", "DELETE"]);
const requestSurfaces = new WeakMap();
const requestElement = (detail) => detail.elt || detail.requestConfig?.elt;
const targetElement = (detail) => detail.target || detail.requestConfig?.target;
const requestVerb = (detail) => (detail.requestConfig?.verb || detail.verb || "GET").toUpperCase();
const criticalForm = (detail) => requestElement(detail)?.closest?.("[data-nx-critical-form]");
const requestSurface = (detail) => criticalForm(detail)?.closest("[data-nx-modal], [data-nx-drawer]") || targetElement(detail)?.closest?.("[data-nx-modal], [data-nx-drawer]");
const setBusy = (detail, busy) => {
  const target = targetElement(detail);
  if (!target || target === document.body) return;
  target.classList.toggle("is-loading", busy);
  if (busy) target.setAttribute("aria-busy", "true"); else target.removeAttribute("aria-busy");
};
const setProcessing = (detail, processing) => {
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
  else { button.disabled = false; if (button.dataset.nxOriginalText) button.textContent = button.dataset.nxOriginalText; }
};
const feedback = (message, action = "") => {
  const region = document.getElementById("nx-feedback"); if (!region) return;
  const surface = document.querySelector("[data-nx-modal][open], [data-nx-drawer][open]");
  const host = document.querySelector("[data-nx-feedback-host]");
  if (surface) {
    surface.prepend(region);
    region.classList.add("nx-feedback--in-surface");
  } else if (host) {
    host.append(region);
    region.classList.remove("nx-feedback--in-surface");
  }
  region.querySelector("[data-nx-feedback-message]").textContent = message;
  region.querySelector("[data-nx-feedback-action]").textContent = action;
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
const finishRequest = (detail) => { setBusy(detail, false); setProcessing(detail, false); };
export const initHtmxEvents = () => {
  if (initialized) return;
  document.body.addEventListener("htmx:configRequest", (event) => {
    if (mutating.has(event.detail.verb.toUpperCase())) {
      const token = document.querySelector('meta[name="csrf-token"]')?.content;
      if (token) event.detail.headers["X-CSRFToken"] = token;
    }
  });
  document.body.addEventListener("htmx:beforeRequest", (event) => { setBusy(event.detail, true); setProcessing(event.detail, true); });
  document.body.addEventListener("htmx:afterRequest", (event) => finishRequest(event.detail));
  document.body.addEventListener("htmx:sendError", (event) => {
    const uncertain = mutating.has(requestVerb(event.detail)) || Boolean(criticalForm(event.detail));
    finishRequest(event.detail);
    if (uncertain) feedback("No podemos confirmar el resultado de la operación.", "Comprueba el estado antes de repetir.");
    else feedback("No se ha podido cargar la información.", "Comprueba la conexión e inténtalo de nuevo.");
  });
  document.body.addEventListener("htmx:beforeSwap", (event) => {
    const status = event.detail.xhr.status;
    if (status === 422) { event.detail.shouldSwap = true; event.detail.isError = false; return; }
    const messages = {403: "No tienes permiso para realizar esta acción.", 404: "Este recurso ya no está disponible.", 409: "La información ha cambiado. Actualiza los datos antes de continuar."};
    const message = messages[status] || (status >= 500 ? "Se ha producido un error inesperado." : null);
    if (message) { event.detail.shouldSwap = false; feedback(message); }
  });
  document.body.addEventListener("htmx:responseError", (event) => finishRequest(event.detail));
  document.addEventListener("nx:refresh-region", (event) => {
    const selector = event.detail?.selector;
    if (typeof selector !== "string" || !/^#[A-Za-z][\w:.-]*$/.test(selector)) return;
    document.querySelector(selector)?.dispatchEvent(new CustomEvent("nx:refresh", { bubbles: true }));
  });
  document.addEventListener("click", (event) => { if (event.target.closest("[data-nx-feedback-close]")) restoreFeedbackHost({ hide: true }); });
  document.addEventListener("close", (event) => { if (event.target.matches?.("[data-nx-modal], [data-nx-drawer]")) restoreFeedbackHost(); }, true);
  initialized = true;
};
