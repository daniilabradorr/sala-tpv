"""Manual Chromium latency baseline, excluded from normal test discovery/CI."""

import json
import time
from pathlib import Path

from django.conf import settings
from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.test import Client, override_settings
from django.urls import reverse
from playwright.sync_api import expect, sync_playwright

from tests.performance.baseline import metadata
from tests.performance.dataset import Dataset
from tests.performance.metrics import distribution


# Capture the actual input/click/change/Enter event, rather than Playwright IPC.
# afterSettle is correlated to the target and the same XHR as beforeRequest.
# A visible-state predicate is checked on animation frames after settle.
_OBSERVER = r"""
({event, trigger, target, expected}) => {
  window.tpvMeasure = {start: null, request: null, response: null, settle: null, end: null, status: null};
  let xhr;
  const triggerListener = e => {
    if (!e.target.closest(trigger) || (event === 'keydown' && e.key !== 'Enter')) return;
    if (window.tpvMeasure.start === null) window.tpvMeasure.start = performance.now();
  };
  document.addEventListener(event, triggerListener, true);
  document.addEventListener('htmx:beforeRequest', e => {
    if (window.tpvMeasure.start === null || e.detail.target?.id !== target) return;
    xhr = e.detail.xhr;
    window.tpvMeasure.request = performance.now();
  });
  document.addEventListener('htmx:afterRequest', e => {
    if (e.detail.xhr !== xhr) return;
    window.tpvMeasure.response = performance.now();
    window.tpvMeasure.status = xhr.status;
  });
  document.addEventListener('htmx:afterSettle', e => {
    if (e.detail.xhr !== xhr || !xhr) return;
    window.tpvMeasure.settle = performance.now();
    const check = () => {
      const node = document.querySelector(expected.selector);
      const visible = node && node.getClientRects().length > 0;
      const valid = visible &&
        (expected.value === undefined || node.value === expected.value) &&
        (expected.checked === undefined || node.checked === expected.checked) &&
        (expected.text === undefined || node.textContent.includes(expected.text)) &&
        (!expected.enabled || !node.disabled);
      if (valid) {
        window.tpvMeasure.end = performance.now();
        document.removeEventListener(event, triggerListener, true);
      } else requestAnimationFrame(check);
    };
    requestAnimationFrame(check);
  });
}
"""


@override_settings(
    STORAGES={
        "staticfiles": {
            "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"
        }
    }
)
class BrowserBaseline(StaticLiveServerTestCase):
    output = Path("work/browser-baseline.json")
    warmups = 5
    iterations = 20
    chromium = None

    def test_measure_interactions(self):
        dataset = Dataset(250, label="browser-baseline")
        client = Client()
        client.force_login(dataset.user)
        cookie = client.cookies[settings.SESSION_COOKIE_NAME].value
        # All fixture creation occurs before entering Playwright's async context.
        batches = {}
        for label in (
            "search",
            "add",
            "quantity_plus",
            "quantity_enter",
            "header",
            "checkout_1",
            "checkout_20",
        ):
            count = 20 if label == "checkout_20" else 1 if label == "checkout_1" else 5
            batches[label] = [
                dataset.sale(count) for _ in range(1 + self.warmups + self.iterations)
            ]
        result = metadata()
        result.update(
            warmups=self.warmups,
            iterations=self.iterations,
            catalog_size=250,
            viewport={"width": 1440, "height": 900},
            search_debounce_ms=275,
            scenarios={},
        )
        start = time.perf_counter()
        with sync_playwright() as playwright:
            launch = {"headless": True}
            if self.chromium:
                launch["executable_path"] = self.chromium
            browser = playwright.chromium.launch(**launch)
            result["chromium"] = browser.version
            context = browser.new_context(
                viewport=result["viewport"], reduced_motion="no-preference"
            )
            context.add_cookies(
                [
                    {
                        "name": settings.SESSION_COOKIE_NAME,
                        "value": cookie,
                        "url": self.live_server_url,
                    }
                ]
            )
            for label, fixtures in batches.items():
                samples = []
                for sale, lines in fixtures:
                    page = context.new_page()
                    errors = []
                    page.on("pageerror", lambda error: errors.append(str(error)))
                    path = reverse(
                        "sales:sale_detail", args=[dataset.store.pk, sale.pk]
                    )
                    response = page.goto(self.live_server_url + path, wait_until="load")
                    self.assertEqual(response.status, 200)
                    page.wait_for_function("window.htmx !== undefined")
                    expect(page.locator("#product-grid .product-card")).to_have_count(
                        24
                    )
                    if label == "search":
                        observer = {
                            "event": "input",
                            "trigger": "#product-search",
                            "target": "product-grid",
                            "expected": {
                                "selector": "#product-grid .product-card strong",
                                "text": "Producto 0020",
                            },
                        }

                        def action():
                            return page.locator("#product-search").fill("BASE-0020")
                    elif label == "add":
                        observer = {
                            "event": "click",
                            "trigger": '#product-grid form [type="submit"]',
                            "target": "sale-cart-content",
                            "expected": {
                                "selector": ".cart-line:nth-child(6) strong",
                                "text": "Producto 0005",
                            },
                        }

                        def action():
                            return (
                                page.locator("#product-grid .product-card")
                                .nth(5)
                                .click()
                            )
                    elif label in ("quantity_plus", "quantity_enter"):
                        input_selector = f"#quantity-{lines[0].pk}"
                        observer = {
                            "event": "click" if label == "quantity_plus" else "keydown",
                            "trigger": '.cart-line:first-child [data-quantity-step="1"]'
                            if label == "quantity_plus"
                            else input_selector,
                            "target": "sale-cart-content",
                            "expected": {
                                "selector": input_selector,
                                "value": "2" if label == "quantity_plus" else "1.5",
                            },
                        }
                        if label == "quantity_plus":

                            def action():
                                return page.locator(
                                    '.cart-line:first-child [data-quantity-step="1"]'
                                ).click()
                        else:
                            page.locator(input_selector).fill("1.5")

                            def action():
                                return page.locator(input_selector).press("Enter")
                    elif label == "header":
                        observer = {
                            "event": "change",
                            "trigger": "#header-document-invoice",
                            "target": "workspace-header",
                            "expected": {
                                "selector": "#header-document-invoice",
                                "checked": True,
                            },
                        }

                        def action():
                            return page.locator("#header-document-invoice").check()
                    else:
                        observer = {
                            "event": "click",
                            "trigger": "[data-checkout-open]",
                            "target": "checkout-panel",
                            "expected": {
                                "selector": '#checkout-dialog[open] [name="method"]',
                                "enabled": True,
                            },
                        }

                        def action():
                            return page.locator("[data-checkout-open]").click()

                    page.evaluate(_OBSERVER, observer)
                    action()
                    page.wait_for_function(
                        "window.tpvMeasure.end !== null", timeout=15000
                    )
                    timing = page.evaluate("window.tpvMeasure")
                    self.assertEqual(timing["status"], 200)
                    self.assertFalse(errors, errors)
                    if label == "search":
                        expect(
                            page.locator("#product-grid .product-card")
                        ).to_have_count(1)
                    samples.append(
                        {
                            "ui_ms": timing["end"] - timing["start"],
                            "event_to_request_ms": timing["request"] - timing["start"],
                            "request_to_response_ms": timing["response"]
                            - timing["request"],
                            "response_to_settle_ms": timing["settle"]
                            - timing["response"],
                            "settle_to_visible_ms": timing["end"] - timing["settle"],
                            "status": timing["status"],
                        }
                    )
                    page.close()
                warm = samples[1 + self.warmups :]
                result["scenarios"][label] = {
                    "first_measured_interaction": samples[0],
                    **{
                        metric: distribution([sample[metric] for sample in warm])
                        for metric in warm[0]
                        if metric != "status"
                    },
                    "samples": warm,
                }
                print(
                    f"UI {label}: p50={result['scenarios'][label]['ui_ms']['p50']}ms p95={result['scenarios'][label]['ui_ms']['p95']}ms"
                )
            context.close()
            browser.close()
        result["profiling_seconds"] = round(time.perf_counter() - start, 3)
        result["scenario_count"] = len(result["scenarios"])
        self.output.parent.mkdir(parents=True, exist_ok=True)
        self.output.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n")
