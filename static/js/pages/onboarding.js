(() => {
  const root = document.querySelector("[data-onboarding]");
  if (!root) return;

  root.classList.add("wizard-enhanced");
  const form = root.querySelector("[data-onboarding-form]");
  const steps = [...root.querySelectorAll("[data-step]")];
  const progress = root.querySelector("[data-progress]");
  const status = root.querySelector("[data-step-status]");
  const sameAddress = form.elements.same_business_address;
  const storeAddress = root.querySelector("[data-store-address]");
  let current = Number(root.dataset.initialStep || 1);

  const value = (name) => (form.elements[name]?.value || "").trim();
  const showStep = (number, focus = false) => {
    current = Math.max(1, Math.min(4, number));
    steps.forEach((step) => {
      const active = Number(step.dataset.step) === current;
      step.hidden = !active;
      step.setAttribute("aria-hidden", String(!active));
    });
    progress.value = current;
    status.textContent = `Paso ${current} de 4`;
    if (current === 4) updateReview();
    if (focus) steps[current - 1].querySelector("legend").focus();
    window.scrollTo({ top: 0, behavior: "smooth" });
  };

  const validateCurrent = () => {
    const controls = [...steps[current - 1].querySelectorAll("input, select, textarea")];
    for (const control of controls) {
      if (!control.checkValidity()) {
        control.reportValidity();
        control.focus();
        return false;
      }
    }
    return true;
  };

  const toggleStoreAddress = () => {
    const usesBusiness = sameAddress.checked;
    storeAddress.hidden = usesBusiness;
    storeAddress.setAttribute("aria-hidden", String(usesBusiness));
    root.querySelector("[data-business-address]").textContent =
      `${value("address_line_1") || "Dirección del negocio"} · ${value("postal_code")} ${value("city")}`;
  };

  function updateReview() {
    root.querySelectorAll("[data-review]").forEach((node) => {
      node.textContent = value(node.dataset.review) || "—";
    });
    root.querySelector("[data-review-owner]").textContent =
      `${value("owner_first_name")} ${value("owner_last_name")}`.trim() || "—";
    const address = sameAddress.checked
      ? `${value("address_line_1")}, ${value("postal_code")} ${value("city")}`
      : `${value("store_address_line_1") || value("address_line_1")}, ${value("store_postal_code") || value("postal_code")} ${value("store_city") || value("city")}`;
    root.querySelector("[data-review-address]").textContent = address;
  }

  root.querySelectorAll("[data-next]").forEach((button) =>
    button.addEventListener("click", () => {
      if (validateCurrent()) showStep(current + 1, true);
    }),
  );
  root.querySelectorAll("[data-back]").forEach((button) =>
    button.addEventListener("click", () => showStep(current - 1, true)),
  );
  sameAddress.addEventListener("change", toggleStoreAddress);
  form.addEventListener("submit", (event) => {
    if (!form.checkValidity()) {
      event.preventDefault();
      form.reportValidity();
      return;
    }
    const submit = root.querySelector("[data-submit]");
    submit.disabled = true;
    submit.textContent = "Procesando…";
    root.querySelector("[data-processing]").hidden = false;
  });

  toggleStoreAddress();
  showStep(current);
})();
