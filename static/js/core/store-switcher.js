let initialized = false;

export const initStoreSwitcher = () => {
  if (initialized) return;
  const trigger = document.querySelector("[data-store-trigger]");
  const dialog = document.querySelector("[data-store-dialog]");
  const close = dialog?.querySelector("[data-store-close]");
  if (!trigger || !dialog || !close) return;
  trigger.addEventListener("click", () => dialog.showModal());
  close.addEventListener("click", () => dialog.close());
  dialog.addEventListener("close", () => trigger.focus());
  initialized = true;
};
