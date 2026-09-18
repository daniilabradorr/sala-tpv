import { initHtmxEvents } from "./core/htmx-events.js";
import { initSidebar } from "./core/sidebar.js";
import { initCommandPalette } from "./core/command-palette.js";
import { initStoreSwitcher } from "./core/store-switcher.js";

document.documentElement.classList.add("js");

const initApp = () => {
  initSidebar();
  initCommandPalette();
  initStoreSwitcher();
  initHtmxEvents();
};

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", initApp, { once: true });
} else {
  initApp();
}
