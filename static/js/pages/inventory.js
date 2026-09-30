function activateRows(root = document) {
  root.querySelectorAll(".inventory-table tr[data-href]").forEach((row) => {
    row.addEventListener("click", (event) => {
      if (!event.target.closest("a,button,input,select")) window.location.assign(row.dataset.href);
    });
    row.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") { event.preventDefault(); window.location.assign(row.dataset.href); }
    });
  });
}
activateRows();
document.addEventListener("htmx:afterSwap", (event) => activateRows(event.target));
const quickForm = document.querySelector("[data-quick-adjustment]");
if (quickForm) {
  const counted = quickForm.querySelector("[name=counted_stock]");
  const system = Number.parseFloat(document.querySelector("#system-stock").textContent.replace(",", "."));
  const preview = document.querySelector("#difference-preview");
  counted.addEventListener("input", () => {
    const difference = Number.parseFloat(counted.value) - system;
    preview.textContent = Number.isFinite(difference) ? `${difference > 0 ? "+" : ""}${difference.toFixed(3)}` : "—";
  });
}
function prepareInventoryFilterDrawer(root = document) {
  const drawer = root.querySelector("#inventory-filter-drawer");
  if (drawer && window.matchMedia("(max-width: 600px)").matches && drawer.open) drawer.close();
}
prepareInventoryFilterDrawer();
document.addEventListener("htmx:afterSwap", (event) => prepareInventoryFilterDrawer(event.target));
