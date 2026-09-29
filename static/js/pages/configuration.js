const form = document.querySelector(".business-profile-form, form.stacked-form");

if (form) {
  let dirty = false;
  let submitting = false;
  const initial = new FormData(form);
  const tax = form.elements.tax_identifier;
  const stock = form.elements.enable_stock_control;
  const sellWithoutStock = form.elements.allow_sale_without_stock;
  const discounts = form.elements.allow_manual_discounts;
  const maximumDiscount = form.elements.max_manual_discount_percent;
  const receipt = form.elements.receipt_footer;
  const receiptPreview = document.querySelector("[data-receipt-preview]");

  const updateDependencies = () => {
    if (sellWithoutStock && stock) sellWithoutStock.disabled = !stock.checked;
    if (maximumDiscount && discounts) maximumDiscount.disabled = !discounts.checked;
  };
  form.addEventListener("input", () => { dirty = true; updateDependencies(); });
  receipt?.addEventListener("input", () => { receiptPreview.textContent = receipt.value || "Tu mensaje aparecerá aquí."; });
  form.addEventListener("submit", (event) => {
    if (submitting) { event.preventDefault(); return; }
    const sensitive = [];
    if (tax && tax.value !== initial.get("tax_identifier")) sensitive.push(`NIF / CIF\nAntes: ${initial.get("tax_identifier")}\nDespués: ${tax.value}`);
    if (stock && !stock.checked && initial.has("enable_stock_control")) sensitive.push("Desactivar el control de stock hará que las ventas no validen inventario.");
    const cash = form.elements.require_open_cash_register;
    if (cash && !cash.checked && initial.has("require_open_cash_register")) sensitive.push("Las ventas dejarán de exigir una caja abierta.");
    if (sensitive.length && !window.confirm(`Revisa los cambios:\n\n${sensitive.join("\n\n")}`)) { event.preventDefault(); return; }
    submitting = true; dirty = false;
  });
  window.addEventListener("beforeunload", (event) => { if (dirty && !submitting) event.preventDefault(); });
  updateDependencies();
}
