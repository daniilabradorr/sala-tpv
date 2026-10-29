"""P01 Billing recovery cashier flow with real Chromium and test PostgreSQL."""

import os
from unittest.mock import patch

from django.conf import settings
from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.core.exceptions import ValidationError
from django.db import connections
from django.test import Client
from django.urls import reverse
from playwright.sync_api import expect, sync_playwright

from apps.payments.models import Payment, PaymentMethod
from apps.billing.models import BillingDocument
from apps.inventory.models import StockMovement
from apps.sales.tests_postgres_recovery import state, save_case
from e2e.browser_optimistic_cart import JoinedLiveServerThread
from tests.performance.dataset import Dataset


class BrowserAuthorizedCheckoutTests(StaticLiveServerTestCase):
    server_thread_class = JoinedLiveServerThread

    @classmethod
    def setUpClass(cls):
        # Playwright's sync driver owns an event loop in this test thread; ORM
        # calls here remain synchronous, separate from the HTTP server threads.
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

    def page(self, browser, d, sale, width):
        client = Client()
        client.force_login(d.user)
        context = browser.new_context(
            viewport={"width": width, "height": 900}, has_touch=width < 1440
        )
        context.add_init_script(
            "window.printCalls = 0; window.print = () => { window.printCalls += 1; };"
        )
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
        page.goto(
            self.live_server_url
            + reverse("sales:sale_detail", args=[sale.store_id, sale.pk])
        )
        if page.locator("[data-checkout-open]").count():
            if width < 1200 and not page.locator("[data-checkout-open]").is_visible():
                page.locator('[data-nx-drawer-trigger="sale-cart"]').click()
            page.locator("[data-checkout-open]").click()
        else:
            page.get_by_role("link", name="Recuperar checkout", exact=True).click()
        expect(page.locator("[data-checkout-form]")).to_be_visible()
        return page, context

    def test_p01_inactive_method_reopen_preserves_billing_identity(self):
        for width in (1440, 820, 390):
            d = Dataset(1, label=f"p01-browser-{width}")
            sale, _ = d.sale(1)
            with sync_playwright() as p:
                browser = p.chromium.launch(
                    executable_path=os.getenv("TPV_CHROMIUM") or None, headless=True
                )
                page, context = self.page(browser, d, sale, width)
                try:
                    page.locator('[name="method"][data-method-code="card"]').check()
                    billing = page.locator(
                        '[name="billing_idempotency_key"]'
                    ).input_value()
                    with patch(
                        "apps.sales.checkout.issue_sale_document",
                        side_effect=ValidationError("Synthetic Billing failure"),
                    ):
                        page.locator(".checkout-confirm").click()
                        expect(page.locator(".recovery-note")).to_contain_text(
                            "El cobro se ha registrado correctamente"
                        )
                    PaymentMethod.objects.filter(business=d.business).update(
                        is_active=False
                    )
                    page.locator("[data-checkout-close]").click()
                    if (
                        width < 1200
                        and not page.locator("[data-checkout-open]").is_visible()
                    ):
                        page.locator('[data-nx-drawer-trigger="sale-cart"]').click()
                    page.locator("[data-checkout-open]").click()
                    expect(
                        page.locator('[name="billing_idempotency_key"]')
                    ).to_have_value(billing)
                    page.get_by_role("button", name="REINTENTAR EMISIÓN").click()
                    expect(page.locator(".checkout-success")).to_be_visible()
                    self.assertEqual(Payment.objects.filter(sale=sale).count(), 1)
                    document = BillingDocument.objects.get(sale=sale)
                    self.assertEqual(str(document.idempotency_key), billing)
                    self.assertEqual(StockMovement.objects.filter(sale=sale).count(), 1)
                    expect(
                        page.get_by_role(
                            "link", name="IMPRIMIR (abre una nueva pestaña)"
                        )
                    ).to_be_visible()
                    expect(
                        page.locator(".checkout-success [data-nx-sale-start] button")
                    ).to_be_enabled()
                    save_case(f"P01-browser-{width}", state(d, [sale]))
                finally:
                    context.close()
                    browser.close()
                    connections.close_all()
