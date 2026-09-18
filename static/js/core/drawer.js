let initialized = false;
const triggers = new WeakMap();
const closeDrawer = (drawer) => {
  if (!drawer?.open || drawer.dataset.nxProcessing === "true") return;
  drawer.close();
};
export const initDrawer = () => {
  if (initialized) return;
  document.addEventListener("click", (event) => {
    const trigger = event.target.closest("[data-nx-drawer-trigger]");
    if (trigger) {
      const drawer = document.getElementById(trigger.dataset.nxDrawerTrigger);
      if (drawer?.showModal) { triggers.set(drawer, trigger); drawer.showModal(); }
    }
    const close = event.target.closest("[data-nx-drawer-close]");
    if (close) closeDrawer(close.closest("[data-nx-drawer]"));
  });
  document.addEventListener("cancel", (event) => {
    if (event.target.matches("[data-nx-drawer]") && event.target.dataset.nxProcessing === "true") event.preventDefault();
  }, true);
  document.addEventListener("close", (event) => {
    if (!event.target.matches("[data-nx-drawer]")) return;
    const trigger = triggers.get(event.target); if (trigger?.isConnected) trigger.focus();
  }, true);
  document.addEventListener("nx:close-drawer", (event) => {
    const id = event.detail?.id;
    closeDrawer(id ? document.getElementById(id) : document.querySelector("[data-nx-drawer][open]"));
  });
  initialized = true;
};
