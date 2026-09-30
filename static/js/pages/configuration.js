import { openModal } from "../core/modal.js";

const form = document.querySelector(".business-profile-form, form.stacked-form");

if (form) {
  const persistedNode = document.querySelector("#configuration-persisted");
  const persisted = persistedNode ? JSON.parse(persistedNode.textContent) : {};
  const reviewDialog = document.querySelector("#configuration-review-dialog");
  const discardDialog = document.querySelector("#configuration-discard-dialog");
  const pendingCount = document.querySelector("[data-pending-count]");
  const reviewButton = document.querySelector("[data-review-changes]");
  let dirty = false;
  let confirmed = false;
  let discardTarget = null;

  const tax = form.elements.tax_identifier;
  const stock = form.elements.enable_stock_control;
  const sellWithoutStock = form.elements.allow_sale_without_stock;
  const discounts = form.elements.allow_manual_discounts;
  const maximumDiscount = form.elements.max_manual_discount_percent;
  const receipt = form.elements.receipt_footer;
  const logoUpload = form.elements.logo_upload;
  const removeLogo = form.elements.remove_logo;
  const receiptPreview = document.querySelector("[data-receipt-preview]");
  const asBoolean = (value) => value === "True" || value === true;
  const display = (value) => value === true ? "Sí" : value === false ? "No" : String(value || "—");

  const currentValue = (control) => {
    if (control.type === "checkbox") return control.checked;
    return control.value;
  };
  const originalValue = (control) => control.type === "checkbox"
    ? asBoolean(persisted[control.name])
    : String(persisted[control.name] ?? "");
  const labelFor = (control) => form.querySelector(`label[for="${control.id}"]`)?.textContent.trim() || control.name;
  const changes = () => {
    const items = Array.from(form.elements)
      .filter((control) => control.name && Object.hasOwn(persisted, control.name) && currentValue(control) !== originalValue(control))
      .map((control) => ({ name: control.name, label: labelFor(control), before: originalValue(control), after: currentValue(control) }));
    if (discounts && maximumDiscount && !discounts.checked && String(persisted.max_manual_discount_percent) !== "0.00") {
      const existingMaximum = items.findIndex(({ name }) => name === maximumDiscount.name);
      if (existingMaximum >= 0) items.splice(existingMaximum, 1);
      items.push({ name: maximumDiscount.name, label: labelFor(maximumDiscount), before: persisted.max_manual_discount_percent, after: "0.00" });
    }
    if (logoUpload?.files.length) {
      items.push({ name: "logo", label: "Logo", before: persisted.logo_present ? "Logo actual" : "Sin logo", after: "Nuevo archivo" });
    } else if (removeLogo?.checked) {
      items.push({ name: "logo", label: "Logo", before: persisted.logo_present ? "Logo actual" : "Sin logo", after: "Eliminar logo" });
    }
    return items;
  };

  const updateDependencies = () => {
    if (sellWithoutStock && stock) sellWithoutStock.disabled = !stock.checked;
    if (maximumDiscount && discounts) maximumDiscount.disabled = !discounts.checked;
  };
  const renderChanges = () => {
    const items = changes();
    dirty = items.length > 0;
    if (pendingCount) pendingCount.textContent = `${items.length} ${items.length === 1 ? "cambio pendiente" : "cambios pendientes"}`;
    if (reviewButton) reviewButton.disabled = !items.length;
    const list = reviewDialog?.querySelector("[data-change-list]");
    if (list) {
      list.replaceChildren(...items.map(({ name, label, before, after }) => {
        const row = document.createElement("dl");
        row.className = "change-review-row";
        const wrapper = document.createElement("div");
        const term = document.createElement("dt");
        term.textContent = label;
        const value = (prefix, content) => {
          const detail = document.createElement("dd");
          const strong = document.createElement("strong");
          strong.textContent = prefix;
          detail.append(strong, ` ${display(content)}`);
          return detail;
        };
        wrapper.append(term, value("Antes:", before), value("Después:", after));
        const warnings = {
          enable_stock_control: "Desactivar el control de stock hará que las ventas no validen inventario.",
          require_open_cash_register: "Las ventas dejarán de exigir una caja abierta.",
        };
        const warning = warnings[name];
        if (warning && after === false && before === true) {
          const explanation = document.createElement("p");
          explanation.className = "fiscal-warning";
          explanation.textContent = warning;
          wrapper.append(explanation);
        }
        row.append(wrapper);
        return row;
      }));
    }
    return items;
  };

  form.addEventListener("input", () => { updateDependencies(); renderChanges(); });
  receipt?.addEventListener("input", () => { receiptPreview.textContent = receipt.value || "Tu mensaje aparecerá aquí."; });
  reviewButton?.addEventListener("click", () => { renderChanges(); openModal(reviewDialog, reviewButton); });
  form.addEventListener("submit", (event) => {
    if (confirmed) { dirty = false; return; }
    if (!renderChanges().length) return;
    event.preventDefault();
    openModal(reviewDialog, event.submitter);
  });
  document.querySelector("[data-confirm-changes]")?.addEventListener("click", () => {
    confirmed = true;
    dirty = false;
    form.requestSubmit();
  });
  document.addEventListener("click", (event) => {
    const link = event.target.closest("a[href]");
    if (!link || !dirty || link.target === "_blank") return;
    event.preventDefault();
    discardTarget = link.href;
    openModal(discardDialog, link);
  });
  document.querySelector("[data-discard-changes]")?.addEventListener("click", () => {
    dirty = false;
    if (discardTarget) window.location.assign(discardTarget);
  });
  window.addEventListener("beforeunload", (event) => { if (dirty && !confirmed) event.preventDefault(); });
  updateDependencies();
  renderChanges();
}
