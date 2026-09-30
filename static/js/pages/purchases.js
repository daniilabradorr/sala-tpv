const isInteractive = (target) => target.closest("a, button, input, select, textarea, form");

document.addEventListener("click", (event) => {
  const choice = event.target.closest("[data-product-choice]");
  if (choice) {
    const form = choice.closest("form");
    const input = form?.querySelector("input[name='product']");
    if (input) input.value = choice.dataset.productId;
    choice.parentElement.querySelectorAll("[data-product-choice]").forEach((item) => {
      const selected = item === choice;
      item.setAttribute("aria-selected", String(selected));
      item.classList.toggle("is-selected", selected);
    });
    return;
  }
  const row = event.target.closest("tr.purchase-row[data-href]");
  if (row && !isInteractive(event.target)) window.location.assign(row.dataset.href);
});

document.addEventListener("keydown", (event) => {
  const row = event.target.closest("tr.purchase-row[data-href]");
  if (!row || isInteractive(event.target) || !["Enter", " "].includes(event.key)) return;
  event.preventDefault();
  window.location.assign(row.dataset.href);
});

document.addEventListener("purchases:supplier-selected", (event) => {
  const select = document.getElementById("id_supplier");
  const id = String(event.detail?.id || "");
  if (!select || !id) return;
  let option = Array.from(select.options).find((item) => item.value === id);
  if (!option) {
    option = new Option(event.detail?.name || "Proveedor", id);
    select.add(option);
  }
  select.value = id;
  select.dispatchEvent(new Event("change", { bubbles: true }));
});
