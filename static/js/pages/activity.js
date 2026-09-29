const mobile = window.matchMedia("(max-width: 767px)");

const initializeFilterPanel = (root = document) => {
  const panel = root.querySelector?.(".activity-filter-panel");
  if (!panel || panel.dataset.activityReady === "true") return;
  panel.dataset.activityReady = "true";
  const trigger = panel.querySelector("summary");
  const close = panel.querySelector("[data-activity-filter-close]");
  if (mobile.matches) panel.open = false;
  panel.addEventListener("toggle", () => {
    if (mobile.matches && panel.open) {
      panel.querySelector("input, select, button")?.focus();
    }
  });
  close?.addEventListener("click", () => {
    panel.open = false;
    trigger?.focus();
  });
  panel.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && mobile.matches && panel.open) {
      event.preventDefault();
      panel.open = false;
      trigger?.focus();
    }
  });
};

initializeFilterPanel();
mobile.addEventListener("change", () => {
  const panel = document.querySelector(".activity-filter-panel");
  if (panel && !mobile.matches) panel.open = true;
});
document.addEventListener("htmx:afterSwap", (event) =>
  initializeFilterPanel(event.detail.target),
);
