(() => {
  const wizard = document.querySelector("[data-user-wizard]");
  const role = document.querySelector("#id_role");
  const matrix = document.querySelector("[data-access-matrix]");
  const ownerGlobal = document.querySelector("[data-owner-global]");
  const updateRolePresentation = () => {
    const owner = role?.value === "owner";
    if (matrix && wizard) matrix.hidden = owner;
    if (ownerGlobal) ownerGlobal.hidden = !owner;
    matrix?.querySelectorAll("input").forEach((input) => { input.disabled = owner; });
  };
  if (wizard) {
    wizard.classList.add("is-enhanced");
    const show = (number) => wizard.dataset.step = String(number);
    wizard.querySelector("[data-wizard-next]")?.addEventListener("click", () => show(2));
    wizard.querySelector("[data-wizard-back]")?.addEventListener("click", () => show(1));
    show(wizard.querySelector("[aria-invalid=true]") ? 1 : 1);
    role?.addEventListener("change", updateRolePresentation);
    updateRolePresentation();
  }
  document.querySelectorAll("[data-access-row]").forEach((row) => {
    const access = row.querySelector("[data-access-toggle] input");
    const operational = row.querySelector("[data-operational-permissions]");
    const update = () => {
      operational?.setAttribute("aria-disabled", String(!access.checked));
      operational?.classList.toggle("is-disabled", !access.checked);
    };
    access?.addEventListener("change", update); update();
  });
})();
