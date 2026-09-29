(() => {
  const wizard = document.querySelector("[data-user-wizard]");
  const role = document.querySelector("#id_role");
  const matrix = document.querySelector("[data-access-matrix]");
  const ownerGlobal = document.querySelector("[data-owner-global]");
  const updateAccessRow = (row) => {
    const access = row.querySelector("[data-access-toggle] input");
    const operational = row.querySelector("[data-operational-permissions]");
    const disabled = !access?.checked;
    operational?.setAttribute("aria-disabled", String(disabled));
    operational?.querySelectorAll("input").forEach((input) => { input.disabled = disabled; });
    operational?.classList.toggle("is-disabled", disabled);
  };
  const updateRolePresentation = () => {
    const owner = role?.value === "owner";
    if (matrix && wizard) matrix.hidden = owner;
    if (ownerGlobal) ownerGlobal.hidden = !owner;
    matrix?.querySelectorAll("[data-access-row]").forEach((row) => {
      const access = row.querySelector("[data-access-toggle] input");
      if (access) access.disabled = owner;
      if (owner) {
        row.querySelectorAll("[data-operational-permissions] input").forEach((input) => { input.disabled = true; });
      } else {
        updateAccessRow(row);
      }
    });
  };
  if (wizard) {
    wizard.classList.add("is-enhanced");
    const show = (number) => wizard.dataset.step = String(number);
    wizard.querySelector("[data-wizard-next]")?.addEventListener("click", () => show(2));
    wizard.querySelector("[data-wizard-back]")?.addEventListener("click", () => show(1));
    show(wizard.querySelector("[data-matrix-errors]") ? 2 : 1);
    role?.addEventListener("change", updateRolePresentation);
    updateRolePresentation();
  }
  document.querySelectorAll("[data-access-row]").forEach((row) => {
    const access = row.querySelector("[data-access-toggle] input");
    access?.addEventListener("change", () => updateAccessRow(row));
    updateAccessRow(row);
  });
})();
