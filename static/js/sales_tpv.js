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
  document.addEventListener("htmx:afterSwap", () => syncCustomer());
  syncCustomer();
})();
