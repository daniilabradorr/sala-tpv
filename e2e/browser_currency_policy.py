"""E-P01 real Chromium: blocked new checkout and historical reprint."""

import os
from unittest.mock import patch

from django.conf import settings
from django.test import Client
from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.db import connections
from django.urls import reverse
from playwright.sync_api import expect, sync_playwright

from apps.business_config.tests.test_currency_policy import legacy
from e2e import browser_checkout_authorized as authorized
from e2e.browser_optimistic_cart import JoinedLiveServerThread
from tests.performance import phase3_billing_audit as audit


class CurrencyBrowserTests(StaticLiveServerTestCase):
    server_thread_class = JoinedLiveServerThread
    page = authorized.BrowserAuthorizedCheckoutTests.page

    @classmethod
    def setUpClass(cls):
        guard = patch.dict(os.environ, {"DJANGO_ALLOW_ASYNC_UNSAFE": "true"})
        guard.start()
        cls.addClassCleanup(guard.stop)
        super().setUpClass()

    def setUp(self):
        cls = type(self)
        if not cls.server_thread.is_alive():
            cls.server_thread = cls._create_server_thread(
                cls.server_thread.connections_override
            )
            cls.server_thread.daemon = True
            cls.server_thread.start()
            cls.server_thread.is_ready.wait()
            if cls.server_thread.error:
                raise cls.server_thread.error

    def _post_teardown(self):
        self.server_thread.terminate()
        super()._post_teardown()

    def test_non_eur_checkout_cannot_create_economic_effects(self):
        d, sale = audit.fixture("currency-browser-checkout")
        legacy(d)
        before = audit.snapshot(d, [sale])
        with sync_playwright() as p:
            browser = p.chromium.launch(
                executable_path=os.getenv("TPV_CHROMIUM") or None, headless=True
            )
            page, context = self.page(browser, d, sale, 1440)
            try:
                expect(
                    page.get_by_role("alert").filter(has_text="Netxodo solo admite EUR")
                ).to_be_visible()
                page.locator('[name="method"][data-method-code="card"]').check()
                page.locator(".checkout-confirm").click()
                expect(page.locator(".checkout-confirm")).to_be_enabled()
                # Wait for the actual server result, not only the shell warning.
                expect(page.locator("#checkout-process-errors")).to_contain_text(
                    "Netxodo solo admite EUR"
                )
                self.assertEqual(audit.snapshot(d, [sale]), before)
            finally:
                context.close()
                browser.close()
                connections.close_all()

    def test_non_eur_historical_print_is_read_only_and_warns(self):
        d, sale = audit.fixture("currency-browser-print")
        audit.paid(d, sale)
        document = audit.issue(d, sale)
        legacy(d)
        before = audit.snapshot(d, [sale])
        with sync_playwright() as p:
            browser = p.chromium.launch(
                executable_path=os.getenv("TPV_CHROMIUM") or None, headless=True
            )
            client = Client()
            client.force_login(d.user)
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
            context.route(
                "**/*",
                lambda route: (
                    route.continue_()
                    if route.request.url.startswith(self.live_server_url + "/")
                    else route.abort()
                ),
            )
            page = context.new_page()
            try:
                page.goto(
                    self.live_server_url
                    + reverse("billing:document_print", args=[d.store.pk, document.pk])
                )
                expect(page.get_by_role("alert")).to_contain_text("moneda histórica")
                expect(page.locator(".document-print-total")).to_contain_text("12,10 €")
                self.assertEqual(audit.snapshot(d, [sale]), before)
            finally:
                context.close()
                browser.close()
                connections.close_all()
