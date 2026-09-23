const cents = (value) => {
  const normalized = String(value || "").trim().replace(",", ".");
  if (!/^\d+(\.\d{0,2})?$/.test(normalized)) return null;
  const [whole, decimal = ""] = normalized.split(".");
  return Number.parseInt(whole, 10) * 100 + Number.parseInt(decimal.padEnd(2, "0"), 10);
};
const enhanceCountPreview = (root = document) => {
  const input = root.querySelector('[name="counted_amount"]');
  const expectedNode = root.querySelector("[data-expected-cents]");
  const output = root.querySelector("[data-count-preview]");
  if (!input || !expectedNode || !output) return;
  input.addEventListener("input", () => {
    const counted = cents(input.value);
    if (counted === null) return;
    const difference = counted - Number.parseInt(expectedNode.dataset.expectedCents, 10);
    output.textContent = `${difference < 0 ? "Faltan " : difference > 0 ? "Sobran " : "Diferencia "}${new Intl.NumberFormat("es-ES", { style: "currency", currency: "EUR" }).format(Math.abs(difference) / 100)}`;
  });
};
enhanceCountPreview();
document.body.addEventListener("htmx:afterSwap", (event) => enhanceCountPreview(event.detail.target));
