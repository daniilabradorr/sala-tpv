let initialized = false;
const tones = new Set(["success", "info", "warning", "error"]);
export const showToast = (detail = {}) => {
  const region = document.getElementById("nx-toast-region");
  if (!region || typeof detail.message !== "string" || !detail.message.trim()) return;
  const toast = document.createElement("div");
  toast.className = `nx-toast nx-toast--${tones.has(detail.tone) ? detail.tone : "info"}`;
  toast.textContent = detail.message.trim();
  region.append(toast);
  const timeout = Math.min(Math.max(Number(detail.timeout) || 4000, 1000), 10000);
  window.setTimeout(() => toast.remove(), timeout);
};
export const initToast = () => {
  if (initialized) return;
  document.addEventListener("nx:toast", (event) => showToast(event.detail));
  initialized = true;
};
