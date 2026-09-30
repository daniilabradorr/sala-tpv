let initialized = false;

export const initSidebar = () => {
  if (initialized) return;

  const shell = document.querySelector("[data-app-shell]");
  const sidebar = document.querySelector("[data-sidebar]");
  const toggle = document.querySelector("[data-sidebar-toggle]");
  const closeButton = document.querySelector("[data-sidebar-close]");
  const overlay = document.querySelector("[data-sidebar-overlay]");

  if (!shell || !sidebar || !toggle || !overlay) return;

  const workspace = shell.querySelector(".erp-workspace");
  const focusableSelector =
    'a[href], button:not([disabled]), input:not([disabled]):not([type="hidden"]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';
  const drawerMedia = window.matchMedia("(max-width: 1199px)");
  const isDrawer = () => drawerMedia.matches;

  const syncClosedState = () => {
    sidebar.inert =
      isDrawer() && !document.body.classList.contains("sidebar-open");
  };

  const closeSidebar = ({ restoreFocus = true } = {}) => {
    document.body.classList.remove("sidebar-open");
    toggle.setAttribute("aria-expanded", "false");
    toggle.setAttribute("aria-label", "Abrir menú");
    overlay.hidden = true;
    sidebar.inert = isDrawer();
    if (workspace) workspace.inert = false;
    if (restoreFocus) toggle.focus();
  };

  const openSidebar = () => {
    sidebar.inert = false;
    if (workspace) workspace.inert = true;
    document.body.classList.add("sidebar-open");
    toggle.setAttribute("aria-expanded", "true");
    toggle.setAttribute("aria-label", "Cerrar menú");
    overlay.hidden = false;
    const firstLink = sidebar.querySelector("a");
    if (firstLink) firstLink.focus();
  };

  toggle.addEventListener("click", () => {
    if (document.body.classList.contains("sidebar-open")) closeSidebar();
    else openSidebar();
  });
  closeButton?.addEventListener("click", () => closeSidebar());
  overlay.addEventListener("click", () => closeSidebar());
  document.addEventListener("keydown", (event) => {
    if (
      event.key === "Escape" &&
      document.body.classList.contains("sidebar-open")
    ) {
      closeSidebar();
      return;
    }
    if (
      event.key === "Tab" &&
      isDrawer() &&
      document.body.classList.contains("sidebar-open")
    ) {
      const focusable = [...sidebar.querySelectorAll(focusableSelector)].filter(
        (element) => element.getClientRects().length > 0,
      );
      if (!focusable.length) return;
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    }
  });
  const handleBreakpoint = () => {
    if (!isDrawer() && document.body.classList.contains("sidebar-open")) {
      closeSidebar({ restoreFocus: false });
    }
    syncClosedState();
    if (!isDrawer()) {
      sidebar.inert = false;
      if (workspace) workspace.inert = false;
      overlay.hidden = true;
    }
  };
  drawerMedia.addEventListener("change", handleBreakpoint);
  syncClosedState();
  initialized = true;
};
