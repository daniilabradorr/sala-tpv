(() => {
  function syncCustomer(root = document) {
    const header = root.querySelector("#workspace-header");
    if (!header) return;
    const mode = header.querySelector('[name="customer_mode"]:checked')?.value;
    const field = header.querySelector(".customer-field");
    if (!field) return;
    field.hidden = mode !== "customer";
    if (mode !== "customer") field.querySelector("select").value = "";
  }
  document.addEventListener("change", (event) => {
    if (event.target.name === "customer_mode") syncCustomer();
  });
  document.addEventListener("click", (event) => {
    const checkoutOpen = event.target.closest("[data-checkout-open]");
    if (checkoutOpen && checkoutOpen.getAttribute("aria-disabled") !== "true") {
      const dialog = document.querySelector("#checkout-dialog");
      if (dialog?.showModal) dialog.showModal();
    }
    if (event.target.closest("[data-checkout-close]")) {
      document.querySelector("#checkout-dialog")?.close();
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
  document.addEventListener("change", (event) => {
    const checkout = event.target.closest(".checkout");
    if (!checkout) return;
    if (event.target.name === "mode") {
      const split = event.target.value === "split";
      checkout.querySelector("[data-single-payment]").hidden = split;
      const splitPanel = checkout.querySelector("[data-split-payment]");
      if (splitPanel) splitPanel.hidden = !split;
    }
    if (event.target.name === "method") {
      const cash = event.target.dataset.methodCode === "cash";
      checkout.querySelector("[data-cash-fields]").hidden = !cash;
    }
    updateCheckoutPreviews(checkout);
  });
  document.addEventListener("input", (event) => {
    const checkout = event.target.closest(".checkout");
    if (checkout) updateCheckoutPreviews(checkout);
  });
  document.addEventListener("submit", (event) => {
    const form = event.target.closest("[data-checkout-form]");
    if (!form) return;
    const button = form.querySelector("button[type=submit]");
    button.disabled = true;
    button.textContent = button.dataset.loadingText;
  });
  function updateCheckoutPreviews(checkout) {
    const due = Number(checkout.querySelector(".checkout-due strong")?.textContent.replace(",", ".")) || 0;
    const received = Number(checkout.querySelector('[name="cash_received"]')?.value || 0);
    const change = checkout.querySelector("[data-cash-change]");
    if (change) change.textContent = `${Math.max(received - due, 0).toFixed(2)} €`;
    const total = [...checkout.querySelectorAll('[data-split-payment] [name$="-amount"]')].reduce((sum, input) => sum + Number(input.value || 0), 0);
    const splitTotal = checkout.querySelector("[data-split-total]");
    if (splitTotal) splitTotal.textContent = `${total.toFixed(2)} €`;
  }
  document.addEventListener("htmx:afterSwap", () => syncCustomer());
  syncCustomer();
})();
