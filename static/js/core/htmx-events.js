let initialized = false;

export const initHtmxEvents = () => {
  if (initialized) return;

  document.body.addEventListener("htmx:responseError", (event) => {
    console.error("HTMX response error:", event.detail);
  });
  initialized = true;
};
