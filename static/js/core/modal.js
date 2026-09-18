let initialized = false;
const triggers = new WeakMap();
const isProcessing = (dialog) => dialog.dataset.nxProcessing === "true";
export const closeModal = (dialog) => {
  if (!dialog?.open || isProcessing(dialog)) return false;
  dialog.close();
  return true;
};
export const openModal = (dialog, trigger) => {
  if (!dialog?.showModal) return;
  triggers.set(dialog, trigger || document.activeElement);
  if (!dialog.open) dialog.showModal();
};
export const initModal = () => {
  if (initialized) return;
  document.addEventListener("click", (event) => {
    const trigger = event.target.closest("[data-nx-modal-trigger], [data-checkout-open]");
    if (trigger) openModal(document.getElementById(trigger.dataset.nxModalTrigger || "checkout-dialog"), trigger);
    const close = event.target.closest("[data-nx-modal-close]");
    if (close) closeModal(close.closest("[data-nx-modal]"));
  });
  document.addEventListener("cancel", (event) => {
    if (event.target.matches("[data-nx-modal]") && isProcessing(event.target)) event.preventDefault();
  }, true);
  document.addEventListener("close", (event) => {
    if (!event.target.matches("[data-nx-modal]")) return;
    const trigger = triggers.get(event.target);
    if (trigger?.isConnected) trigger.focus();
  }, true);
  document.addEventListener("nx:close-modal", (event) => {
    const id = event.detail?.id;
    closeModal(id ? document.getElementById(id) : document.querySelector("[data-nx-modal][open]"));
  });
  initialized = true;
};
