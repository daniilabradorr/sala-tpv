document.addEventListener("DOMContentLoaded", () => {
  console.log("Sala TPV base cargada");
});

document.body.addEventListener("htmx:responseError", (event) => {
  console.error("HTMX response error:", event.detail);
});