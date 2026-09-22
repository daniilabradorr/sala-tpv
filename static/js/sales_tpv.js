(() => {
  const workspace = () => document.querySelector(".tpv");

  function syncCustomer(root = document) {
    const header = root.querySelector("#workspace-header");
    if (!header) return;
    const mode = header.querySelector('[name="customer_mode"]:checked')?.value;
    const field = header.querySelector(".customer-field");
    if (!field) return;
    field.hidden = mode !== "customer";
    if (mode !== "customer") field.querySelector("select").value = "";
  }

  function syncCartSummary() {
    const root = workspace();
    const cart = root?.querySelector("#sale-cart");
    const countOutput = root?.querySelector("[data-cart-count]");
    const totalOutput = root?.querySelector("[data-cart-total]");
    if (!cart || !countOutput || !totalOutput) return;
    countOutput.textContent =
      cart.querySelector(".cart-heading > span")?.textContent.match(/\d+/)?.[0] || "0";
    totalOutput.textContent = cart.querySelector(".grand-total dd")?.textContent || "0,00 €";
  }

  function normalizeResponsiveTicket() {
    const cart = document.querySelector("#sale-cart");
    if (
      cart?.open &&
      matchMedia("(max-width: 1199px)").matches &&
      !cart.matches(":modal")
    ) {
      cart.close();
    }
  }

  const money = (value) => `${value.toFixed(2).replace(".", ",")} €`;

  function pendingAmount(checkout) {
    return Number(String(checkout.dataset.pending || "0").replace(",", ".")) || 0;
  }

  function syncCheckoutMode(checkout) {
    const split = checkout.querySelector('[name="mode"]:checked')?.value === "split";
    const singlePanel = checkout.querySelector("[data-single-payment]");
    const splitPanel = checkout.querySelector("[data-split-payment]");
    if (singlePanel) singlePanel.hidden = split;
    if (splitPanel) splitPanel.hidden = !split;
  }

  function methodCodes(checkout) {
    return new Map(
      [...checkout.querySelectorAll('[name="method"][data-method-code]')].map((input) => [
        input.value,
        input.dataset.methodCode,
      ]),
    );
  }

  function syncPaymentMethodFields(checkout) {
    const selected = checkout.querySelector('[name="method"]:checked');
    const cash = selected?.dataset.methodCode === "cash";
    const cashFields = checkout.querySelector("[data-cash-fields]");
    if (cashFields) cashFields.hidden = !cash;
    const reference = checkout.querySelector("[data-single-reference]");
    if (reference) reference.hidden = !selected || cash;

    const codes = methodCodes(checkout);
    checkout.querySelectorAll("[data-split-part]:not([hidden])").forEach((part) => {
      const code = codes.get(part.querySelector("[data-split-method]")?.value);
      const partCash = part.querySelector("[data-part-cash]");
      const partReference = part.querySelector("[data-part-reference]");
      if (partCash) partCash.hidden = code !== "cash";
      if (partReference) partReference.hidden = !code || code === "cash";
    });
  }

  function updateCashChange(checkout) {
    const received = Number(checkout.querySelector('[name="cash_received"]')?.value || 0);
    const output = checkout.querySelector("[data-cash-change]");
    if (output) output.textContent = money(Math.max(received - pendingAmount(checkout), 0));
  }

  function updateSplitSummary(checkout) {
    const assigned = [...checkout.querySelectorAll('[data-split-part]:not([hidden]) [name$="-amount"]')]
      .reduce((sum, input) => sum + Number(input.value || 0), 0);
    const remaining = pendingAmount(checkout) - assigned;
    const assignedOutput = checkout.querySelector("[data-split-assigned]");
    const remainingOutput = checkout.querySelector("[data-split-remaining]");
    if (assignedOutput) assignedOutput.textContent = money(assigned);
    if (remainingOutput) {
      remainingOutput.textContent = money(remaining);
      remainingOutput.classList.toggle("is-negative", remaining < 0);
    }
  }

  function syncSplitParts(checkout) {
    const visible = [...checkout.querySelectorAll("[data-split-part]:not([hidden])")];
    visible.forEach((part, index) => {
      part.querySelector("[data-part-number]").textContent = index + 1;
      part.querySelector("[data-remove-part]").hidden = visible.length <= 2;
      const deletion = part.querySelector('[name$="-DELETE"]');
      if (deletion) deletion.checked = false;
    });
    checkout.querySelectorAll("[data-split-part][hidden]").forEach((part) => {
      const deletion = part.querySelector('[name$="-DELETE"]');
      if (deletion) deletion.checked = true;
    });
    const add = checkout.querySelector("[data-add-part]");
    if (add) add.hidden = !checkout.querySelector("[data-split-part][hidden]");
    syncPaymentMethodFields(checkout);
    updateSplitSummary(checkout);
  }

  function initializeCheckout(checkout) {
    if (checkout.dataset.checkoutReady) return;
    checkout.dataset.checkoutReady = "true";
    syncCheckoutMode(checkout);
    syncPaymentMethodFields(checkout);
    updateCashChange(checkout);
    syncSplitParts(checkout);
  }

  document.addEventListener("change", (event) => {
    if (event.target.name === "customer_mode") syncCustomer();
    const checkout = event.target.closest(".checkout");
    if (!checkout) return;
    syncCheckoutMode(checkout);
    syncPaymentMethodFields(checkout);
    updateCashChange(checkout);
    updateSplitSummary(checkout);
  });

  document.addEventListener("input", (event) => {
    const checkout = event.target.closest(".checkout");
    if (checkout) {
      updateCashChange(checkout);
      updateSplitSummary(checkout);
    }
  });

  document.addEventListener("click", (event) => {
    const cashQuick = event.target.closest("[data-cash-quick]");
    if (cashQuick) {
      const checkout = cashQuick.closest(".checkout");
      const input = checkout.querySelector('[name="cash_received"]');
      input.value = cashQuick.dataset.cashQuick === "exact" ? pendingAmount(checkout).toFixed(2) : cashQuick.dataset.cashQuick;
      input.dispatchEvent(new Event("input", { bubbles: true }));
      input.focus();
      return;
    }
    const addPart = event.target.closest("[data-add-part]");
    if (addPart) {
      const checkout = addPart.closest(".checkout");
      const part = checkout.querySelector("[data-split-part][hidden]");
      if (part) part.hidden = false;
      syncSplitParts(checkout);
      part?.querySelector("select")?.focus();
      return;
    }
    const removePart = event.target.closest("[data-remove-part]");
    if (removePart) {
      const checkout = removePart.closest(".checkout");
      const part = removePart.closest("[data-split-part]");
      part.hidden = true;
      part.querySelectorAll("input:not([type=hidden]), select").forEach((field) => { field.value = ""; });
      syncSplitParts(checkout);
      checkout.querySelector("[data-add-part]")?.focus();
      return;
    }
    const category = event.target.closest("[data-category-value]");
    if (category) {
      const form = category.closest("form");
      form.querySelector('[name="category"]').value = category.dataset.categoryValue;
      form.requestSubmit();
      return;
    }
    const button = event.target.closest("[data-quantity-step]");
    if (!button) return;
    const form = button.closest("form");
    const input = form.querySelector('[name="quantity"]');
    const next = Number(input.value) + Number(button.dataset.quantityStep);
    if (next <= 0) return;
    input.value = next.toFixed(3);
    form.requestSubmit();
  });

  document.addEventListener("htmx:afterSwap", () => {
    syncCustomer();
    syncCartSummary();
    normalizeResponsiveTicket();
    document.querySelectorAll("[data-checkout]").forEach(initializeCheckout);
  });

  document.addEventListener("htmx:oobAfterSwap", () => {
    syncCartSummary();
    normalizeResponsiveTicket();
  });

  if (matchMedia("(min-width: 768px)").matches) {
    document.querySelector("[data-tpv-search]")?.focus();
  }
  syncCustomer();
  syncCartSummary();
  normalizeResponsiveTicket();
  document.querySelectorAll("[data-checkout]").forEach(initializeCheckout);
})();
