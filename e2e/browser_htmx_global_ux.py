"""Real-browser coverage for the global HTMX UX contract.

Run with::

    python manage.py test e2e.browser_htmx_global_ux
"""

import re

from django.conf import settings
from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.test import override_settings
from playwright.sync_api import expect, sync_playwright

from apps.onboarding.demo_seed import DemoBusinessSeeder
from apps.onboarding.services import OnboardingService


@override_settings(
    STORAGES={
        "staticfiles": {
            "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage",
        },
    }
)
class BrowserHtmxGlobalUxTests(StaticLiveServerTestCase):
    email = "htmx.e2e@example.com"
    password = "HTMX-E2E-Password-123!"

    def setUp(self):
        result = OnboardingService.create_business(
            legal_name="HTMX E2E SL",
            trade_name="HTMX E2E",
            tax_identifier="B12345671",
            phone="923333333",
            email="business-htmx@example.com",
            address_line_1="Calle HTMX 1",
            postal_code="37001",
            city="Salamanca",
            province="Salamanca",
            country_code="ES",
            store_name="Tienda HTMX",
            owner_first_name="HTMX",
            owner_last_name="Owner",
            owner_email=self.email,
            owner_phone="600000002",
            owner_password=self.password,
            owner_pin="2468",
        )
        seeded = DemoBusinessSeeder.seed(business=result.business)
        self.store = result.store
        self.product = seeded.products[0]

    def _browser_page(self, playwright, width=1440):
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": width, "height": 900})
        page = context.new_page()
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.goto(f"{self.live_server_url}/users/login/")
        page.get_by_label("Correo electrónico").fill(self.email)
        page.get_by_label("Contraseña").fill(self.password)
        page.get_by_role("button", name="Iniciar sesión").click()
        page.wait_for_url(f"{self.live_server_url}/")
        return browser, context, page, errors

    def _open_sale_with_product(self, page):
        page.get_by_label("Operaciones por tienda").get_by_role(
            "link", name="Caja", exact=True
        ).click()
        main = page.locator("#main-content")
        main.get_by_role("link", name="Abrir caja").click()
        main.get_by_label("Efectivo inicial").fill("100.00")
        main.get_by_role("button", name="Abrir caja").click()
        main.get_by_role("button", name="Nueva venta").click()
        expect(main.get_by_role("heading", name=re.compile(r"Venta #"))).to_be_visible()
        main.get_by_label("Buscar producto").fill(self.product.name)
        main.locator("#product-grid").get_by_role(
            "button", name=re.compile(self.product.name)
        ).click()
        expect(main.locator("#sale-cart .cart-line")).to_be_visible()

    def test_checkout_processing_422_toast_and_csrf(self):
        with sync_playwright() as playwright:
            browser, context, page, errors = self._browser_page(playwright)
            request_headers = []
            page.on(
                "request",
                lambda request: (
                    request_headers.append(request.headers)
                    if request.method == "POST"
                    else None
                ),
            )
            try:
                self._open_sale_with_product(page)
                page.get_by_role("button", name="Actualizar cabecera").click()
                expect(page.locator("#nx-toast-region .nx-toast")).to_have_text(
                    "Venta actualizada."
                )

                trigger = page.get_by_role("link", name=re.compile(r"^COBRAR"))
                trigger.click()
                dialog = page.locator("#checkout-dialog")
                expect(dialog).to_be_visible()
                self.assertTrue(
                    page.evaluate(
                        "document.querySelector('#checkout-dialog').contains(document.activeElement)"
                    )
                )
                page.evaluate(
                    """
                    window.nxProcessingSnapshots = {};
                    document.body.addEventListener('htmx:beforeRequest', event => {
                      if (!event.detail.elt.closest('[data-nx-critical-form]')) return;
                      const dialog = document.querySelector('#checkout-dialog');
                      const button = event.detail.elt.querySelector('[type=submit]');
                      window.nxProcessingSnapshots.before = {
                        processing: dialog.dataset.nxProcessing,
                        disabled: button.disabled,
                        text: button.textContent.trim()
                      };
                      dialog.dispatchEvent(new Event('cancel', {cancelable: true}));
                      dialog.querySelector('[data-nx-modal-close]').click();
                      window.nxProcessingSnapshots.stayedOpen = dialog.open;
                    });
                    document.body.addEventListener('htmx:afterRequest', () => {
                      const dialog = document.querySelector('#checkout-dialog');
                      window.nxProcessingSnapshots.after = {
                        processing: dialog.hasAttribute('data-nx-processing'),
                        open: dialog.open
                      };
                    });
                    """
                )
                page.locator('[name="external_reference"]').fill(
                    "Referencia conservada"
                )
                page.locator('[name="payment_idempotency_key"]').evaluate(
                    "input => { input.value = 'not-a-uuid'; }"
                )
                with page.expect_response(
                    lambda response: (
                        response.request.method == "POST"
                        and "/checkout/" in response.url
                    )
                ) as response_info:
                    page.get_by_role("button", name="Confirmar cobro").click()
                self.assertEqual(response_info.value.status, 422)
                expect(dialog).to_be_visible()
                expect(dialog.locator(".errorlist").first).to_be_visible()
                expect(dialog.locator('[name="external_reference"]')).to_have_value(
                    "Referencia conservada"
                )
                snapshots = page.evaluate("window.nxProcessingSnapshots")
                self.assertEqual(snapshots["before"]["processing"], "true")
                self.assertTrue(snapshots["before"]["disabled"])
                self.assertEqual(snapshots["before"]["text"], "Procesando…")
                self.assertTrue(snapshots["stayedOpen"])
                self.assertFalse(snapshots["after"]["processing"])
                expect(
                    dialog.get_by_role("button", name="Confirmar cobro")
                ).to_be_enabled()
                self.assertFalse(page.locator("#nx-feedback").is_visible())
                self.assertTrue(
                    any(headers.get("x-csrftoken") for headers in request_headers)
                )

                page.keyboard.press("Escape")
                expect(dialog).to_be_hidden()
                expect(trigger).to_be_focused()

                payload = "<img src=x onerror=window.nxInjected=true>"
                page.evaluate(
                    "message => document.dispatchEvent(new CustomEvent('nx:toast', "
                    "{detail:{message, tone:'warning', timeout:1000}}))",
                    payload,
                )
                toast = page.locator("#nx-toast-region .nx-toast").last
                expect(toast).to_have_text(payload)
                self.assertEqual(toast.locator("img,script").count(), 0)
                self.assertIsNone(page.evaluate("window.nxInjected"))
                self.assertEqual(errors, [])
            finally:
                context.close()
                browser.close()

    def test_store_drawer_desktop_mobile_and_command_palette(self):
        with sync_playwright() as playwright:
            browser, context, page, errors = self._browser_page(playwright)
            try:
                trigger = page.locator("[data-store-trigger]")
                trigger.click()
                drawer = page.locator("#store-dialog")
                expect(drawer).to_be_visible()
                desktop = drawer.evaluate(
                    "el => ({height: el.getBoundingClientRect().height, top: el.getBoundingClientRect().top, right: innerWidth - el.getBoundingClientRect().right})"
                )
                self.assertGreater(desktop["height"], 800)
                self.assertLessEqual(desktop["right"], 1)
                page.keyboard.press("Escape")
                expect(trigger).to_be_focused()

                page.set_viewport_size({"width": 375, "height": 812})
                trigger.click()
                mobile = drawer.evaluate(
                    "el => ({width: el.getBoundingClientRect().width, bottom: innerHeight - el.getBoundingClientRect().bottom, height: el.getBoundingClientRect().height})"
                )
                self.assertGreaterEqual(mobile["width"], 373)
                self.assertLessEqual(mobile["bottom"], 1)
                self.assertLessEqual(mobile["height"], 812 * 0.91)
                page.keyboard.press("Escape")

                page.keyboard.press("Control+k")
                expect(page.locator("[data-command-dialog]")).to_be_visible()
                expect(page.locator("[data-command-input]")).to_be_focused()
                page.keyboard.press("Escape")
                self.assertEqual(errors, [])
            finally:
                context.close()
                browser.close()

    def test_expired_session_causes_full_navigation_not_partial_login(self):
        with sync_playwright() as playwright:
            browser, context, page, errors = self._browser_page(playwright)
            try:
                self._open_sale_with_product(page)
                context.clear_cookies(name=settings.SESSION_COOKIE_NAME)
                page.locator("#sale-cart .quantity-form").get_by_role(
                    "button", name="Actualizar"
                ).click()
                page.wait_for_url(re.compile(r"/users/login/\?next="))
                expect(
                    page.get_by_role("heading", name="Iniciar sesión")
                ).to_be_visible()
                self.assertEqual(page.locator("#sale-cart, #checkout-panel").count(), 0)
                self.assertEqual(errors, [])
            finally:
                context.close()
                browser.close()

    def test_network_feedback_distinguishes_mutation_from_read(self):
        with sync_playwright() as playwright:
            browser, context, page, errors = self._browser_page(playwright)
            try:
                self._open_sale_with_product(page)
                page.get_by_role("link", name=re.compile(r"^COBRAR")).click()

                def abort_checkout(route):
                    if (
                        route.request.method == "POST"
                        and "/checkout/" in route.request.url
                    ):
                        route.abort()
                    else:
                        route.continue_()

                page.route("**/sales/**", abort_checkout)
                page.get_by_role("button", name="Confirmar cobro").click()
                feedback = page.locator("#nx-feedback")
                expect(feedback).to_contain_text(
                    "No podemos confirmar el resultado de la operación."
                )
                expect(feedback).to_contain_text(
                    "Comprueba el estado antes de repetir."
                )
                expect(page.locator("#checkout-dialog")).not_to_have_attribute(
                    "data-nx-processing", "true"
                )
                close_feedback = feedback.get_by_role("button", name="Cerrar aviso")
                close_feedback.focus()
                page.keyboard.press("Enter")
                expect(feedback).to_be_hidden()
                page.unroute("**/sales/**", abort_checkout)
                page.keyboard.press("Escape")

                def abort_search(route):
                    if route.request.method == "GET" and "q=" in route.request.url:
                        route.abort()
                    else:
                        route.continue_()

                page.route("**/sales/**", abort_search)
                page.get_by_label("Buscar producto").fill("sin conexión")
                expect(feedback).to_contain_text(
                    "No se ha podido cargar la información."
                )
                expect(feedback).to_contain_text(
                    "Comprueba la conexión e inténtalo de nuevo."
                )
                self.assertEqual(errors, [])
            finally:
                context.close()
                browser.close()
