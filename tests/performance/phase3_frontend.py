"""Small actual-browser probes for flush, lost responses and real XHR timeout."""

from pathlib import Path
from threading import Event
from time import perf_counter
from unittest.mock import patch

from django.conf import settings
from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.test import Client
from django.urls import reverse

from e2e.browser_optimistic_cart import JoinedLiveServerThread
from tests.performance.dataset import Dataset
from tests.performance.phase3_harness import economic, guard, save


class FrontendBoundaries(StaticLiveServerTestCase):
    server_thread_class = JoinedLiveServerThread

    def test_browser_boundaries(self):
        guard()
        from playwright.sync_api import expect, sync_playwright
        from apps.sales import checkout

        dataset = Dataset(2, label="phase3-frontend")
        client = Client()
        client.force_login(dataset.user)
        fixtures = {
            name: dataset.sale(1)[0]
            for name in (
                "initialization",
                "pending",
                "lost",
                "timeout",
                "twenty_seconds",
            )
        }
        results = {}
        for name, sale in fixtures.items():
            done = Event()
            original = checkout.issue_sale_document

            def delayed(*args, **kwargs):
                try:
                    Event().wait(20 if name == "twenty_seconds" else 0.8)
                    return original(*args, **kwargs)
                finally:
                    done.set()

            context_patch = (
                patch.object(checkout, "issue_sale_document", delayed)
                if name in ("timeout", "twenty_seconds")
                else patch.object(checkout, "issue_sale_document", original)
            )
            with context_patch, sync_playwright() as p:
                browser = p.chromium.launch(
                    executable_path="/usr/bin/chromium", headless=True
                )
                context = browser.new_context()
                context.add_cookies(
                    [
                        {
                            "name": settings.SESSION_COOKIE_NAME,
                            "value": client.cookies[settings.SESSION_COOKIE_NAME].value,
                            "url": self.live_server_url,
                        }
                    ]
                )
                context.add_init_script(
                    Path(__file__).with_name("phase3-browser.js").read_text()
                )
                page = context.new_page()
                held = {"initial_gets": 0, "posts": 0}

                def sync_route(route):
                    if (
                        name == "initialization"
                        and route.request.method == "GET"
                        and held["initial_gets"] == 0
                    ):
                        held["initial_gets"] += 1
                        # Delay upstream in the browser's network path, not Django.
                        page.wait_for_timeout(300)
                    if name == "pending" and route.request.method == "POST":
                        page.wait_for_timeout(300)
                    route.continue_()

                page.route("**/cart-sync/**", sync_route)
                page.goto(
                    self.live_server_url
                    + reverse("sales:sale_detail", args=[sale.store_id, sale.pk]),
                    wait_until="domcontentloaded",
                )
                page.wait_for_function("window.SalesCartQueue && window.htmx")
                page.evaluate("phase3.installQueue()")
                if name == "pending":
                    page.locator("#product-grid .product-card").first.click()
                page.locator("[data-checkout-open]").click()
                expect(page.locator("[data-checkout-form]")).to_be_visible(
                    timeout=30000
                )
                page.wait_for_function("phase3.open?.frame")
                if name in ("lost", "timeout", "twenty_seconds"):
                    page.locator('[name="method"][data-method-code="card"]').check()
                    if name == "lost":

                        def lose(route):
                            held["posts"] += 1
                            route.fetch()
                            route.abort("failed")

                        page.route("**/checkout/", lose)
                    if name == "timeout":
                        page.evaluate(
                            "document.addEventListener('htmx:beforeRequest', e => {if (e.detail.elt.matches('[data-checkout-form]')) e.detail.xhr.timeout = 250;})"
                        )
                    start = perf_counter()
                    page.locator(".checkout-confirm").click()
                    if name == "twenty_seconds":
                        expect(page.locator(".checkout-success")).to_be_visible(
                            timeout=30000
                        )
                        results[name] = {
                            "elapsed_click_to_success_ms": (perf_counter() - start)
                            * 1000
                        }
                    elif name == "lost":
                        expect(page.locator("#nx-feedback")).to_contain_text(
                            "No podemos confirmar"
                        )
                        page.unroute("**/checkout/", lose)
                    else:
                        page.wait_for_function(
                            "phase3.events.some(e => e.type === 'timeout')"
                        )
                        results[name] = {
                            "timeout_elapsed_ms": (perf_counter() - start) * 1000,
                            "feedback_visible": page.locator(
                                "#nx-feedback"
                            ).is_visible(),
                            "processing": page.locator(
                                "#checkout-dialog"
                            ).get_attribute("data-nx-processing")
                            == "true",
                        }
                        page.wait_for_timeout(1000)
                    if name in ("lost", "timeout"):
                        page.locator(".checkout-confirm").click()
                        expect(page.locator(".checkout-success")).to_be_visible(
                            timeout=30000
                        )
                results.setdefault(name, {})["browser"] = page.evaluate(
                    "({flush: phase3.flush, sync: phase3.sync, open: phase3.open, submit: phase3.submit, events: phase3.events, errors: phase3.errors})"
                )
                results[name]["held_transport"] = held
                browser.close()
            if name in ("timeout", "twenty_seconds"):
                self.assertTrue(done.wait(5))
            state = economic(sale)
            results[name]["economic"] = state
            if name in ("lost", "timeout", "twenty_seconds"):
                self.assertEqual(state["payments"], 1)
                self.assertEqual(state["documents"], 1)
                self.assertEqual(state["stock_movements"], 1)
            save("frontend-boundaries.json", results)
