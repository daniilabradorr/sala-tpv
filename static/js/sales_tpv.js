(() => {
  let reopenTicketAfterSwap = false;

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

  function updateCheckoutPreviews(checkout) {
    const due =
      Number(checkout.querySelector(".checkout-due strong")?.textContent.replace(",", ".")) || 0;
    const received = Number(checkout.querySelector('[name="cash_received"]')?.value || 0);
    const change = checkout.querySelector("[data-cash-change]");
    if (change) change.textContent = `${Math.max(received - due, 0).toFixed(2)} €`;
    const total = [...checkout.querySelectorAll('[data-split-payment] [name$="-amount"]')].reduce(
      (sum, input) => sum + Number(input.value || 0),
      0,
    );
    const splitTotal = checkout.querySelector("[data-split-total]");
    if (splitTotal) splitTotal.textContent = `${total.toFixed(2)} €`;
  }

  document.addEventListener("change", (event) => {
    if (event.target.name === "customer_mode") syncCustomer();
    const checkout = event.target.closest(".checkout");
    if (!checkout) return;
    if (event.target.name === "mode") {
      const split = event.target.value === "split";
      checkout.querySelector("[data-single-payment]").hidden = split;
      const splitPanel = checkout.querySelector("[data-split-payment]");
      if (splitPanel) splitPanel.hidden = !split;
    }
    if (event.target.name === "method") {
      checkout.querySelector("[data-cash-fields]").hidden =
        event.target.dataset.methodCode !== "cash";
    }
    updateCheckoutPreviews(checkout);
  });

  document.addEventListener("input", (event) => {
    const checkout = event.target.closest(".checkout");
    if (checkout) updateCheckoutPreviews(checkout);
  });

  document.addEventListener("click", (event) => {
    const button = event.target.closest("[data-quantity-step]");
    if (!button) return;
    const form = button.closest("form");
    const input = form.querySelector('[name="quantity"]');
    const next = Number(input.value) + Number(button.dataset.quantityStep);
    if (next <= 0) return;
    input.value = next.toFixed(3);
    form.requestSubmit();
  });

  document.addEventListener("htmx:beforeSwap", (event) => {
    if (event.detail.target?.id === "sale-cart") {
      reopenTicketAfterSwap = Boolean(document.querySelector("#sale-cart[open]"));
    }
  });

  document.addEventListener("htmx:oobBeforeSwap", (event) => {
    if (event.detail.target?.id === "sale-cart") {
      reopenTicketAfterSwap = Boolean(document.querySelector("#sale-cart[open]"));
    }
  });

  document.addEventListener("htmx:afterSwap", () => {
    syncCustomer();
    syncCartSummary();
    normalizeResponsiveTicket();
    if (reopenTicketAfterSwap && matchMedia("(max-width: 1199px)").matches) {
      reopenTicketAfterSwap = false;
      workspace()?.querySelector('[data-nx-drawer-trigger="sale-cart"]')?.click();
    }
  });

  document.addEventListener("htmx:oobAfterSwap", () => {
    syncCartSummary();
    normalizeResponsiveTicket();
    if (reopenTicketAfterSwap && matchMedia("(max-width: 1199px)").matches) {
      reopenTicketAfterSwap = false;
      workspace()?.querySelector('[data-nx-drawer-trigger="sale-cart"]')?.click();
    }
  });

  if (matchMedia("(min-width: 768px)").matches) {
    document.querySelector("[data-tpv-search]")?.focus();
  }
  syncCustomer();
  syncCartSummary();
  normalizeResponsiveTicket();
})();
