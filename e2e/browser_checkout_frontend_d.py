"""Block D real-browser regression probes; economic assertions use test PostgreSQL."""

import os
from decimal import Decimal
from threading import Event
from unittest.mock import patch
from uuid import uuid4

from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.db import connections
from playwright.sync_api import expect, sync_playwright

from apps.cash_register.models import CashRegister, CashSession
from apps.cash_register.services import CashRegisterService
from apps.payments.services import register_sale_payment
from apps.sales import checkout
from apps.sales.services import complete_sale
from apps.sales.tests_postgres_recovery import state, save_case
from e2e import browser_checkout_authorized as authorized
from e2e.browser_optimistic_cart import JoinedLiveServerThread
from tests.performance.dataset import Dataset


class CheckoutFrontendDTests(StaticLiveServerTestCase):
    server_thread_class = JoinedLiveServerThread

    def page(self, browser, d, sale, width):
        page, context = authorized.BrowserAuthorizedCheckoutTests.page(
            self, browser, d, sale, width
        )
        page.on("pageerror", lambda error: self.browser_errors.append(str(error)))
        context.on(
            "page",
            lambda opened: opened.on(
                "pageerror", lambda error: self.browser_errors.append(str(error))
            ),
        )
        return page, context

    def tearDown(self):
        super().tearDown()
        self.assertEqual(self.browser_errors, [], "Unexpected browser JavaScript error")

    @classmethod
    def setUpClass(cls):
        guard = patch.dict(os.environ, {"DJANGO_ALLOW_ASYNC_UNSAFE": "true"})
        guard.start()
        cls.addClassCleanup(guard.stop)
        super().setUpClass()

    def setUp(self):
        self.browser_errors = []
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

    def recovery(self, label):
        d = Dataset(1, label=label)
        d.settings.allow_split_payments = True
        d.settings.save()
        sale, _ = d.sale(1)
        complete_sale(business=d.business, sale=sale, closed_by=d.user)
        sale.refresh_from_db()
        half = (sale.total_amount / 2).quantize(Decimal(".01"))
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
            counted_cash_amount=half,
        )
        register = CashRegister.objects.create(
            business=d.business, store=d.store, name="Recovery D", code="RECOVERY"
        )
        session = CashSession.objects.create(
            business=d.business, store=d.store, cash_register=register, opened_by=d.user
        )
        return d, sale, session

    def choose_recovery(self, page, d, session):
        page.locator('[name="recovery_cash_session"]').select_option(str(session.pk))
        page.locator('[name="method"]').select_option(str(d.methods[1].pk))
        page.locator('[name="recovery_confirm"]').check()

    def test_old_read_cannot_replace_newer_confirmed_result(self):
        d, sale, session = self.recovery("d-stale-read")
        with sync_playwright() as p:
            browser = p.chromium.launch(
                executable_path=os.getenv("TPV_CHROMIUM") or None, headless=True
            )
            page, context = self.page(browser, d, sale, 1440)
            held = {}

            def hold(route):
                if route.request.method == "GET" and not held:
                    response = route.fetch()
                    held.update(route=route, response=response)
                    page.evaluate("window.dHeldRead = true")
                else:
                    route.continue_()

            page.route("**/checkout/", hold)
            try:
                page.evaluate(
                    "() => { void htmx.ajax('GET', location.pathname, {source: document.body, target: '#checkout-panel'}).catch(() => {}); }"
                )
                page.wait_for_function("window.dHeldRead")
                self.choose_recovery(page, d, session)
                page.locator(".checkout-confirm").click()
                expect(page.locator(".checkout-success")).to_be_visible()
                page.evaluate(
                    "document.addEventListener('htmx:afterRequest', e => {if (e.detail.requestConfig?.verb === 'get') window.dOldReadDone = true;})"
                )
                held["route"].fulfill(response=held["response"])
                page.wait_for_function("window.dOldReadDone")
                page.evaluate(
                    "() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))"
                )
                self.assertTrue(page.locator(".checkout-success").is_visible())
                final = state(d, [sale])
                self.assertEqual(final["sales"][0]["payments"], 2)
                self.assertEqual(final["sales"][0]["documents"], 1)
                self.assertEqual(final["sales"][0]["stock_movements"], 1)
                save_case("D-stale-read", final)
            finally:
                context.close()
                browser.close()
                connections.close_all()

    def test_processing_blocks_state_read_and_programmatic_second_post(self):
        d, sale, session = self.recovery("d-processing-requests")
        release, entered, finished = Event(), Event(), Event()
        original = checkout.issue_sale_document

        def hold(**kwargs):
            entered.set()
            try:
                if not release.wait(8):
                    raise TimeoutError("test release")
                return original(**kwargs)
            finally:
                finished.set()

        with (
            patch.object(checkout, "issue_sale_document", hold),
            sync_playwright() as p,
        ):
            browser = p.chromium.launch(
                executable_path=os.getenv("TPV_CHROMIUM") or None, headless=True
            )
            page, context = self.page(browser, d, sale, 1440)
            requests = []
            page.on(
                "request",
                lambda r: requests.append(r.method) if "/checkout/" in r.url else None,
            )
            try:
                self.choose_recovery(page, d, session)
                page.locator("[data-checkout-form]").evaluate(
                    "form => window.dPayload = Object.fromEntries(new FormData(form))"
                )
                page.locator(".checkout-confirm").click()
                self.assertTrue(entered.wait(5))
                page.evaluate(
                    "() => { void htmx.ajax('GET', location.pathname, {source: document.body, target: '#checkout-panel'}).catch(() => {}); }"
                )
                page.evaluate(
                    "() => { void htmx.ajax('POST', location.pathname, {source: document.body, target: '#checkout-panel', values: window.dPayload}).catch(() => {}); }"
                )
                page.wait_for_timeout(150)
                self.assertEqual(requests, ["POST"])
                self.assertTrue(page.locator("[data-checkout-form]").is_visible())
                release.set()
                expect(page.locator(".checkout-success")).to_be_visible()
                final = state(d, [sale])
                self.assertEqual(final["sales"][0]["payments"], 2)
                save_case("D-processing-requests", {"requests": requests, **final})
            finally:
                release.set()
                self.assertTrue(finished.wait(8))
                context.close()
                browser.close()
                connections.close_all()

    def test_intentionally_closing_checkout_read_is_not_a_network_failure(self):
        d = Dataset(1, label="d-cancel-read")
        sale, _ = d.sale(1)
        with sync_playwright() as p:
            browser = p.chromium.launch(
                executable_path=os.getenv("TPV_CHROMIUM") or None, headless=True
            )
            # Open normally first, then hold a second opening before its response.
            page, context = self.page(browser, d, sale, 1440)
            page.locator("[data-checkout-close]").click()
            held = {}

            def hold(route):
                held["route"] = route
                page.evaluate("window.dHeldRead = true")

            page.route("**/checkout/", hold)
            try:
                page.locator("[data-checkout-open]").click()
                page.wait_for_function("window.dHeldRead")
                page.keyboard.press("Escape")
                expect(page.locator("#checkout-dialog")).not_to_be_visible()
                page.wait_for_timeout(150)
                expect(page.locator("#nx-feedback")).to_be_hidden()
                final = state(d, [sale])
                self.assertEqual(final["sales"][0]["payments"], 0)
                save_case("D-cancel-read", final)
            finally:
                context.close()
                browser.close()
                connections.close_all()

    def test_performance_warm_card_f2(self):
        from pathlib import Path

        observer = (
            Path(__file__).with_name("checkout_frontend_d_observer.js").read_text()
        )
        d = Dataset(1, label="d-performance")
        sales = [d.sale(1)[0] for _ in range(5)]
        results = []
        with sync_playwright() as p:
            browser = p.chromium.launch(
                executable_path=os.getenv("TPV_CHROMIUM") or None, headless=True
            )
            try:
                for sale in sales:
                    page, context = self.page(browser, d, sale, 1440)
                    try:
                        baseline = os.getenv("TPV_D_BASELINE_STATIC_DIR")
                        if baseline:

                            def base_asset(route):
                                relative = route.request.url.split("/static/js/", 1)[
                                    1
                                ].split("?", 1)[0]
                                path = Path(baseline) / relative
                                if path.is_file():
                                    route.fulfill(
                                        path=path, content_type="application/javascript"
                                    )
                                else:
                                    route.continue_()

                            context.route("**/static/js/**", base_asset)
                        page.reload()
                        page.locator("[data-checkout-open]").click()
                        expect(page.locator("[data-checkout-form]")).to_be_visible()
                        page.locator("[data-checkout-close]").click()
                        page.evaluate(observer)
                        page.locator("[data-checkout-open]").click()
                        expect(page.locator("[data-checkout-form]")).to_be_visible()
                        page.locator('[name="method"][data-method-code="card"]').check()
                        page.locator(".checkout-confirm").click()
                        page.wait_for_function(
                            "checkoutDProbe.records.some(r => r.name === 'settled-painted' && r.method === 'POST')"
                        )
                        context.add_init_script(observer)
                        with page.expect_popup() as info:
                            page.get_by_role(
                                "link", name="IMPRIMIR (abre una nueva pestaña)"
                            ).click()
                        popup = info.value
                        popup.wait_for_function(
                            "checkoutDProbe.records.some(r => r.name === 'page-painted')"
                        )
                        timings = page.evaluate("checkoutDProbe")
                        print_timings = popup.evaluate("checkoutDProbe")
                        popup.close()
                        final = state(d, [sale])
                        self.assertEqual(final["sales"][0]["payments"], 1)
                        self.assertEqual(final["sales"][0]["documents"], 1)
                        self.assertEqual(final["sales"][0]["stock_movements"], 1)
                        results.append(
                            {
                                "events": timings["records"],
                                "time_origin": timings["timeOrigin"],
                                "print_events": print_timings["records"],
                                "print_time_origin": print_timings["timeOrigin"],
                                "economic_state": final,
                            }
                        )
                    finally:
                        context.close()
                        connections.close_all()
            finally:
                browser.close()
                connections.close_all()
        save_case(
            "D-performance",
            {
                "mode": "warm reopening; 1 line card F2; five fresh sales",
                "samples": results,
            },
        )

    def test_422_focus_and_field_errors_are_associated(self):
        d = Dataset(1, label="d-field-errors")
        sale, _ = d.sale(1)
        with sync_playwright() as p:
            browser = p.chromium.launch(
                executable_path=os.getenv("TPV_CHROMIUM") or None, headless=True
            )
            page, context = self.page(browser, d, sale, 1440)
            try:
                page.locator('[name="method"][data-method-code="cash"]').check()
                page.locator("[data-checkout-form]").evaluate(
                    "form => form.noValidate = true"
                )
                page.locator('[name="cash_received"]').fill("-1")
                with page.expect_response(
                    lambda r: "/checkout/" in r.url and r.request.method == "POST"
                ) as response:
                    page.locator(".checkout-confirm").click()
                self.assertEqual(response.value.status, 422)
                summary = page.locator("[data-checkout-error-summary]")
                expect(summary).to_be_visible()
                expect(summary).to_be_focused()
                expect(page.locator('[name="cash_received"]')).to_have_attribute(
                    "aria-invalid", "true"
                )
                self.assertTrue(
                    page.locator('[name="cash_received"]').get_attribute(
                        "aria-describedby"
                    )
                )
                final = state(d, [sale])
                self.assertEqual(final["sales"][0]["payments"], 0)
                save_case("D-errors-focus", final)
            finally:
                context.close()
                browser.close()
                connections.close_all()

    def test_p02_displays_change_for_the_selected_piece(self):
        d, sale, session = self.recovery("d-piece-change")
        with sync_playwright() as p:
            browser = p.chromium.launch(
                executable_path=os.getenv("TPV_CHROMIUM") or None, headless=True
            )
            page, context = self.page(browser, d, sale, 390)
            try:
                expect(page.locator('[name="recovery_cash_session"]')).to_be_focused()
                page.locator('[name="method"]').select_option(str(d.methods[0].pk))
                page.locator('[name="amount"]').fill("3.00")
                page.locator('[name="cash_received"]').fill("10.00")
                expect(page.locator("[data-recovery-cash-change]")).to_have_text(
                    "7,00 €"
                )
                page.locator('[name="method"]').select_option(str(d.methods[1].pk))
                expect(page.locator("[data-recovery-change]")).to_be_hidden()
                self.choose_recovery(page, d, session)
                pending_key = page.locator(
                    '[name="payment_idempotency_key"]'
                ).input_value()
                with page.expect_response(
                    lambda r: "/checkout/" in r.url and r.request.method == "POST"
                ) as response:
                    page.locator(".checkout-confirm").click()
                self.assertEqual(response.value.status, 200)
                expect(
                    page.locator('[name="payment_idempotency_key"]')
                ).not_to_have_value(pending_key)
                expect(page.locator("[data-payment-recovery-form]")).to_be_visible()
                final = state(d, [sale])
                self.assertEqual(final["sales"][0]["payments"], 2)
                self.assertEqual(final["sales"][0]["documents"], 0)
                self.assertEqual(final["sales"][0]["cash_movements"], 1)
                save_case("D-piece-change", final)
            finally:
                context.close()
                browser.close()
                connections.close_all()

    def test_card_cash_split_f1_print_cancel_repeat_and_new_sale(self):
        from django.urls import reverse
        from apps.billing.models import BillingDocument
        from apps.sales.models import Sale

        with sync_playwright() as p:
            browser = p.chromium.launch(
                executable_path=os.getenv("TPV_CHROMIUM") or None, headless=True
            )
            try:
                for mode in ("card", "cash", "split", "invoice", "p01"):
                    d = Dataset(1, label=f"d-full-{mode}")
                    d.settings.allow_split_payments = True
                    d.settings.save()
                    sale, _ = d.sale(
                        1,
                        customer=d.customers[0] if mode == "invoice" else None,
                        document="invoice" if mode == "invoice" else "ticket",
                    )
                    page, context = self.page(browser, d, sale, 1440)
                    requests = []
                    page.on(
                        "response",
                        lambda r: (
                            requests.append(
                                {"method": r.request.method, "status": r.status}
                            )
                            if "/checkout/" in r.url
                            else None
                        ),
                    )
                    try:
                        if mode == "p01":
                            from django.core.exceptions import ValidationError
                            from apps.payments.models import PaymentMethod

                            page.locator(
                                '[name="method"][data-method-code="card"]'
                            ).check()
                            with patch.object(
                                checkout,
                                "issue_sale_document",
                                side_effect=ValidationError(
                                    "Synthetic Billing failure"
                                ),
                            ):
                                page.locator(".checkout-confirm").click()
                                expect(page.locator(".recovery-note")).to_contain_text(
                                    "El cobro se ha registrado correctamente"
                                )
                            PaymentMethod.objects.filter(pk=d.methods[1].pk).update(
                                is_active=False
                            )
                        original_keys = page.locator("[data-checkout-form]").evaluate(
                            "form => [...new FormData(form)].filter(([k]) => k.endsWith('idempotency_key')).map(([,v]) => v)"
                        )
                        if mode == "split":
                            page.locator('[name="mode"][value="split"]').check()
                            for i, method in enumerate(d.methods):
                                page.locator(
                                    f'[name="payments-{i}-method"]'
                                ).select_option(str(method.pk))
                                page.locator(f'[name="payments-{i}-amount"]').fill(
                                    "6.05"
                                )
                        elif mode != "p01":
                            code = "cash" if mode == "cash" else "card"
                            page.locator(
                                f'[name="method"][data-method-code="{code}"]'
                            ).check()
                            if code == "cash":
                                page.locator('[name="cash_received"]').fill("20")
                                expect(page.locator("[data-cash-change]")).to_have_text(
                                    "7,90 €"
                                )
                        page.locator(".checkout-confirm").focus()
                        page.keyboard.press("Enter")
                        expect(page.locator(".checkout-success")).to_be_visible()
                        document = BillingDocument.objects.get(sale=sale)
                        self.assertEqual(
                            document.document_type, "F1" if mode == "invoice" else "F2"
                        )
                        before = state(d, [sale])
                        for _ in range(2):
                            with page.expect_popup() as popup_info:
                                page.get_by_role(
                                    "link", name="IMPRIMIR (abre una nueva pestaña)"
                                ).click()
                            popup = popup_info.value
                            popup.wait_for_function("window.printCalls === 1")
                            expect(popup.locator("body")).to_contain_text(
                                document.series_text
                            )
                            # Stub returns without printing, modelling dismissal; then close.
                            popup.close()
                        self.assertEqual(state(d, [sale]), before)
                        previous = page.url
                        page.locator(
                            ".checkout-success [data-nx-sale-start] button"
                        ).click()
                        page.wait_for_url(lambda u: u != previous)
                        new_sale = (
                            Sale.objects.filter(business=d.business)
                            .exclude(pk=sale.pk)
                            .get()
                        )
                        self.assertEqual(new_sale.status, "open")
                        self.assertEqual(new_sale.total_amount, 0)
                        self.assertEqual(new_sale.lines.count(), 0)
                        self.assertEqual(new_sale.payments.count(), 0)
                        self.assertEqual(new_sale.cash_session_id, d.session.pk)
                        expect(page).to_have_url(
                            self.live_server_url
                            + reverse(
                                "sales:sale_detail", args=[d.store.pk, new_sale.pk]
                            )
                        )
                        page.locator("#product-grid .product-card").first.click()
                        page.locator("[data-checkout-open]").click()
                        expect(page.locator("[data-checkout-form]")).to_be_visible()
                        new_keys = page.locator("[data-checkout-form]").evaluate(
                            "form => [...new FormData(form)].filter(([k]) => k.endsWith('idempotency_key')).map(([,v]) => v)"
                        )
                        self.assertTrue(set(original_keys).isdisjoint(new_keys))
                        final = state(d, [sale])
                        self.assertEqual(
                            final["sales"][0]["payments"], 2 if mode == "split" else 1
                        )
                        self.assertEqual(final["sales"][0]["documents"], 1)
                        self.assertEqual(final["sales"][0]["stock_movements"], 1)
                        save_case(
                            f"D-full-{mode}",
                            {
                                "http": requests,
                                "print_calls": 2,
                                "print_no_mutation": True,
                                "new_sale_empty_and_new_keys": True,
                                **final,
                            },
                        )
                    finally:
                        context.close()
                        connections.close_all()
            finally:
                browser.close()
                connections.close_all()

    def test_real_timeout_before_t1_queries_instead_of_reposting(self):
        from apps.sales.views import SaleCheckoutView

        d = Dataset(1, label="d-timeout-before-t1")
        sale, _ = d.sale(1)
        entered, release, finished = Event(), Event(), Event()
        original = SaleCheckoutView.post

        def delayed(view, request, *args, **kwargs):
            entered.set()
            try:
                if not release.wait(8):
                    raise TimeoutError("test release")
                return original(view, request, *args, **kwargs)
            finally:
                finished.set()

        with sync_playwright() as p:
            browser = p.chromium.launch(
                executable_path=os.getenv("TPV_CHROMIUM") or None, headless=True
            )
            page, context = self.page(browser, d, sale, 1440)
            try:
                page.locator('[name="method"][data-method-code="card"]').check()
                page.evaluate(
                    "document.addEventListener('htmx:beforeRequest', e => {if(e.detail.requestConfig?.verb === 'post') {window.dDefaultTimeout=e.detail.xhr.timeout; e.detail.xhr.timeout=250;}})"
                )
                posts = []
                page.on(
                    "request",
                    lambda r: (
                        posts.append(True)
                        if "/checkout/" in r.url and r.method == "POST"
                        else None
                    ),
                )
                with patch.object(SaleCheckoutView, "post", delayed):
                    page.locator(".checkout-confirm").click()
                    self.assertTrue(entered.wait(5))
                    expect(page.locator("#nx-feedback")).to_contain_text(
                        "No podemos confirmar el resultado"
                    )
                    expect(page.locator(".checkout-confirm")).to_be_disabled()
                    self.assertEqual(page.evaluate("window.dDefaultTimeout"), 60000)
                    before = state(d, [sale])
                    self.assertEqual(before["sales"][0]["sale"], "open")
                    self.assertEqual(before["sales"][0]["payments"], 0)
                    release.set()
                    self.assertTrue(finished.wait(8))
                page.locator("[data-nx-checkout-status]").click()
                expect(page.locator(".checkout-success")).to_be_visible()
                self.assertEqual(len(posts), 1)
                final = state(d, [sale])
                self.assertEqual(final["sales"][0]["payments"], 1)
                self.assertEqual(final["sales"][0]["documents"], 1)
                save_case(
                    "D-timeout-before-t1",
                    {
                        "before": before,
                        "after": final,
                        "posts": len(posts),
                        "default_timeout_ms": 60000,
                        "injected_timeout_ms": 250,
                    },
                )
            finally:
                release.set()
                if entered.is_set():
                    self.assertTrue(finished.wait(8))
                context.close()
                browser.close()
                connections.close_all()

    def test_stale_version_and_revoked_permission_have_no_effects(self):
        from apps.users.models import RoleChoices
        from apps.sales.tests.factories import create_store_access

        with sync_playwright() as p:
            browser = p.chromium.launch(
                executable_path=os.getenv("TPV_CHROMIUM") or None, headless=True
            )
            try:
                for label, status in (("version", 409), ("permission", 403)):
                    d = Dataset(1, label=f"d-{label}")
                    sale, _ = d.sale(1)
                    page, context = self.page(browser, d, sale, 1440)
                    try:
                        page.locator('[name="method"][data-method-code="card"]').check()
                        if label == "version":
                            sale.cart_version += 1
                            sale.save(update_fields=["cart_version"])
                        else:
                            create_store_access(
                                business=d.business,
                                user=d.user,
                                store=d.store,
                                can_sell=False,
                            )
                            d.user.role = RoleChoices.CASHIER
                            d.user.save(update_fields=["role"])
                        with page.expect_response(
                            lambda r: (
                                "/checkout/" in r.url and r.request.method == "POST"
                            )
                        ) as response:
                            page.locator(".checkout-confirm").click()
                        self.assertEqual(response.value.status, status)
                        if label == "permission":
                            expect(page.locator("#nx-feedback")).to_contain_text(
                                "No tienes permiso"
                            )
                        else:
                            expect(
                                page.locator("[data-checkout-error-summary]")
                            ).to_be_visible()
                        final = state(d, [sale])
                        self.assertEqual(final["sales"][0]["payments"], 0)
                        self.assertEqual(final["sales"][0]["stock_movements"], 0)
                        self.assertEqual(final["sales"][0]["documents"], 0)
                        save_case(f"D-{label}", {"http": status, **final})
                    finally:
                        context.close()
                        connections.close_all()
            finally:
                browser.close()
                connections.close_all()

    def test_touch_landscape_zoom_keyboard_and_focus_return(self):

        d = Dataset(1, label="d-responsive")
        sales = [d.sale(1)[0] for _ in range(6)]
        sizes = [
            (390, 844),
            (844, 390),
            (820, 1180),
            (1180, 820),
            (1440, 900),
            (820, 1180),
        ]
        results = []
        with sync_playwright() as p:
            browser = p.chromium.launch(
                executable_path=os.getenv("TPV_CHROMIUM") or None, headless=True
            )
            try:
                for index, (sale, (width, height)) in enumerate(
                    zip(sales, sizes, strict=True)
                ):
                    page, context = self.page(browser, d, sale, width)
                    try:
                        page.set_viewport_size({"width": width, "height": height})
                        if index == 5:
                            page.evaluate("document.documentElement.style.zoom = '2'")
                        if width < 1440:
                            page.locator(".payment-method.method-cash").tap()
                        else:
                            page.locator(
                                '[name="method"][data-method-code="cash"]'
                            ).check()
                        page.locator('[name="cash_received"]').fill("20")
                        expect(page.locator("[data-cash-change]")).to_have_text(
                            "7,90 €"
                        )
                        bounds = page.locator(".checkout-confirm").bounding_box()
                        self.assertGreaterEqual(bounds["height"], 44)
                        overflow = page.locator("[data-checkout]").evaluate(
                            "el => el.scrollWidth - el.clientWidth"
                        )
                        self.assertLessEqual(
                            overflow, 2, (width, height, index, overflow)
                        )
                        if index == 0:
                            page.screenshot(
                                path="/workspace/work/phase3-d/mobile-checkout.png"
                            )
                        if index == 2:
                            page.screenshot(
                                path="/workspace/work/phase3-d/tablet-checkout.png"
                            )
                        page.keyboard.press("Escape")
                        expect(page.locator("#checkout-dialog")).not_to_be_visible()
                        expect(page.locator("[data-checkout-open]")).to_be_focused()
                        page.keyboard.press("Enter")
                        try:
                            expect(page.locator("[data-checkout-form]")).to_be_visible()
                        except AssertionError:
                            save_case(
                                "D-responsive-failure",
                                {
                                    "index": index,
                                    "view": page.evaluate(
                                        "({panel:document.querySelector('#checkout-panel').innerText, dialog:document.querySelector('#checkout-dialog').open, active:document.activeElement.tagName, queue:{busy:tpvCart.busy,frozen:tpvCart.frozen,error:tpvCart.error}, drawer:document.querySelector('#sale-cart').open})"
                                    ),
                                },
                            )
                            raise
                        final = state(d, [sale])
                        self.assertEqual(final["sales"][0]["payments"], 0)
                        results.append(
                            {
                                "width": width,
                                "height": height,
                                "css_zoom": 2 if index == 5 else 1,
                                "overflow_px": overflow,
                                "confirm_height_px": bounds["height"],
                                **final,
                            }
                        )
                    finally:
                        context.close()
                        connections.close_all()
            finally:
                browser.close()
                connections.close_all()
        save_case("D-responsive-keyboard", {"samples": results})

    def test_expired_session_cart_read_has_clear_message_and_keeps_intent(self):
        d = Dataset(1, label="d-expired-cart-read")
        sale, _ = d.sale(1)
        with sync_playwright() as p:
            browser = p.chromium.launch(
                executable_path=os.getenv("TPV_CHROMIUM") or None, headless=True
            )
            page, context = self.page(browser, d, sale, 1440)
            try:
                page.locator("[data-checkout-close]").click()
                page.wait_for_function("tpvCart.protocolReady && !tpvCart.busy")
                page.evaluate("tpvCart.busy=true")
                page.locator("#product-grid .product-card").first.click()
                keys = page.evaluate("tpvCart.ops.map(op => op.key)")
                self.assertEqual(len(keys), 1)
                context.clear_cookies()
                message = page.evaluate(
                    "async () => {try {await tpvCart.refresh(); return '';} catch(e) {return e.message;} }"
                )
                self.assertIn("Comprueba sesión y permisos", message)
                self.assertNotIn("JSON", message)
                self.assertEqual(page.evaluate("tpvCart.ops.map(op => op.key)"), keys)
                final = state(d, [sale])
                self.assertEqual(final["sales"][0]["payments"], 0)
                self.assertEqual(sale.lines.count(), 1)
                save_case(
                    "D-expired-cart-read",
                    {"message": message, "pending_identity_preserved": True, **final},
                )
            finally:
                context.close()
                browser.close()
                connections.close_all()

    def test_double_open_and_repeated_modal_cycles_send_one_read_per_open(self):
        d = Dataset(1, label="d-double-open")
        sale, _ = d.sale(1)
        with sync_playwright() as p:
            browser = p.chromium.launch(
                executable_path=os.getenv("TPV_CHROMIUM") or None, headless=True
            )
            page, context = self.page(browser, d, sale, 1440)
            requests = []
            page.on(
                "request",
                lambda r: requests.append(r.method) if "/checkout/" in r.url else None,
            )
            try:
                page.locator("[data-checkout-close]").click()
                page.locator("[data-checkout-open]").dblclick()
                expect(page.locator("[data-checkout-form]")).to_be_visible()
                self.assertEqual(requests, ["GET"])
                for _ in range(5):
                    page.keyboard.press("Escape")
                    expect(page.locator("[data-checkout-open]")).to_be_focused()
                    page.keyboard.press("Enter")
                    expect(page.locator("[data-checkout-form]")).to_be_visible()
                self.assertEqual(requests, ["GET"] * 6)
                final = state(d, [sale])
                self.assertEqual(final["sales"][0]["payments"], 0)
                save_case("D-double-open-cycles", {"methods": requests, **final})
            finally:
                context.close()
                browser.close()
                connections.close_all()

    def test_second_tab_changes_cart_then_checkout_requires_review(self):
        from django.urls import reverse

        d = Dataset(1, label="d-two-browser-tabs")
        sale, _ = d.sale(1)
        with sync_playwright() as p:
            browser = p.chromium.launch(
                executable_path=os.getenv("TPV_CHROMIUM") or None, headless=True
            )
            page, context = self.page(browser, d, sale, 1440)
            try:
                page.locator('[name="method"][data-method-code="card"]').check()
                version = page.locator('[name="cart_version"]').input_value()
                second = context.new_page()
                second.goto(
                    self.live_server_url
                    + reverse("sales:sale_detail", args=[d.store.pk, sale.pk])
                )
                second.wait_for_function("tpvCart.protocolReady && !tpvCart.busy")
                second.locator("#product-grid .product-card").first.click()
                second.wait_for_function(
                    "(v) => !tpvCart.busy && !tpvCart.ops.length && tpvCart.cart.version > Number(v)",
                    arg=version,
                )
                page.bring_to_front()
                expect(page.locator('[name="cart_version"]')).to_have_value(version)
                with page.expect_response(
                    lambda r: "/checkout/" in r.url and r.request.method == "POST"
                ) as response:
                    page.locator(".checkout-confirm").click()
                self.assertEqual(response.value.status, 409)
                expect(page.locator("[data-checkout-error-summary]")).to_be_visible()
                before = state(d, [sale])
                self.assertEqual(before["sales"][0]["payments"], 0)
                expect(page.locator('[name="cart_version"]')).not_to_have_value(version)
                expect(page.locator(".checkout-total")).to_contain_text("24,20")
                page.locator('[name="method"][data-method-code="card"]').check()
                page.locator(".checkout-confirm").click()
                expect(page.locator(".checkout-success")).to_be_visible()
                final = state(d, [sale])
                self.assertEqual(final["sales"][0]["confirmed_amount"], "24.20")
                self.assertEqual(final["sales"][0]["payments"], 1)
                self.assertEqual(final["inventory"], ["998.000"])
                save_case(
                    "D-two-browser-tabs",
                    {"http": [409, 200], "before": before, "after": final},
                )
            finally:
                context.close()
                browser.close()
                connections.close_all()

    def test_sampled_contrast_and_native_control_labels(self):
        import re

        d = Dataset(1, label="d-contrast-labels")
        sale, _ = d.sale(1)
        with sync_playwright() as p:
            browser = p.chromium.launch(
                executable_path=os.getenv("TPV_CHROMIUM") or None, headless=True
            )
            page, context = self.page(browser, d, sale, 1440)
            try:
                colours = page.evaluate("""() => ['.checkout-total strong', '.checkout-confirm'].map(selector => {
                    const el=document.querySelector(selector); let parent=el;
                    while (parent.parentElement && getComputedStyle(parent).backgroundColor === 'rgba(0, 0, 0, 0)') parent=parent.parentElement;
                    return {selector, foreground:getComputedStyle(el).color, background:getComputedStyle(parent).backgroundColor};
                })""")
                for sample in colours:

                    def luminance(colour):
                        rgb = [
                            float(v) / 255 for v in re.findall(r"[\d.]+", colour)[:3]
                        ]
                        linear = [
                            v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4
                            for v in rgb
                        ]
                        return sum(
                            v * coefficient
                            for v, coefficient in zip(
                                linear, (0.2126, 0.7152, 0.0722), strict=True
                            )
                        )

                    foreground, background = (
                        luminance(sample["foreground"]),
                        luminance(sample["background"]),
                    )
                    ratio = (max(foreground, background) + 0.05) / (
                        min(foreground, background) + 0.05
                    )
                    self.assertGreaterEqual(ratio, 4.5, sample)
                    sample["ratio"] = round(ratio, 2)
                missing = page.locator("[data-checkout-form]").evaluate(
                    """form => [...form.elements].filter(el => el.matches('input:not([type=hidden]), select, textarea') && el.getClientRects().length && !el.labels?.length && !el.getAttribute('aria-label')).map(el => el.name)"""
                )
                self.assertEqual(missing, [])
                self.assertTrue(
                    page.locator("[data-checkout]").get_attribute("aria-live")
                )
                save_case(
                    "D-contrast-labels",
                    {
                        "samples": colours,
                        "unlabelled_visible_fields": missing,
                        **state(d, [sale]),
                    },
                )
            finally:
                context.close()
                browser.close()
                connections.close_all()

    def test_navigation_during_cart_sync_preserves_and_replays_original_intent(self):
        from playwright.sync_api import Error
        from apps.sales.models import CartOperation

        d = Dataset(1, label="d-navigation-pending")
        sale, _ = d.sale(1)
        with sync_playwright() as p:
            browser = p.chromium.launch(
                executable_path=os.getenv("TPV_CHROMIUM") or None, headless=True
            )
            page, context = self.page(browser, d, sale, 1440)
            held = []

            def hold(route):
                if route.request.method == "POST":
                    held.append(route)
                else:
                    route.continue_()

            try:
                page.locator("[data-checkout-close]").click()
                page.wait_for_function("tpvCart.protocolReady && !tpvCart.busy")
                sale_url = page.url
                page.route("**/cart-sync/", hold)
                page.locator("#product-grid .product-card").first.click()
                page.wait_for_function("tpvCart.busy && tpvCart.ops.length === 1")
                keys = page.evaluate("tpvCart.ops.map(op => op.key)")

                def dismiss(dialog):
                    self.assertEqual(dialog.type, "beforeunload")
                    dialog.dismiss()

                page.on("dialog", dismiss)
                with self.assertRaises(Error):
                    page.goto(self.live_server_url + "/")
                self.assertEqual(page.url, sale_url)
                self.assertEqual(page.evaluate("tpvCart.ops.map(op => op.key)"), keys)
                page.remove_listener("dialog", dismiss)
                page.on("dialog", lambda dialog: dialog.accept())
                page.goto(self.live_server_url + "/")
                page.unroute("**/cart-sync/", hold)
                page.goto(sale_url)
                page.wait_for_function(
                    "window.tpvCart?.protocolReady && !tpvCart.busy && !tpvCart.ops.length"
                )
                self.assertEqual(sum(line.quantity for line in sale.lines.all()), 2)
                self.assertEqual(CartOperation.objects.filter(sale=sale).count(), 1)
                self.assertEqual(str(CartOperation.objects.get(sale=sale).key), keys[0])
                final = state(d, [sale])
                self.assertEqual(final["sales"][0]["payments"], 0)
                save_case(
                    "D-navigation-pending",
                    {
                        "navigation_dismissed_then_accepted": True,
                        "original_operation_replayed_once": True,
                        **final,
                    },
                )
            finally:
                context.close()
                browser.close()
                connections.close_all()

    def test_pending_quantities_flush_before_authoritative_checkout(self):
        d = Dataset(1, label="d-pending-quantities")
        sale, _ = d.sale(1)
        with sync_playwright() as p:
            browser = p.chromium.launch(
                executable_path=os.getenv("TPV_CHROMIUM") or None, headless=True
            )
            page, context = self.page(browser, d, sale, 1440)
            held = []

            def hold_first(route):
                if route.request.method == "POST" and not held:
                    held.append(route)
                else:
                    route.continue_()

            try:
                page.locator("[data-checkout-close]").click()
                page.wait_for_function(
                    "tpvCart.protocolReady && !tpvCart.busy && !tpvCart.frozen"
                )
                page.route("**/cart-sync/", hold_first)
                with page.expect_request(
                    lambda r: "/cart-sync/" in r.url and r.method == "POST"
                ):
                    page.locator("[data-plus]").first.click()
                page.locator("[data-plus]").first.click()
                page.wait_for_function("tpvCart.busy && tpvCart.ops.length >= 2")
                page.locator("[data-checkout-open]").click()
                expect(page.locator(".checkout-loading")).to_be_visible()
                expect(page.locator("[data-checkout-form]")).to_have_count(0)
                self.assertEqual(sum(line.quantity for line in sale.lines.all()), 1)
                self.assertEqual(len(held), 1)
                held[0].continue_()
                expect(page.locator("[data-checkout-form]")).to_be_visible()
                expect(page.locator(".checkout-total")).to_contain_text("36,30")
                self.assertEqual(sum(line.quantity for line in sale.lines.all()), 3)
                page.locator('[name="method"][data-method-code="card"]').check()
                page.locator(".checkout-confirm").click()
                expect(page.locator(".checkout-success")).to_be_visible()
                final = state(d, [sale])
                self.assertEqual(final["sales"][0]["confirmed_amount"], "36.30")
                self.assertEqual(final["sales"][0]["payments"], 1)
                self.assertEqual(final["sales"][0]["documents"], 1)
                self.assertEqual(final["sales"][0]["stock_movements"], 1)
                self.assertEqual(final["inventory"], ["997.000"])
                save_case("D-pending-quantities", final)
            finally:
                context.close()
                browser.close()
                connections.close_all()
