function bindQuantity(root = document) {
  root.querySelectorAll("[data-quantity-step]").forEach((button) => {
    if (button.dataset.bound) return;
    button.dataset.bound = "true";
    button.addEventListener("click", () => {
      const input = button.closest(".quantity-control").querySelector("input");
      const delta = Number.parseFloat(button.dataset.quantityStep);
      const current = Number.isFinite(input.valueAsNumber)
        ? input.valueAsNumber
        : 0;
      const maximum = Number.parseFloat(input.max);
      if (!Number.isFinite(delta) || !Number.isFinite(maximum)) return;
      input.valueAsNumber = Math.max(
        0,
        Math.min(maximum, current + delta),
      );
      input.focus();
    });
  });
}
bindQuantity();
document.body.addEventListener("htmx:afterSwap", (event) => bindQuantity(event.target));
