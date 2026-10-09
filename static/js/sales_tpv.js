(() => {
  const workspace = () => document.querySelector(".tpv");

  // Absolute quantities share one queue owner that survives cart-content swaps.
  // Keep the old forms connected until the final queued intent is answered.
  let cartRevision = 0;
  const dirtyLines = new Set();
  let searchTimer;
  let searchValue = document.querySelector("[data-tpv-search]")?.value || "";
  document.addEventListener("input", (event) => {
    if (!event.target.matches("[data-tpv-search]")) return;
    clearTimeout(searchTimer);
    if (event.target.value === searchValue) return;
    searchValue = event.target.value;
    searchTimer = setTimeout(() => event.target.form.dispatchEvent(new CustomEvent("tpv:search", { bubbles: true })), 175);
  });
  document.addEventListener("htmx:configRequest", (event) => {
    if (dirtyLines.size && event.detail.elt.closest?.("#sale-cart, .line-editor")) {
      event.detail.headers["X-TPV-Changed-Lines"] = [...dirtyLines].join(",");
    }
  });
  const cartRequests = new WeakMap();
  document.addEventListener("submit", (event) => {
    const form = event.target;
    if (form.id === "catalog-filters") clearTimeout(searchTimer);
    if (form.matches(".quantity-form")) {
      const input = form.querySelector('[name="quantity"]');
      if (!form.isConnected || form.dataset.quantityRemoving || form.dataset.quantitySubmitted === input.value) {
        event.preventDefault();
        event.stopImmediatePropagation();
        return;
      }
      // Swapped forms are visible before HTMX's settle task initializes them.
      // Install the form's submit listener before this event reaches its target.
      htmx.process(form);
      form.dataset.quantitySubmitted = input.value;
    }
    if (event.target.matches('#sale-cart form, .line-editor form, .product-grid form')) {
      event.cartRevision = ++cartRevision;
      const lineId = form.dataset.cartLineId;
      if (lineId) dirtyLines.add(lineId);
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

  // Capture at swap time, not request time: the user can scroll while waiting.
  // The same shell is replaced by direct quantity/add/delete and editor OOB swaps.
  let cartScroll = null;
  function captureCartScroll(status = 200) {
    const shell = document.querySelector("#sale-cart-content");
    const region = shell?.querySelector("[data-cart-scroll-region]");
    cartScroll = region ? { shell, sale: shell.dataset.saleId, top: region.scrollTop, status } : null;
  }
  document.addEventListener("htmx:beforeSwap", (event) => {
    if (event.detail.target?.id === "sale-cart-content" && event.detail.shouldSwap) {
      captureCartScroll(event.detail.xhr.status);
    }
  });
  document.addEventListener("htmx:oobBeforeSwap", (event) => {
    if (event.detail.target?.id === "sale-cart-content" && event.detail.shouldSwap) {
      captureCartScroll();
    }
  });
  function restoreCartScroll() {
    const saved = cartScroll;
    const shell = document.querySelector("#sale-cart-content");
    if (!saved || shell === saved.shell) return;
    cartScroll = null;
    const region = shell?.querySelector("[data-cart-scroll-region]");
    if (!region || shell.dataset.saleId !== saved.sale) return;
    region.scrollTop = saved.top; // The browser clamps after removal/emptying.
    const alert = saved.status === 422 && region.querySelector('[role="alert"]');
    if (alert) {
      const bounds = region.getBoundingClientRect();
      const error = alert.getBoundingClientRect();
      if (error.top < bounds.top || error.bottom > bounds.bottom) {
        region.scrollTop += error.top - bounds.top;
      }
    }
  }
  document.addEventListener("htmx:afterSwap", restoreCartScroll);
  document.addEventListener("htmx:oobAfterSwap", restoreCartScroll);
  document.addEventListener("htmx:afterSettle", (event) => {
    if (event.detail.xhr?.status !== 422 || !event.detail.target?.id?.startsWith("cart-line-")) return;
    const region = document.querySelector("[data-cart-scroll-region]");
    const alert = document.getElementById(event.detail.target.id)?.querySelector('[role="alert"]');
    if (!region || !alert) return;
    const bounds = region.getBoundingClientRect();
    const error = alert.getBoundingClientRect();
    if (error.top < bounds.top || error.bottom > bounds.bottom) region.scrollTop += Math.floor(error.top - bounds.top) - 2;
  });

  function saveQuantity(input) {
    const form = input.closest("form");
    // A swap can blur the old input and fire change after Enter already saved it.
    // Never submit a form whose HTMX listeners are being removed.
    if (!form?.isConnected || form.dataset.quantityRemoving || form.dataset.quantitySubmitted === input.value) return;
    form.requestSubmit();
  }
  document.addEventListener("htmx:beforeCleanupElement", (event) => {
    if (event.detail.elt.matches?.(".quantity-form")) event.detail.elt.dataset.quantityRemoving = "true";
  });
  document.addEventListener("htmx:afterRequest", (event) => {
    if (event.detail.elt.matches?.(".quantity-form") && (event.detail.xhr.status === 0 || event.detail.xhr.status >= 500)) {
      delete event.detail.elt.dataset.quantitySubmitted;
    }
  });
  document.addEventListener("change", (event) => {
    if (event.target.matches('.quantity-form [name="quantity"]')) saveQuantity(event.target);
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
    if (form?.matches("[data-checkout-open], [data-checkout-reload]")) {
      const panel = event.detail.target;
      const shell = document.querySelector("#checkout-loading-template")?.content.cloneNode(true);
      if (shell) panel.replaceChildren(shell);
    }
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

  // Visual feedback only. Decimal strings become integer cents without binary
  // floating point; the server still validates and confirms every amount.
  function cents(value) {
    const match = /^(\d+)(?:[.,](\d{1,2}))?$/.exec(String(value).trim());
    return match ? BigInt(match[1]) * 100n + BigInt((match[2] || "").padEnd(2, "0")) : null;
  }
  function decimalMoney(value) {
    const amount = value < 0n ? -value : value;
    return `${value < 0n ? "-" : ""}${amount / 100n}.${String(amount % 100n).padStart(2, "0")}`;
  }
  const money = (value) => `${decimalMoney(value).replace(".", ",")} €`;
  function pendingAmount(checkout) {
    return cents(checkout.dataset.pending || "0") ?? 0n;
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
        input.dataset.methodCash === "true",
      ]),
    );
  }

  function syncPaymentMethodFields(checkout) {
    const selected = checkout.querySelector('[name="method"]:checked');
    const cash = selected?.dataset.methodCash === "true";
    const cashFields = checkout.querySelector("[data-cash-fields]");
    if (cashFields) cashFields.hidden = !cash;
    const reference = checkout.querySelector("[data-single-reference]");
    if (reference) reference.hidden = !selected || cash;

    const codes = methodCodes(checkout);
    checkout.querySelectorAll("[data-split-part]:not([hidden])").forEach((part) => {
      const selectedId = part.querySelector("[data-split-method]")?.value;
      const cash = codes.get(selectedId);
      const partCash = part.querySelectorAll("[data-part-cash]");
      const partReference = part.querySelector("[data-part-reference]");
      partCash.forEach(node => { node.hidden = cash !== true; });
      if (partReference) partReference.hidden = !selectedId || cash === true;
    });
  }

  function cashFeedback(input, amount, label, output) {
    if (!input || !output) return;
    const received = input.value.trim() === "" ? amount : cents(input.value);
    if (received === null || amount === null) {
      if (label) label.textContent = "Importe inválido";
      output.textContent = "—";
      return;
    }
    const difference = received - amount;
    if (label) label.textContent = difference < 0n ? "Faltan" : "Cambio";
    output.textContent = money(difference < 0n ? -difference : difference);
  }
  function updateCashChange(checkout) {
    cashFeedback(checkout.querySelector('[name="cash_received"]'), pendingAmount(checkout),
      checkout.querySelector("[data-cash-label]"), checkout.querySelector("[data-cash-change]"));
    checkout.querySelectorAll("[data-split-part]:not([hidden])").forEach((part) => {
      cashFeedback(part.querySelector('[name$="-cash_received"]'), cents(part.querySelector('[name$="-amount"]')?.value || "0"),
        part.querySelector("[data-part-cash-label]"), part.querySelector("[data-part-cash-change]"));
    });
  }
  function updateSplitSummary(checkout) {
    const amounts = [...checkout.querySelectorAll('[data-split-part]:not([hidden]) [name$="-amount"]')].map(input => cents(input.value || "0"));
    const valid = amounts.every(amount => amount !== null);
    const assigned = amounts.reduce((sum, amount) => sum + (amount ?? 0n), 0n);
    const remaining = pendingAmount(checkout) - assigned;
    const assignedOutput = checkout.querySelector("[data-split-assigned]");
    const remainingOutput = checkout.querySelector("[data-split-remaining]");
    if (assignedOutput) assignedOutput.textContent = valid ? money(assigned) : "—";
    if (remainingOutput) {
      remainingOutput.textContent = valid ? money(remaining) : "—";
      remainingOutput.classList.toggle("is-negative", remaining < 0n);
    }
    updateCashChange(checkout);
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
      input.value = cashQuick.dataset.cashQuick === "exact" ? decimalMoney(pendingAmount(checkout)) : cashQuick.dataset.cashQuick;
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

  document.addEventListener("htmx:afterSwap", (event) => {
    const revision = cartRequests.get(event.detail.xhr);
    if (revision !== undefined && revision === cartRevision) dirtyLines.clear();
    syncCartSummary();
    normalizeResponsiveTicket();
    document.querySelectorAll("[data-checkout]").forEach(initializeCheckout);
    document.querySelector('#line-editor-dialog[open] [autofocus]')?.focus();
  });

  document.addEventListener("htmx:afterSettle", (event) => {
    if (event.detail.target?.id !== "checkout-panel") return;
    const checkout = document.querySelector("#checkout-dialog[open] [data-checkout]");
    if (checkout) {
      const cash = checkout.querySelector('[name="method"]:checked')?.dataset.methodCash === "true";
      const focus = cash ? checkout.querySelector('[name="cash_received"]') : checkout.querySelector('[name="method"]:checked, [name="method"], [type="submit"]');
      focus?.focus();
    }
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
