"""Chromium checks for FE-04; run against the live-server URL in BASE_URL."""

import os

from playwright.sync_api import sync_playwright


def main():
    base_url = os.environ.get("BASE_URL", "http://127.0.0.1:8000")
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 375, "height": 812})
        errors = []
        page.on(
            "console",
            lambda message: (
                errors.append(message.text) if message.type == "error" else None
            ),
        )
        page.goto(base_url)
        assert page.locator('meta[name="csrf-token"]').count() == 1
        assert page.locator('#nx-toast-region[aria-live="polite"]').count() == 1
        page.evaluate(
            "document.dispatchEvent(new CustomEvent('nx:toast',{detail:{message:'Listo',tone:'success',timeout:1000}}))"
        )
        assert page.get_by_text("Listo", exact=True).is_visible()
        assert errors == []
        browser.close()


if __name__ == "__main__":
    main()
