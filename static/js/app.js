document.addEventListener("DOMContentLoaded", () => {
  console.log("Netxodo base cargado");
});

document.body.addEventListener("htmx:responseError", (event) => {
  console.error("HTMX response error:", event.detail);
});