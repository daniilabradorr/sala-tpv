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
  function closeTicket({ restoreFocus = true } = {}) {
    const root = workspace();
    if (!root?.classList.contains("ticket-open")) return;
    root.classList.remove("ticket-open");
    document.body.style.overflow = "";
    if (restoreFocus) root.querySelector("[data-ticket-open]")?.focus();
  }
  function syncCartSummary() {
    const root = workspace();
    const cart = root?.querySelector("#sale-cart");
    if (!cart) return;
    const count = cart.querySelector(".cart-heading > span")?.textContent.match(/\d+/)?.[0] || "0";
    const total = cart.querySelector(".grand-total dd")?.textContent || "0,00 €";
    root.querySelector("[data-cart-count]").textContent = count;
    root.querySelector("[data-cart-total]").textContent = total;
  }
  document.addEventListener("change", (event) => {
    if (event.target.name === "customer_mode") syncCustomer();
  });
  document.addEventListener("click", (event) => {
    if (event.target.closest("[data-ticket-open]")) {
      workspace()?.classList.add("ticket-open");
      document.body.style.overflow = "hidden";
      workspace()?.querySelector("[data-ticket-close]")?.focus();
      return;
    }
    if (event.target.closest("[data-ticket-close]")) return closeTicket();
    const button = event.target.closest("[data-quantity-step]");
    if (!button) return;
    const form = button.closest("form");
    const input = form.querySelector('[name="quantity"]');
    const next = Number(input.value) + Number(button.dataset.quantityStep);
    if (next <= 0) return;
    input.value = next.toFixed(3);
    form.requestSubmit();
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && workspace()?.classList.contains("ticket-open")) closeTicket();
  });
  document.addEventListener("htmx:afterSwap", () => { syncCustomer(); syncCartSummary(); });
  if (matchMedia("(min-width: 768px)").matches) document.querySelector("[data-tpv-search]")?.focus();
  syncCustomer(); syncCartSummary();
})();
