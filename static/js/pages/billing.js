function openBillingRow(row) {
  const href = row.dataset.href;
  if (href) window.location.assign(href);
}
document.addEventListener("click", (event) => {
  const row = event.target.closest(".billing-clickable");
  if (!row || event.target.closest("a, button, input, select, textarea")) return;
  openBillingRow(row);
});
document.addEventListener("keydown", (event) => {
  const row = event.target.closest(".billing-clickable");
  if (!row || !["Enter", " "].includes(event.key)) return;
  event.preventDefault(); openBillingRow(row);
});
