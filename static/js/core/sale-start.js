let initialized = false;

export const initSaleStart = () => {
  if (initialized) return;
  let pending = false;
  document.addEventListener("submit", (event) => {
    const form = event.target;
    if (!form.matches("[data-nx-sale-start]")) return;
    if (pending) {
      event.preventDefault();
      return;
    }
    pending = true;
    document.querySelectorAll("[data-nx-sale-start]").forEach((start) => {
      start.dataset.nxProcessing = "true";
      start.setAttribute("aria-busy", "true");
      start.querySelectorAll("button").forEach((button) => { button.disabled = true; });
    });
  });
  // A back/forward-cache restoration must allow an intentional new sale.
  window.addEventListener("pageshow", () => {
    pending = false;
    document.querySelectorAll("[data-nx-sale-start]").forEach((form) => {
      delete form.dataset.nxProcessing;
      form.removeAttribute("aria-busy");
      form.querySelectorAll("button").forEach((button) => { button.disabled = false; });
    });
  });
  initialized = true;
};
