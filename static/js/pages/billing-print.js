(() => {
  "use strict";

  document.addEventListener("click", (event) => {
    if (!event.target.closest("[data-print-document]")) return;
    window.print();
  });

  // Only the explicit checkout action requests printing on arrival.
  // load waits for the stylesheet and document images before printing.
  if (new URLSearchParams(window.location.search).get("autoprint") === "1") {
    window.addEventListener("load", () => window.print(), { once: true });
  }
})();
