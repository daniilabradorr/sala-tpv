let initialized = false;

const normalized = (value) =>
  value
    .toLocaleLowerCase("es")
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .trim();

export const initCommandPalette = () => {
  if (initialized) return;
  const dialog = document.querySelector("[data-command-dialog]");
  const triggers = [...document.querySelectorAll("[data-command-trigger]")];
  const input = dialog?.querySelector("[data-command-input]");
  const items = dialog ? [...dialog.querySelectorAll("[data-command-item]")] : [];
  const empty = dialog?.querySelector("[data-command-empty]");
  if (!dialog || !input || !triggers.length) return;

  let returnFocus = triggers[0];
  let highlighted = -1;
  const visibleItems = () => items.filter((item) => !item.hidden);
  const highlight = (index) => {
    const visible = visibleItems();
    items.forEach((item) => item.classList.remove("is-highlighted"));
    if (!visible.length) return;
    highlighted = (index + visible.length) % visible.length;
    visible[highlighted].classList.add("is-highlighted");
    visible[highlighted].scrollIntoView({ block: "nearest" });
  };
  const filter = () => {
    const query = normalized(input.value);
    items.forEach((item) => {
      item.hidden = !normalized(item.dataset.search || item.textContent).includes(
        query,
      );
    });
    dialog.querySelectorAll(".command-results section").forEach((section) => {
      section.hidden = !section.querySelector("[data-command-item]:not([hidden])");
    });
    empty.hidden = visibleItems().length > 0;
    highlighted = -1;
  };
  const open = (trigger = document.activeElement) => {
    returnFocus = trigger;
    dialog.showModal();
    input.value = "";
    filter();
    input.focus();
  };
  triggers.forEach((trigger) =>
    trigger.addEventListener("click", () => open(trigger)),
  );
  dialog.querySelector("[data-command-close]").addEventListener("click", () =>
    dialog.close(),
  );
  input.addEventListener("input", filter);
  input.addEventListener("keydown", (event) => {
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      if (highlighted < 0) {
        highlight(event.key === "ArrowDown" ? 0 : visibleItems().length - 1);
      } else {
        highlight(highlighted + (event.key === "ArrowDown" ? 1 : -1));
      }
    } else if (event.key === "Enter" && highlighted >= 0) {
      event.preventDefault();
      visibleItems()[highlighted].click();
    }
  });
  document.addEventListener("keydown", (event) => {
    if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") {
      event.preventDefault();
      if (dialog.open) dialog.close();
      else open();
    }
  });
  dialog.addEventListener("close", () => returnFocus?.focus());
  initialized = true;
};
