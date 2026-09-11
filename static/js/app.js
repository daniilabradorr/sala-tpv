document.documentElement.classList.add("js");

document.addEventListener("DOMContentLoaded", () => {
  const shell = document.querySelector("[data-app-shell]");
  const sidebar = document.querySelector("[data-sidebar]");
  const toggle = document.querySelector("[data-sidebar-toggle]");
  const closeButton = document.querySelector("[data-sidebar-close]");
  const overlay = document.querySelector("[data-sidebar-overlay]");

  if (!shell || !sidebar || !toggle || !overlay) return;

  const closeSidebar = ({ restoreFocus = true } = {}) => {
    document.body.classList.remove("sidebar-open");
    toggle.setAttribute("aria-expanded", "false");
    toggle.setAttribute("aria-label", "Abrir menú");
    overlay.hidden = true;
    if (restoreFocus) toggle.focus();
  };

  const openSidebar = () => {
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
    if (event.key === "Escape" && document.body.classList.contains("sidebar-open")) {
      closeSidebar();
    }
  });
  window.addEventListener("resize", () => {
    if (window.innerWidth > 900 && document.body.classList.contains("sidebar-open")) {
      closeSidebar({ restoreFocus: false });
    }
  });
});

document.body.addEventListener("htmx:responseError", (event) => {
  console.error("HTMX response error:", event.detail);
});
