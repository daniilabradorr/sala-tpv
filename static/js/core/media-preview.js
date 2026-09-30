const activeUrls = new WeakMap();
export function initMediaPreview() {
  document.addEventListener("change", (event) => {
    const input = event.target.closest("[data-media-upload]");
    if (!input || !input.files?.[0]) return;
    const preview = input.closest("form")?.querySelector("[data-media-preview]");
    if (!preview) return;
    const previous = activeUrls.get(preview);
    if (previous) URL.revokeObjectURL(previous);
    const next = URL.createObjectURL(input.files[0]);
    activeUrls.set(preview, next);
    preview.src = next;
  });
  document.addEventListener("error", (event) => {
    const image = event.target.closest?.("img[data-media-fallback]");
    if (!image || image.dataset.mediaFallbackApplied) return;
    image.dataset.mediaFallbackApplied = "true";
    image.src = image.dataset.mediaFallback;
  }, true);
  window.addEventListener("pagehide", () => document.querySelectorAll("[data-media-preview]").forEach((image) => {
    const url = activeUrls.get(image); if (url) URL.revokeObjectURL(url);
  }));
}
