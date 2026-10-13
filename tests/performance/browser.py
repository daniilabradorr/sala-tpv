"""Manual Chromium latency baseline, excluded from normal test discovery/CI."""

import json
import time
from decimal import Decimal
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
  window.tpvMeasure = {start: null, request: null, response: null, settle: null, end: null, status: null, dialog: null};
  const dialog = document.querySelector('#checkout-dialog');
  const modalObserver = dialog && new MutationObserver(() => {
    if (dialog.open && window.tpvMeasure.start !== null && window.tpvMeasure.dialog === null) window.tpvMeasure.dialog = performance.now();
  });
  if (modalObserver) modalObserver.observe(dialog, {attributes: true, attributeFilter: ['open']});
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
            "barcode_enter",
            "add",
            "quantity_plus",
            "quantity_enter",
            "header",
            "checkout_1",
            "checkout_20",
            "checkout_post_card",
            "checkout_post_cash_exact",
            "checkout_post_cash_change",
            "checkout_post_split",
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
            search_debounce_ms=175,
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
                    if label in ("search", "barcode_enter"):
                        observer = {
                            "event": "keydown" if label == "barcode_enter" else "input",
                            "trigger": "#product-search",
                            "target": "product-grid",
                            "expected": {
                                "selector": "#product-grid .product-card strong",
                                "text": "Producto 0020",
                            },
                        }

                        if label == "barcode_enter":
                            page.locator("#product-search").fill(
                                dataset.products[20].barcode
                            )

                            def action():
                                return page.locator("#product-search").press("Enter")
                        else:

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
                            "target": f"cart-line-{lines[0].pk}",
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
                    elif label.startswith("checkout_post_"):
                        page.locator("[data-checkout-open]").click()
                        form = page.locator("[data-checkout-form]")
                        expect(form).to_be_visible()
                        cash = next(
                            m for m in dataset.methods if m.affects_cash_register
                        )
                        card = next(
                            m for m in dataset.methods if not m.affects_cash_register
                        )
                        if label == "checkout_post_split":
                            form.locator('[name="mode"][value="split"]').check()
                            parts = form.locator("[data-split-part]")
                            parts.nth(0).locator("[data-split-method]").select_option(
                                str(cash.pk)
                            )
                            parts.nth(0).locator('[name$="-amount"]').fill("5.00")
                            parts.nth(0).locator('[name$="-cash_received"]').fill(
                                "20.00"
                            )
                            parts.nth(1).locator("[data-split-method]").select_option(
                                str(card.pk)
                            )
                            parts.nth(1).locator('[name$="-amount"]').fill(
                                str(sale.pending_amount - Decimal("5.00"))
                            )
                        else:
                            method = card if label == "checkout_post_card" else cash
                            form.locator(
                                f'[name="method"][value="{method.pk}"]'
                            ).check()
                            if label == "checkout_post_cash_change":
                                form.locator('[name="cash_received"]').fill("100.00")
                        observer = {
                            "event": "click",
                            "trigger": ".checkout-confirm",
                            "target": "checkout-panel",
                            "expected": {
                                "selector": ".checkout-success h3",
                                "text": "VENTA COMPLETADA",
                            },
                        }

                        def action():
                            return page.locator(".checkout-confirm").click()
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
                    if label in ("search", "barcode_enter"):
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
                            **(
                                {
                                    "click_to_dialog_ms": timing["dialog"]
                                    - timing["start"]
                                }
                                if timing["dialog"] is not None
                                else {}
                            ),
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
        # Persisted economic assertions are outside all measured browser intervals
        # and outside Playwright's async context. Every sample had its own Sale.
        from apps.payments.models import Payment
        from apps.billing.models import BillingDocument
        from apps.cash_register.models import CashMovement

        for label, fixtures in batches.items():
            if not label.startswith("checkout_post_"):
                continue
            for sale, _ in fixtures:
                sale.refresh_from_db()
                self.assertEqual(sale.status, "completed")
                self.assertEqual(sale.pending_amount, Decimal("0.00"))
                payments = list(
                    Payment.objects.filter(sale=sale).select_related("method")
                )
                self.assertEqual(len(payments), 2 if label.endswith("split") else 1)
                self.assertEqual(
                    sum((p.amount for p in payments), Decimal("0.00")),
                    sale.total_amount,
                )
                self.assertEqual(
                    BillingDocument.objects.filter(sale=sale, status="issued").count(),
                    1,
                )
                self.assertEqual(
                    CashMovement.objects.filter(sale=sale).count(),
                    sum(p.method.affects_cash_register for p in payments),
                )
                for payment in payments:
                    if payment.method.affects_cash_register:
                        self.assertEqual(
                            CashMovement.objects.get(payment=payment).amount,
                            payment.amount,
                        )
        result["profiling_seconds"] = round(time.perf_counter() - start, 3)
        result["scenario_count"] = len(result["scenarios"])
        self.output.parent.mkdir(parents=True, exist_ok=True)
        self.output.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n")
