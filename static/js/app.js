import { initMediaPreview } from "./core/media-preview.js";
import { initHtmxEvents } from "./core/htmx-events.js";
import { initSidebar } from "./core/sidebar.js";
import { initCommandPalette } from "./core/command-palette.js";
import { initModal } from "./core/modal.js";
import { initDrawer } from "./core/drawer.js";
import { initToast } from "./core/toast.js";

document.documentElement.classList.add("js");
const initApp = () => { initSidebar(); initCommandPalette(); initModal(); initDrawer(); initToast(); initHtmxEvents(); initMediaPreview(); };
if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", initApp, { once: true }); else initApp();
