import { initHtmxEvents } from "./core/htmx-events.js";
import { initSidebar } from "./core/sidebar.js";

document.documentElement.classList.add("js");

const initApp = () => {
  initSidebar();
  initHtmxEvents();
};

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", initApp, { once: true });
} else {
  initApp();
}
