let initialized = false;
const mutating = new Set(["POST", "PUT", "PATCH", "DELETE"]);
const requestElement = (detail) => detail.elt || detail.requestConfig?.elt;
const targetElement = (detail) => detail.target || detail.requestConfig?.target;
const criticalForm = (detail) => requestElement(detail)?.closest?.("[data-nx-critical-form]");
const setBusy = (detail, busy) => {
  const target = targetElement(detail);
  if (!target || target === document.body) return;
  target.classList.toggle("is-loading", busy);
  if (busy) target.setAttribute("aria-busy", "true"); else target.removeAttribute("aria-busy");
};
const setProcessing = (detail, processing) => {
  const form = criticalForm(detail); if (!form) return;
  form.dataset.nxProcessing = String(processing);
  form.closest("[data-nx-modal], [data-nx-drawer]")?.setAttribute("data-nx-processing", String(processing));
  const button = detail.requestConfig?.triggeringEvent?.submitter || form.querySelector('[type="submit"]');
  if (!button) return;
  if (processing) { button.dataset.nxOriginalText = button.textContent; button.disabled = true; if (button.dataset.loadingText) button.textContent = button.dataset.loadingText; }
  else { button.disabled = false; if (button.dataset.nxOriginalText) button.textContent = button.dataset.nxOriginalText; }
};
const feedback = (message, action = "") => {
  const region = document.getElementById("nx-feedback"); if (!region) return;
  region.querySelector("[data-nx-feedback-message]").textContent = message;
  region.querySelector("[data-nx-feedback-action]").textContent = action;
  region.hidden = false;
};
export const initHtmxEvents = () => {
  if (initialized) return;
  document.body.addEventListener("htmx:configRequest", (event) => {
    if (mutating.has(event.detail.verb.toUpperCase())) {
      const token = document.querySelector('meta[name="csrf-token"]')?.content;
      if (token) event.detail.headers["X-CSRFToken"] = token;
    }
  });
  document.body.addEventListener("htmx:beforeRequest", (event) => { setBusy(event.detail, true); setProcessing(event.detail, true); });
  document.body.addEventListener("htmx:afterRequest", (event) => { setBusy(event.detail, false); setProcessing(event.detail, false); });
  document.body.addEventListener("htmx:sendError", (event) => { setBusy(event.detail, false); setProcessing(event.detail, false); feedback("No podemos confirmar el resultado de la operación.", "Comprueba el estado antes de repetir."); });
  document.body.addEventListener("htmx:beforeSwap", (event) => {
    const status = event.detail.xhr.status;
    if (status === 422) { event.detail.shouldSwap = true; event.detail.isError = false; return; }
    const messages = {403: "No tienes permiso para realizar esta acción.", 404: "Este recurso ya no está disponible.", 409: "La información ha cambiado. Actualiza los datos antes de continuar.", 500: "Se ha producido un error inesperado."};
    if (messages[status]) { event.detail.shouldSwap = false; feedback(messages[status]); }
  });
  document.body.addEventListener("htmx:responseError", (event) => { setBusy(event.detail, false); setProcessing(event.detail, false); });
  document.addEventListener("nx:refresh-region", (event) => {
    const selector = event.detail?.selector;
    if (typeof selector !== "string" || !/^#[A-Za-z][\w:.-]*$/.test(selector)) return;
    document.querySelector(selector)?.dispatchEvent(new CustomEvent("nx:refresh", { bubbles: true }));
  });
  document.addEventListener("click", (event) => { if (event.target.closest("[data-nx-feedback-close]")) document.getElementById("nx-feedback").hidden = true; });
  initialized = true;
};
