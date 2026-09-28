const syncActiveTab = (root = document) => {
  const workspace = root.querySelector?.("#reports-workspace") || document.querySelector("#reports-workspace");
  const field = document.querySelector("#reports-active-tab");
  if (workspace?.dataset.activeTab && field) field.value = workspace.dataset.activeTab;
};

document.addEventListener("click", (event) => {
  const tab = event.target.closest?.("[data-report-tab]");
  const field = document.querySelector("#reports-active-tab");
  if (tab && field) field.value = tab.dataset.reportTab;
});
document.addEventListener("htmx:afterSwap", (event) => syncActiveTab(event.detail.target));
document.addEventListener("DOMContentLoaded", () => syncActiveTab());
