"""P01/P02 complete cashier flows with real Chromium and test PostgreSQL."""

import os
from decimal import Decimal
from unittest.mock import patch
from uuid import uuid4

from django.conf import settings
from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.core.exceptions import ValidationError
from django.db import connections
from django.test import Client
from django.urls import reverse
from playwright.sync_api import expect, sync_playwright

from apps.sales import checkout
from apps.sales.models import Sale
from apps.sales.services import complete_sale
from apps.payments.services import register_sale_payment
from apps.payments.models import Payment, PaymentMethod
from apps.cash_register.models import CashSession, CashRegister
from apps.cash_register.services import CashRegisterService
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

    def test_p02_explicit_recovery_cash_card_lost_response_and_original_t1(self):
        for width in (1440, 820, 390):
            for label in ("unpaid_cash", "partial_card", "lost_partial", "after_T1"):
                d = Dataset(1, label=f"p02-browser-{width}-{label.lower()}")
                d.settings.allow_split_payments = True
                d.settings.save()
                sale, _ = d.sale(1)
                half = (sale.total_amount / 2).quantize(Decimal(".01"))
                if label != "after_T1":
                    complete_sale(business=d.business, sale=sale, closed_by=d.user)
                    sale.refresh_from_db()
                    if label in ("partial_card", "lost_partial"):
                        register_sale_payment(
                            business=d.business,
                            sale_id=sale.pk,
                            method_id=d.methods[0].pk,
                            amount=half,
                            user=d.user,
                            idempotency_key=uuid4(),
                            cash_session_id=d.session.pk,
                        )
                    CashRegisterService().close_cash_session(
                        business=d.business,
                        store_id=d.store.pk,
                        cash_register_id=d.register.pk,
                        cash_session_id=d.session.pk,
                        user=d.user,
                        counted_cash_amount=half
                        if label != "unpaid_cash"
                        else Decimal("0"),
                    )
                historical = list(
                    Payment.objects.filter(sale=sale).values_list(
                        "idempotency_key", flat=True
                    )
                )
                register = CashRegister.objects.create(
                    business=d.business, store=d.store, name="Recovery", code="RECOVERY"
                )
                session = CashSession.objects.create(
                    business=d.business,
                    store=d.store,
                    cash_register=register,
                    opened_by=d.user,
                )
                with sync_playwright() as p:
                    browser = p.chromium.launch(
                        executable_path=os.getenv("TPV_CHROMIUM") or None, headless=True
                    )
                    page, context = self.page(browser, d, sale, width)
                    try:
                        if label == "after_T1":
                            page.locator(
                                '[name="method"][data-method-code="cash"]'
                            ).check()
                            original = checkout.register_sale_payment
                            original_key = page.locator(
                                '[name="payment_idempotency_key"]'
                            ).input_value()

                            def close_then_pay(**kwargs):
                                CashRegisterService().close_cash_session(
                                    business=d.business,
                                    store_id=d.store.pk,
                                    cash_register_id=d.register.pk,
                                    cash_session_id=d.session.pk,
                                    user=d.user,
                                    counted_cash_amount=Decimal("0"),
                                )
                                return original(**kwargs)

                            with patch.object(
                                checkout, "register_sale_payment", close_then_pay
                            ):
                                page.locator(".checkout-confirm").click()
                                expect(
                                    page.locator("[data-payment-recovery-form]")
                                ).to_be_visible()
                            expect(
                                page.locator('[name="payment_idempotency_key"]')
                            ).to_have_value(original_key)
                        expect(
                            page.locator("[data-payment-recovery-form]")
                        ).to_be_visible()
                        expect(
                            page.locator('[name="recovery_cash_session"]')
                        ).to_have_value("")
                        self.assertLessEqual(
                            page.locator("[data-payment-recovery-form]").evaluate(
                                "form => form.scrollWidth - form.clientWidth"
                            ),
                            2,
                        )

                        page.locator('[name="recovery_cash_session"]').select_option(
                            str(session.pk)
                        )
                        page.locator('[name="method"]').select_option(
                            str(
                                d.methods[
                                    0 if label in ("unpaid_cash", "after_T1") else 1
                                ].pk
                            )
                        )
                        pending_key = page.locator(
                            '[name="payment_idempotency_key"]'
                        ).input_value()
                        billing_key = page.locator(
                            '[name="billing_idempotency_key"]'
                        ).input_value()
                        page.locator('[name="recovery_confirm"]').check()
                        if label == "lost_partial":
                            page.locator('[name="amount"]').fill("3.00")

                            def lose(route):
                                route.fetch()
                                route.abort("failed")

                            page.route("**/checkout/", lose)
                            page.locator(".checkout-confirm").click()
                            expect(page.locator("#nx-feedback")).to_contain_text(
                                "No podemos confirmar el resultado"
                            )
                            page.unroute("**/checkout/", lose)
                            page.locator("[data-nx-checkout-status]").click()
                            expect(
                                page.locator("[data-payment-recovery-form]")
                            ).to_be_visible()
                            expect(
                                page.locator('[name="payment_idempotency_key"]')
                            ).not_to_have_value(pending_key)
                            expect(
                                page.locator('[name="recovery_confirm"]')
                            ).not_to_be_checked()
                            self.assertEqual(
                                Payment.objects.filter(sale=sale).count(), 2
                            )
                            page.locator(
                                '[name="recovery_cash_session"]'
                            ).select_option(str(session.pk))
                            page.locator('[name="method"]').select_option(
                                str(d.methods[1].pk)
                            )
                            page.locator('[name="recovery_confirm"]').check()
                        page.locator(".checkout-confirm").click()
                        expect(page.locator(".checkout-success")).to_be_visible()
                        document = BillingDocument.objects.get(sale=sale)
                        self.assertEqual(str(document.idempotency_key), billing_key)
                        self.assertEqual(document.cash_session_id, d.session.pk)
                        for key in historical:
                            self.assertEqual(
                                Payment.objects.get(
                                    idempotency_key=key, business=d.business
                                ).cash_session_id,
                                d.session.pk,
                            )
                        sale.refresh_from_db()
                        self.assertEqual(sale.cash_session_id, d.session.pk)
                        self.assertEqual(sale.pending_amount, 0)
                        self.assertEqual(
                            Payment.objects.filter(sale=sale).count(),
                            3
                            if label == "lost_partial"
                            else 2
                            if label == "partial_card"
                            else 1,
                        )
                        self.assertEqual(
                            StockMovement.objects.filter(sale=sale).count(), 1
                        )
                        self.assertLessEqual(
                            page.locator("body").evaluate("(body)=>body.scrollWidth"),
                            width + 2,
                        )
                        expect(
                            page.get_by_role(
                                "link", name="IMPRIMIR (abre una nueva pestaña)"
                            )
                        ).to_be_visible()
                        expect(
                            page.locator(
                                ".checkout-success [data-nx-sale-start] button"
                            )
                        ).to_be_enabled()
                        with page.expect_popup() as popup_info:
                            page.get_by_role(
                                "link", name="IMPRIMIR (abre una nueva pestaña)"
                            ).click()
                        popup = popup_info.value
                        popup.wait_for_load_state("load")
                        popup.wait_for_function("window.printCalls === 1")
                        expect(
                            popup.get_by_role("heading", name="FACTURA SIMPLIFICADA")
                        ).to_be_visible()
                        popup.close()
                        previous_url = page.url
                        page.locator(
                            ".checkout-success [data-nx-sale-start] button"
                        ).click()
                        page.wait_for_url(lambda url: url != previous_url)
                        new_sale = (
                            Sale.objects.filter(business=d.business)
                            .exclude(pk=sale.pk)
                            .get()
                        )
                        expect(page).to_have_url(
                            self.live_server_url
                            + reverse(
                                "sales:sale_detail", args=[d.store.pk, new_sale.pk]
                            )
                        )
                        self.assertEqual(new_sale.status, "open")
                        self.assertEqual(new_sale.cash_session_id, session.pk)
                        sale.refresh_from_db()
                        self.assertEqual(sale.cash_session_id, d.session.pk)
                        save_case(
                            f"P02-browser-{label}-{width}",
                            {
                                **state(d, [sale]),
                                "printed": True,
                                "new_sale_in_valid_session": True,
                            },
                        )
                    finally:
                        context.close()
                        browser.close()
                        connections.close_all()
