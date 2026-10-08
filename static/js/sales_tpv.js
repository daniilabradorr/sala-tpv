(() => {
  const workspace = () => document.querySelector(".tpv");

  // Absolute quantities share one queue owner that survives cart-content swaps.
  // Keep the old forms connected until the final queued intent is answered.
  let cartRevision = 0;
  const cartRequests = new WeakMap();
  document.addEventListener("submit", (event) => {
    if (event.target.matches('#sale-cart form, .line-editor form, .product-grid form')) {
      event.cartRevision = ++cartRevision;
    }
  }, true);
  document.addEventListener("htmx:beforeRequest", (event) => {
    const revision = event.detail.requestConfig?.triggeringEvent?.cartRevision;
    if (revision !== undefined) cartRequests.set(event.detail.xhr, revision);
  });
  document.addEventListener("htmx:beforeSwap", (event) => {
    const revision = cartRequests.get(event.detail.xhr);
    if (revision !== undefined && revision < cartRevision) event.detail.shouldSwap = false;
  });

  function saveQuantity(input) {
    const form = input.closest("form");
    // A swap can blur the old input and fire change after Enter already saved it.
    // Never submit a form whose HTMX listeners are being removed.
    if (!form?.isConnected || form.dataset.quantityRemoving || form.dataset.quantitySubmitted === input.value) return;
    form.dataset.quantitySubmitted = input.value;
    form.requestSubmit();
  }
  document.addEventListener("htmx:beforeCleanupElement", (event) => {
    if (event.detail.elt.matches?.(".quantity-form")) event.detail.elt.dataset.quantityRemoving = "true";
  });
  document.addEventListener("htmx:afterRequest", (event) => {
    if (event.detail.xhr.status === 0 || event.detail.xhr.status >= 500) {
      delete event.detail.elt.dataset.quantitySubmitted;
    }
  });
  document.addEventListener("change", (event) => {
    if (event.target.matches('.quantity-form [name="quantity"]')) saveQuantity(event.target);
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && event.target.matches('.quantity-form [name="quantity"]')) {
      event.preventDefault();
      saveQuantity(event.target);
    }
  });

  // The sync owner (.tpv) survives header swaps. Keep the submitting form
  // connected while HTMX has a newer change queued, or HTMX would discard it.
  const headerRevisions = new WeakMap();
  const headerRequests = new WeakMap();
  document.addEventListener("change", (event) => {
    const form = event.target.closest("[data-header-autosave]");
    if (form) headerRevisions.set(form, (headerRevisions.get(form) || 0) + 1);
  }, true);
  document.addEventListener("htmx:beforeRequest", (event) => {
    const form = event.detail.elt;
    if (form?.id === "quick-customer-trigger") {
      // Reopening must not expose the previous form while its replacement GET
      // is in flight: edits/submits on that form would be lost on the swap.
      const panel = event.detail.target;
      const loading = document.createElement("p");
      loading.id = "quick-customer-title";
      loading.setAttribute("role", "status");
      loading.textContent = "Cargando formulario de cliente…";
      panel.replaceChildren(loading);
    }
    if (form?.matches("[data-header-autosave]")) {
      headerRequests.set(event.detail.xhr, { form, revision: headerRevisions.get(form) || 0 });
    }
  });
  document.addEventListener("htmx:beforeSwap", (event) => {
    const request = headerRequests.get(event.detail.xhr);
    if (request && (headerRevisions.get(request.form) || 0) !== request.revision) {
      event.detail.shouldSwap = false;
    }
  });

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
    // Only UI quantities: integer thousandths preserve all three decimal places.
    const match = /^(\d+)(?:\.(\d{1,3}))?$/.exec(input.value);
    if (!match) return;
    const current = BigInt(match[1]) * 1000n + BigInt((match[2] || "").padEnd(3, "0"));
    const next = current + BigInt(button.dataset.quantityStep) * 1000n;
    if (next <= 0n) return;
    const fraction = String(next % 1000n).padStart(3, "0").replace(/0+$/, "");
    input.value = `${next / 1000n}${fraction ? `.${fraction}` : ""}`;
    saveQuantity(input);
  });

  document.addEventListener("htmx:afterSwap", () => {
    syncCartSummary();
    normalizeResponsiveTicket();
    document.querySelectorAll("[data-checkout]").forEach(initializeCheckout);
    document.querySelector('#line-editor-dialog[open] [autofocus]')?.focus();
  });

  document.addEventListener("htmx:oobAfterSwap", () => {
    syncCartSummary();
    normalizeResponsiveTicket();
  });

  if (matchMedia("(min-width: 768px)").matches) {
    document.querySelector("[data-tpv-search]")?.focus();
  }
  syncCartSummary();
  normalizeResponsiveTicket();
  document.querySelectorAll("[data-checkout]").forEach(initializeCheckout);
})();
