function bindQuantity(root = document) {
  root.querySelectorAll("[data-quantity-step]").forEach((button) => {
    if (button.dataset.bound) return;
    button.dataset.bound = "true";
    button.addEventListener("click", () => {
      const input = button.closest(".quantity-control").querySelector("input");
      const step = Number(button.dataset.quantityStep);
      const maximum = Number(button.closest(".return-line").querySelector('[data-label="Disponible"] strong')?.textContent || 0);
      input.value = Math.max(0, Math.min(maximum, Number(input.value || 0) + step));
      input.focus();
    });
  });
}
bindQuantity();
document.body.addEventListener("htmx:afterSwap", (event) => bindQuantity(event.target));
