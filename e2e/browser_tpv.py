"""Real Chromium coverage for the FE-10 TPV catalogue and server cart."""

import re
from decimal import Decimal

from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.test import override_settings
from playwright.sync_api import expect, sync_playwright

from apps.cash_register.models import CashSession
from apps.catalog.models import Category
from apps.onboarding.services import OnboardingService
from apps.sales.tests.factories import (
    create_sale,
    create_sale_line,
    create_sales_customer,
    create_sales_inventory_item,
    create_sales_product,
)


@override_settings(
    STORAGES={
        "staticfiles": {
            "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"
        }
    }
)
class BrowserTPVTests(StaticLiveServerTestCase):
    email = "tpv.e2e@example.com"
    password = "E2E-TPV-123!"
    viewports = (
        {"width": 1440, "height": 900},
        {"width": 900, "height": 900},
        {"width": 375, "height": 812},
    )

    def setUp(self):
        result = OnboardingService.create_business(
            legal_name="TPV E2E SL",
            trade_name="TPV E2E",
            tax_identifier="B12345678",
            phone="923111111",
            email="business-tpv@example.com",
            address_line_1="Calle TPV 1",
            postal_code="37001",
            city="Salamanca",
            province="Salamanca",
            country_code="ES",
            store_name="Tienda Centro",
            owner_first_name="Eva",
            owner_last_name="TPV",
            owner_email=self.email,
            owner_phone="600000000",
            owner_password=self.password,
            owner_pin="1234",
        )
        self.result = result
        self.session = CashSession.objects.create(
            business=result.business,
            store=result.store,
            cash_register=result.cash_register,
            opened_by=result.owner,
        )
        self.category = Category.objects.create(
            business=result.business, name="Bebidas TPV", is_active=True
        )
        self.product = create_sales_product(
            business=result.business,
            name="Café especial",
            sku="CAFE-10",
            barcode="8410000000010",
            base_price=Decimal("2.00"),
            track_stock=True,
        )
        self.product.category = self.category
        self.product.save(update_fields=["category", "updated_at"])
        create_sales_inventory_item(
            business=result.business,
            store=result.store,
            product=self.product,
            current_stock=Decimal("50.000"),
        )
        self.customer = create_sales_customer(
            business=result.business, name="Cliente TPV"
        )
        # All ORM setup happens before Playwright enters its event-loop context.
        self.store_id = result.store.pk
        self.session_id = self.session.pk
        self.customer_id = self.customer.pk
        self.category_id = self.category.pk

    def _login(self, page):
        page.goto(f"{self.live_server_url}/users/login/")
        page.get_by_label("Correo electrónico").fill(self.email)
        page.get_by_label("Contraseña").fill(self.password)
        page.get_by_role("button", name="Iniciar sesión").click()
        page.wait_for_url(f"{self.live_server_url}/")

    def _open_sale(self, page):
        page.goto(
            f"{self.live_server_url}/cash-register/stores/{self.store_id}/sessions/{self.session_id}/"
        )
        page.locator(".cash-session-header").get_by_role(
            "button", name="Nueva venta"
        ).click()
        expect(page.get_by_role("heading", name=re.compile(r"Venta #"))).to_be_visible()
        expect(page.get_by_role("button", name="Iniciar venta")).to_have_count(0)
        expect(page).to_have_url(re.compile(r"/sales/stores/\d+/sales/\d+/$"))
        page.wait_for_load_state("load")

    def _save_header(self, page, change):
        page.locator("#workspace-header").evaluate(
            "el => el.dataset.beforeSave = 'true'"
        )
        with page.expect_response(
            lambda r: "/header/" in r.url and r.request.method == "POST"
        ) as response:
            change()
        self.assertEqual(response.value.status, 200)
        expect(page.locator("#workspace-header[data-before-save]")).to_have_count(0)
        expect(page.locator("#workspace-header.htmx-settling")).to_have_count(0)

    def test_header_autosave_drafts_quick_customer_and_responsive(self):
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            try:
                for viewport in self.viewports:
                    with self.subTest(viewport=viewport):
                        context = browser.new_context(viewport=viewport)
                        page = context.new_page()
                        self._login(page)
                        self._open_sale(page)
                        header = page.locator("#workspace-header")
                        expect(header.locator("option:checked")).to_have_text(
                            "Sin cliente"
                        )
                        expect(
                            header.get_by_role("radio", name="Ticket", exact=True)
                        ).to_be_checked()
                        expect(
                            header.get_by_text("Mostrador", exact=True)
                        ).to_have_count(0)
                        expect(
                            header.get_by_role("radio", name="Cliente", exact=True)
                        ).to_have_count(0)
                        expect(
                            header.get_by_role("button", name="Guardar", exact=True)
                        ).to_have_count(0)
                        sale_url = page.url
                        page.locator("#product-grid").evaluate(
                            "el => el.dataset.headerTest = 'unchanged'"
                        )
                        page.locator("#sale-cart").evaluate(
                            "el => el.dataset.headerTest = 'unchanged'"
                        )
                        page.locator("#id_customer").focus()
                        self._save_header(
                            page,
                            lambda: page.locator("#id_customer").select_option(
                                str(self.customer_id)
                            ),
                        )
                        expect(
                            header.get_by_role("radio", name="Ticket", exact=True)
                        ).to_be_checked()
                        expect(
                            page.locator('#product-grid[data-header-test="unchanged"]')
                        ).to_have_count(1)
                        expect(
                            page.locator('#sale-cart[data-header-test="unchanged"]')
                        ).to_have_count(1)
                        expect(page.locator("#id_customer")).to_be_focused()
                        page.reload()
                        expect(page.locator("#id_customer")).to_have_value(
                            str(self.customer_id)
                        )
                        expect(
                            header.get_by_role("radio", name="Ticket", exact=True)
                        ).to_be_checked()
                        self._save_header(
                            page, lambda: page.locator("#id_customer").select_option("")
                        )
                        self._save_header(
                            page,
                            lambda: header.get_by_role(
                                "radio", name="Factura", exact=True
                            ).check(),
                        )
                        expect(header.locator(".header-help")).to_be_visible()
                        expect(header.locator('[role="alert"]')).to_have_count(0)
                        expect(
                            header.get_by_role("radio", name="Factura", exact=True)
                        ).to_be_focused()
                        page.reload()
                        expect(
                            header.get_by_role("radio", name="Factura", exact=True)
                        ).to_be_checked()
                        expect(page.locator("#id_customer")).to_have_value("")
                        page.get_by_role(
                            "button", name=re.compile("Café especial")
                        ).click()
                        for document in ("Factura", "Ticket"):
                            if document == "Ticket":
                                self._save_header(
                                    page,
                                    lambda: header.get_by_role(
                                        "radio", name="Ticket", exact=True
                                    ).check(),
                                )
                            header.get_by_role(
                                "button", name="+ Nuevo cliente", exact=True
                            ).click()
                            panel = page.locator("#quick-customer-panel")
                            expect(panel.locator('input[name="name"]')).to_be_visible()
                            name = f"Cliente {document} {viewport['width']}"
                            panel.locator('input[name="name"]').fill(name)
                            with page.expect_response(
                                lambda r: (
                                    "/quick-create/" in r.url
                                    and r.request.method == "POST"
                                )
                            ):
                                panel.get_by_role(
                                    "button", name="Crear y seleccionar"
                                ).click()
                            expect(
                                page.locator("#quick-customer-dialog")
                            ).not_to_be_visible()
                            expect(header.locator("option:checked")).to_have_text(name)
                            expect(
                                header.get_by_role("radio", name=document, exact=True)
                            ).to_be_checked()
                            self.assertEqual(page.url, sale_url)
                        self.assertTrue(
                            page.evaluate(
                                "document.documentElement.scrollWidth <= document.documentElement.clientWidth"
                            )
                        )
                        context.close()
            finally:
                browser.close()

    def test_reopening_quick_customer_waits_for_new_form_with_slow_get(self):
        """A second GET must never leave the previous form editable underneath it."""
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            try:
                for viewport in self.viewports:
                    with self.subTest(viewport=viewport):
                        context = browser.new_context(viewport=viewport)
                        page = context.new_page()
                        self._login(page)
                        self._open_sale(page)
                        sale_url = page.url
                        held = {}
                        requests = []

                        def hold_second_get(route):
                            requests.append(route.request.method)
                            if (
                                route.request.method == "GET"
                                and requests.count("GET") == 2
                            ):
                                held["route"] = route
                                held["response"] = route.fetch()
                                page.evaluate("window.quickCustomerGetHeld = true")
                            else:
                                route.continue_()

                        page.route("**/quick-create/", hold_second_get)
                        panel = page.locator("#quick-customer-panel")
                        for index, document in enumerate(
                            ("Factura", "Ticket", "Factura")
                        ):
                            self._save_header(
                                page,
                                lambda: page.get_by_role(
                                    "radio", name=document, exact=True
                                ).check(),
                            )
                            page.get_by_role(
                                "button", name="+ Nuevo cliente", exact=True
                            ).click()
                            if index == 1:
                                page.wait_for_function(
                                    "window.quickCustomerGetHeld === true"
                                )
                                expect(panel.locator("form")).to_have_count(0)
                                expect(panel.get_by_role("status")).to_have_text(
                                    "Cargando formulario de cliente…"
                                )
                                held["route"].fulfill(response=held["response"])
                            expect(panel.locator('input[name="name"]')).to_be_visible()
                            expect(panel.locator('input[name="name"]')).to_have_value(
                                ""
                            )
                            name = f"Cliente lento {viewport['width']} {index}"
                            panel.locator('input[name="name"]').fill(name)
                            with page.expect_response(
                                lambda r: (
                                    "/quick-create/" in r.url
                                    and r.request.method == "POST"
                                )
                            ) as response:
                                panel.get_by_role(
                                    "button", name="Crear y seleccionar"
                                ).click()
                            self.assertEqual(response.value.status, 200)
                            expect(
                                page.locator("#quick-customer-dialog")
                            ).not_to_be_visible()
                            expect(
                                page.locator("#workspace-header option:checked")
                            ).to_have_text(name)
                            expect(
                                page.get_by_role("radio", name=document, exact=True)
                            ).to_be_checked()
                            expect(
                                page.locator("#workspace-header.htmx-settling")
                            ).to_have_count(0)
                            self.assertEqual(page.url, sale_url)
                        self.assertEqual(requests.count("POST"), 3)
                        page.reload()
                        expect(
                            page.locator("#workspace-header option:checked")
                        ).to_have_text(name)
                        expect(
                            page.get_by_role("radio", name="Factura", exact=True)
                        ).to_be_checked()
                        context.close()
            finally:
                browser.close()

    def test_rapid_changes_keep_last_server_state_after_older_response(self):
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page()
            try:
                self._login(page)
                self._open_sale(page)
                requests = []

                def hold_first_response(route):
                    requests.append(route.request.post_data)
                    response = route.fetch()
                    if len(requests) == 1:
                        # The server saved Ticket, but its response is still held.
                        # Queue several choices while that first request is in flight.
                        page.evaluate(
                            """customer => {
                            const select = document.querySelector('#id_customer');
                            select.value = '';
                            select.dispatchEvent(new Event('change', {bubbles: true}));
                            select.value = customer;
                            select.dispatchEvent(new Event('change', {bubbles: true}));
                            const invoice = document.querySelector('#header-document-invoice');
                            invoice.checked = true;
                            invoice.dispatchEvent(new Event('change', {bubbles: true}));
                        }""",
                            str(self.customer_id),
                        )
                    route.fulfill(response=response)

                page.route("**/header/", hold_first_response)
                self._save_header(
                    page,
                    lambda: page.locator("#id_customer").select_option(
                        str(self.customer_id)
                    ),
                )
                expect(
                    page.get_by_role("radio", name="Factura", exact=True)
                ).to_be_checked()
                self.assertEqual(len(requests), 2)
                self.assertIn("document_type_requested=invoice", requests[-1])
                self.assertIn(f"customer={self.customer_id}", requests[-1])
                page.reload()
                expect(page.locator("#id_customer")).to_have_value(
                    str(self.customer_id)
                )
                expect(
                    page.get_by_role("radio", name="Factura", exact=True)
                ).to_be_checked()
            finally:
                browser.close()

    def test_rejected_header_change_restores_server_values_and_shows_error(self):
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page()
            try:
                self._login(page)
                self._open_sale(page)
                page.locator("#workspace-header").evaluate(
                    "el => el.dataset.beforeSave = 'true'"
                )
                with page.expect_response(lambda r: "/header/" in r.url) as response:
                    page.evaluate("""() => {
                        const select = document.querySelector('#id_customer');
                        select.add(new Option('Cliente inexistente', '999999999'));
                        select.value = '999999999';
                        select.dispatchEvent(new Event('change', {bubbles: true}));
                    }""")
                self.assertEqual(response.value.status, 422)
                expect(
                    page.locator("#workspace-header[data-before-save]")
                ).to_have_count(0)
                expect(page.locator("#id_customer")).to_have_value("")
                expect(
                    page.get_by_role("radio", name="Ticket", exact=True)
                ).to_be_checked()
                expect(page.locator('#workspace-header [role="alert"]')).to_be_visible()
                expect(page.locator("#nx-toast-region .nx-toast--error")).to_have_text(
                    "No se ha podido guardar la cabecera."
                )
                page.reload()
                expect(page.locator("#id_customer")).to_have_value("")
            finally:
                browser.close()

    def test_header_submission_without_javascript(self):
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            context = browser.new_context(java_script_enabled=False)
            page = context.new_page()
            try:
                self._login(page)
                self._open_sale(page)
                header = page.locator("#workspace-header")
                expect(
                    header.get_by_role("button", name="Guardar", exact=True)
                ).to_be_visible()
                header.get_by_role("radio", name="Factura", exact=True).check()
                header.get_by_role("button", name="Guardar", exact=True).click()
                expect(
                    header.get_by_role("radio", name="Factura", exact=True)
                ).to_be_checked()
                page.reload()
                expect(
                    header.get_by_role("radio", name="Factura", exact=True)
                ).to_be_checked()
            finally:
                browser.close()

    def _open_ticket_if_needed(self, page, width):
        if width >= 1200:
            expect(page.locator("#sale-cart")).to_be_visible()
            return
        trigger = page.locator('[data-nx-drawer-trigger="sale-cart"]')
        expect(trigger).to_be_visible()
        trigger.click()
        expect(page.locator("#sale-cart")).to_have_attribute("open", "")
        expect(page.locator("#sale-cart [data-nx-drawer-close]")).to_be_focused()

    def _save_quantity(self, page, action, expected, status=200):
        requests = []
        navigations = []

        def record_request(request):
            if "/quantity/" in request.url and request.method == "POST":
                requests.append(request)

        def record_navigation(frame):
            if frame == page.main_frame:
                navigations.append(frame.url)

        page.on("request", record_request)
        page.on("framenavigated", record_navigation)
        page.locator("#sale-cart-content").evaluate(
            "el => el.dataset.beforeSave = 'true'"
        )
        try:
            with page.expect_response(
                lambda r: (
                    "/quantity/" in r.url
                    and r.request.method == "POST"
                    and r.request.headers.get("hx-request") == "true"
                )
            ) as response:
                action()
            self.assertEqual(response.value.status, status)
            expect(page.locator("#sale-cart-content[data-before-save]")).to_have_count(
                0
            )
            expect(page.locator('.quantity-form [name="quantity"]')).to_have_value(
                expected
            )
            expect(page.locator("#sale-cart-content.htmx-settling")).to_have_count(0)
            self.assertEqual(len(requests), 1)
            self.assertEqual(requests[0].headers.get("hx-request"), "true")
            self.assertEqual(navigations, [])
        finally:
            page.remove_listener("request", record_request)
            page.remove_listener("framenavigated", record_navigation)

    def test_quantity_autosave_fractions_bounds_and_reload(self):
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1440, "height": 900})
            try:
                self._login(page)
                self._open_sale(page)
                page.get_by_role("button", name=re.compile("Café especial")).click()
                quantity = page.locator('.quantity-form [name="quantity"]')
                expect(quantity).to_have_value("1")
                expect(page.get_by_role("button", name="Actualizar")).to_have_count(0)
                self._save_quantity(
                    page,
                    lambda: page.get_by_label("Aumentar Café especial").click(),
                    "2",
                )
                page.reload()
                expect(quantity).to_have_value("2")
                self._save_quantity(
                    page,
                    lambda: page.get_by_label("Reducir Café especial").click(),
                    "1",
                )
                page.reload()
                expect(quantity).to_have_value("1")
                for value in ("1.5", "0.125", "0.001"):
                    quantity.fill(value)
                    self._save_quantity(page, lambda: quantity.press("Enter"), value)
                    page.reload()
                    expect(quantity).to_have_value(value)
                quantity.fill("1.5")
                self._save_quantity(page, lambda: quantity.blur(), "1.5")
                self._save_quantity(
                    page,
                    lambda: page.get_by_label("Aumentar Café especial").click(),
                    "2.5",
                )
                self._save_quantity(
                    page,
                    lambda: page.get_by_label("Reducir Café especial").click(),
                    "1.5",
                )
                self._save_quantity(
                    page,
                    lambda: page.get_by_label("Reducir Café especial").click(),
                    "0.5",
                )
                page.get_by_label("Reducir Café especial").click()
                expect(quantity).to_have_value("0.5")
                page.reload()
                expect(quantity).to_have_value("0.5")
                for value in ("0", "-1", "1.2345", ""):
                    quantity.fill(value)
                    self._save_quantity(
                        page, lambda: quantity.press("Enter"), "0.5", status=422
                    )
                    expect(
                        page.locator("#sale-cart-content [role=alert]")
                    ).to_be_visible()
            finally:
                browser.close()

    def test_rapid_quantity_clicks_survive_older_response(self):
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1440, "height": 900})
            try:
                self._login(page)
                self._open_sale(page)
                page.get_by_role("button", name=re.compile("Café especial")).click()
                expect(page.locator('.quantity-form [name="quantity"]')).to_have_value(
                    "1"
                )
                requests = []
                held = {}

                def hold_first_response(route):
                    requests.append(route.request.post_data)
                    if len(requests) == 1:
                        held["route"] = route
                        held["response"] = route.fetch()
                        page.evaluate("window.quantityResponseHeld = true")
                    else:
                        route.continue_()

                page.route("**/quantity/", hold_first_response)
                page.get_by_label("Aumentar Café especial").click()
                page.wait_for_function("window.quantityResponseHeld === true")
                # A single browser task ensures all clicks precede the held response.
                page.evaluate("""() => {
                    const plus = document.querySelector('[data-quantity-step="1"]');
                    plus.click(); plus.click(); plus.click();
                }""")
                expect(page.locator('.quantity-form [name="quantity"]')).to_have_value(
                    "5"
                )
                held["route"].fulfill(response=held["response"])
                expect(page.locator(".quantity-form.htmx-request")).to_have_count(0)
                expect(page.locator('.quantity-form [name="quantity"]')).to_have_value(
                    "5"
                )
                self.assertIn("quantity=2", requests[0])
                self.assertIn("quantity=5", requests[-1])
                self.assertEqual(len(requests), 4)
                page.reload()
                expect(page.locator('.quantity-form [name="quantity"]')).to_have_value(
                    "5"
                )
            finally:
                browser.close()

    def test_rapid_quantity_changes_on_two_lines_keep_both_intents(self):
        create_sales_product(
            business=self.result.business,
            name="Agua TPV",
            base_price=Decimal("1.00"),
            track_stock=False,
        )
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1440, "height": 900})
            try:
                self._login(page)
                self._open_sale(page)
                for name in ("Café especial", "Agua TPV"):
                    page.get_by_role("button", name=re.compile(name)).click()
                    expect(
                        page.locator("#sale-cart .cart-line", has_text=name)
                    ).to_be_visible()
                held = {}
                requests = []

                def hold_first_response(route):
                    requests.append(route.request.post_data)
                    if len(requests) == 1:
                        held["route"] = route
                        held["response"] = route.fetch()
                        page.evaluate("window.quantityResponseHeld = true")
                    else:
                        route.continue_()

                page.route("**/quantity/", hold_first_response)
                page.get_by_label("Aumentar Café especial").click()
                page.wait_for_function("window.quantityResponseHeld === true")
                page.evaluate("""() => {
                    document.querySelector('[aria-label="Aumentar Agua TPV"]').click();
                    document.querySelector('[aria-label="Aumentar Café especial"]').click();
                }""")
                held["route"].fulfill(response=held["response"])
                expect(page.locator(".quantity-form.htmx-request")).to_have_count(0)
                self.assertEqual(len(requests), 3)
                page.reload()
                expect(
                    page.locator(".cart-line", has_text="Café especial").get_by_label(
                        "Cantidad"
                    )
                ).to_have_value("3")
                expect(
                    page.locator(".cart-line", has_text="Agua TPV").get_by_label(
                        "Cantidad"
                    )
                ).to_have_value("2")
            finally:
                browser.close()

    def test_discount_editor_totals_errors_and_responsive(self):
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            try:
                for viewport in self.viewports:
                    with self.subTest(viewport=viewport):
                        context = browser.new_context(viewport=viewport)
                        page = context.new_page()
                        self._login(page)
                        self._open_sale(page)
                        page.get_by_role(
                            "button", name=re.compile("Café especial")
                        ).click()
                        self._open_ticket_if_needed(page, viewport["width"])
                        cart = page.locator("#sale-cart")
                        expect(
                            cart.locator(".cart-totals dt", has_text="Descuento")
                        ).to_have_count(0)
                        cart.get_by_role("link", name="Descuento", exact=True).click()
                        editor = page.locator("#line-editor-dialog")
                        discount = editor.get_by_label("Descuento (€)")
                        expect(discount).to_be_focused()
                        discount.fill("0.40")
                        editor.get_by_role("button", name="Guardar cambios").click()
                        expect(editor).not_to_be_visible()
                        expect(cart.get_by_text("Descuento: −0,40 €")).to_be_visible()
                        expect(cart.locator(".grand-total dd")).to_have_text("1,94 €")
                        expect(
                            cart.locator(".cart-totals dt", has_text="Descuento")
                        ).to_be_visible()
                        cart.get_by_role("link", name="Editar descuento").click()
                        discount.fill("0.41")
                        with page.expect_response(
                            lambda r: "/edit/" in r.url and r.request.method == "POST"
                        ) as response:
                            editor.get_by_role("button", name="Guardar cambios").click()
                        self.assertEqual(response.value.status, 422)
                        expect(editor).to_be_visible()
                        expect(
                            editor.locator("#id_discount_amount-errors")
                        ).to_be_visible()
                        expect(cart.get_by_text("Descuento: −0,40 €")).to_be_visible()
                        discount.fill("0")
                        editor.get_by_role("button", name="Guardar cambios").click()
                        expect(editor).not_to_be_visible()
                        expect(
                            cart.get_by_text("Descuento:", exact=False)
                        ).to_have_count(0)
                        expect(
                            cart.locator(".cart-totals dt", has_text="Descuento")
                        ).to_have_count(0)
                        expect(cart.locator(".grand-total dd")).to_have_text("2,42 €")
                        self.assertTrue(
                            page.evaluate(
                                "document.documentElement.scrollWidth <= document.documentElement.clientWidth"
                            )
                        )
                        self.assertTrue(
                            cart.evaluate("el => el.scrollWidth <= el.clientWidth")
                        )
                        context.close()
            finally:
                browser.close()

    def test_quantity_without_javascript_uses_normal_post(self):
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            context = browser.new_context(
                java_script_enabled=False, viewport={"width": 1440, "height": 900}
            )
            page = context.new_page()
            try:
                self._login(page)
                self._open_sale(page)
                page.get_by_role("button", name=re.compile("Café especial")).click()
                quantity = page.locator('.quantity-form [name="quantity"]')
                quantity.fill("0.125")
                page.get_by_role("button", name="Actualizar").click()
                expect(quantity).to_have_value("0.125")
                page.reload()
                expect(quantity).to_have_value("0.125")
            finally:
                browser.close()

    def test_catalogue_ticket_and_responsive_surfaces(self):
        # IDs and all other ORM-derived data are materialised before sync_playwright.
        scenarios = tuple(dict(viewport) for viewport in self.viewports)
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            try:
                for viewport in scenarios:
                    with self.subTest(viewport=viewport):
                        context = browser.new_context(viewport=viewport)
                        page = context.new_page()
                        errors = []
                        page.on("pageerror", lambda error: errors.append(str(error)))
                        self._login(page)
                        self._open_sale(page)

                        heading = page.get_by_role(
                            "heading", name=re.compile(r"Venta #\d+ · Tienda Centro")
                        )
                        expect(heading).to_be_visible()
                        if viewport["width"] >= 1200:
                            expect(page.locator(".app-sidebar")).to_have_css(
                                "width", "76px"
                            )
                            expect(page.locator(".erp-workspace")).to_have_css(
                                "margin-left", "76px"
                            )

                        search = page.locator("#product-search")
                        if viewport["width"] >= 768:
                            expect(search).to_be_focused()
                        category_chip = page.locator("#category-chips").get_by_role(
                            "button", name="Bebidas TPV", exact=True
                        )
                        category_chip.click()
                        expect(category_chip).to_have_attribute("aria-pressed", "true")

                        with page.expect_request(
                            lambda request: (
                                "q=CAFE-10" in request.url
                                and f"category={self.category_id}" in request.url
                            )
                        ):
                            search.fill("CAFE-10")
                        product_button = page.get_by_role(
                            "button", name=re.compile("Café especial")
                        )
                        expect(product_button).to_be_visible()
                        expect(category_chip).to_have_attribute("aria-pressed", "true")
                        expect(product_button).to_be_visible()
                        product_button.click()

                        self._open_ticket_if_needed(page, viewport["width"])
                        cart = page.locator("#sale-cart")
                        expect(cart.get_by_text("Café especial")).to_be_visible()
                        quantity = cart.get_by_label("Cantidad")
                        expect(quantity).to_have_value("1")
                        with page.expect_response(
                            lambda response: (
                                "/quantity/" in response.url
                                and response.request.method == "POST"
                            )
                        ):
                            cart.get_by_label("Aumentar Café especial").click()
                        if viewport["width"] < 1200:
                            expect(cart).to_have_attribute("open", "")
                            expect(cart.get_by_label("Cantidad")).to_be_visible()
                        expect(cart.get_by_label("Cantidad")).to_have_value("2")
                        # Expose the interval where swapped forms are visible but
                        # HTMX has not yet run its deferred processing task.
                        page.evaluate("htmx.config.defaultSettleDelay = 1000")
                        with page.expect_response(
                            lambda response: (
                                "/quantity/" in response.url
                                and response.request.method == "POST"
                            )
                        ):
                            cart.get_by_label("Reducir Café especial").click()
                        if viewport["width"] < 1200:
                            expect(cart).to_have_attribute("open", "")
                            expect(cart.get_by_label("Cantidad")).to_be_visible()
                        expect(cart.get_by_label("Cantidad")).to_have_value("1")
                        cart.evaluate("el => window.quantityDrawer = el")
                        cart.get_by_label("Cantidad").fill("1.500")
                        self._save_quantity(
                            page,
                            lambda: cart.get_by_label("Cantidad").press("Enter"),
                            "1.5",
                        )
                        self.assertTrue(
                            cart.evaluate("el => el === window.quantityDrawer")
                        )
                        page.evaluate("htmx.config.defaultSettleDelay = 20")
                        if viewport["width"] < 1200:
                            expect(cart).to_have_attribute("open", "")
                            expect(cart.get_by_label("Cantidad")).to_be_visible()
                        expect(cart.get_by_label("Cantidad")).to_have_value("1.5")

                        cart.get_by_role("link", name="Editar precio").click()
                        editor = page.locator("#line-editor-dialog")
                        expect(editor).to_have_attribute("open", "")
                        page.get_by_role("button", name="Guardar cambios").click()
                        expect(editor).not_to_have_attribute("open", "")
                        expect(page.locator("#line-editor-panel")).to_have_count(1)
                        cart.get_by_role("link", name="Editar precio").click()
                        expect(editor).to_have_attribute("open", "")
                        page.get_by_role("button", name="Cerrar editor").click()

                        cart.get_by_role("button", name="Eliminar").click()
                        expect(cart.get_by_text("Café especial")).to_have_count(0)
                        if viewport["width"] < 1200:
                            expect(cart).to_have_attribute("open", "")
                            cart.get_by_role("button", name="Cerrar ticket").click()
                            expect(cart).not_to_have_attribute("open", "")
                        page.get_by_role(
                            "button", name=re.compile("Café especial")
                        ).click()
                        if viewport["width"] < 1200:
                            page.locator('[data-nx-drawer-trigger="sale-cart"]').click()
                        expect(cart.get_by_text("Café especial")).to_be_visible()
                        if viewport["width"] < 1200:
                            cart.get_by_role("button", name="Cerrar ticket").click()

                        self._save_header(
                            page,
                            lambda: page.get_by_role(
                                "radio", name="Factura", exact=True
                            ).check(),
                        )
                        expect(page.locator(".header-help")).to_be_visible()
                        self._save_header(
                            page,
                            lambda: page.locator("#id_customer").select_option(
                                str(self.customer_id)
                            ),
                        )
                        expect(page.locator("#id_customer")).to_have_value(
                            str(self.customer_id)
                        )
                        self._save_header(
                            page,
                            lambda: page.get_by_role(
                                "radio", name="Ticket", exact=True
                            ).check(),
                        )
                        expect(page.locator("#id_customer")).to_have_value(
                            str(self.customer_id)
                        )
                        if viewport["width"] < 1200:
                            page.locator('[data-nx-drawer-trigger="sale-cart"]').click()
                        expect(
                            cart.get_by_role("link", name=re.compile(r"^COBRAR"))
                        ).to_be_visible()

                        if viewport["width"] < 1200:
                            trigger = page.locator(
                                '[data-nx-drawer-trigger="sale-cart"]'
                            )
                            expect(cart).to_have_attribute("open", "")
                            page.keyboard.press("Escape")
                            expect(cart).not_to_have_attribute("open", "")
                            expect(trigger).to_be_focused()
                        assert page.evaluate(
                            "document.documentElement.scrollWidth <= document.documentElement.clientWidth"
                        )
                        assert errors == []
                        context.close()
            finally:
                browser.close()

    def test_long_ticket_fixed_footer_scroll_and_mutations(self):
        # Twenty real products/lines trigger overflow without artificial CSS heights.
        products = [
            create_sales_product(
                business=self.result.business,
                name=f"Producto largo {index:02d}",
                base_price=Decimal("10.00"),
                track_stock=False,
            )
            for index in range(20)
        ]
        scenarios = []
        for viewport in (*self.viewports, {"width": 375, "height": 568}):
            sale = create_sale(
                business=self.result.business,
                store=self.result.store,
                opened_by=self.result.owner,
                cash_register=self.result.cash_register,
                cash_session=self.session,
            )
            for product in products:
                create_sale_line(
                    business=self.result.business, sale=sale, product=product
                )
            scenarios.append((viewport, sale.pk))

        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            try:
                for viewport, sale_id in scenarios:
                    with self.subTest(viewport=viewport):
                        context = browser.new_context(viewport=viewport)
                        page = context.new_page()
                        errors = []
                        page.on("pageerror", lambda error: errors.append(str(error)))
                        self._login(page)
                        page.goto(
                            f"{self.live_server_url}/sales/stores/{self.store_id}/sales/{sale_id}/"
                        )
                        page.wait_for_load_state("load")
                        self._open_ticket_if_needed(page, viewport["width"])
                        cart = page.locator("#sale-cart")
                        region = cart.locator("[data-cart-scroll-region]")
                        heading = cart.locator(".cart-heading")
                        footer = cart.locator("footer")
                        checkout = footer.get_by_role(
                            "link", name=re.compile("^COBRAR")
                        )
                        expect(cart.locator(".cart-line")).to_have_count(20)
                        self.assertTrue(
                            region.evaluate("el => el.scrollHeight > el.clientHeight")
                        )
                        self.assertTrue(
                            cart.evaluate(
                                "el => el.scrollHeight <= el.clientHeight + 1"
                            ),
                            cart.evaluate(
                                "el => [el, el.firstElementChild].map(e => ({h:e.clientHeight, sh:e.scrollHeight, css:getComputedStyle(e).height, p:getComputedStyle(e).padding, b:e.getBoundingClientRect().toJSON()}))"
                            ),
                        )
                        self.assertEqual(
                            cart.evaluate("el => getComputedStyle(el).overflowY"),
                            "hidden",
                        )
                        expect(heading).to_be_in_viewport(ratio=1)
                        expect(checkout).to_be_in_viewport(ratio=1)
                        expect(
                            footer.get_by_role("link", name="Cancelar venta")
                        ).to_be_in_viewport(ratio=1)
                        region.focus()
                        before_keyboard = region.evaluate("el => el.scrollTop")
                        region.press("PageDown")
                        page.wait_for_function(
                            "document.querySelector('[data-cart-scroll-region]').scrollTop > 0"
                        )
                        self.assertGreater(
                            region.evaluate("el => el.scrollTop"), before_keyboard
                        )
                        expect(checkout).to_be_in_viewport(ratio=1)
                        initial_heading = heading.bounding_box()
                        initial_footer = footer.bounding_box()
                        page_y = page.evaluate("window.scrollY")
                        region.evaluate("el => el.scrollTop = el.scrollHeight")
                        expect(cart.locator(".cart-line").last).to_be_in_viewport(
                            ratio=1
                        )
                        for locator, initial in (
                            (heading, initial_heading),
                            (footer, initial_footer),
                        ):
                            self.assertAlmostEqual(
                                locator.bounding_box()["y"], initial["y"], delta=1
                            )
                        expect(checkout).to_be_in_viewport(ratio=1)
                        self.assertEqual(page.evaluate("window.scrollY"), page_y)

                        line = cart.locator(".cart-line", has_text="Producto largo 12")
                        line.locator(
                            "[data-quantity-step='1']"
                        ).scroll_into_view_if_needed()
                        before = region.evaluate("el => el.scrollTop")
                        self._save_long_ticket_quantity(page, line, "2", step=True)
                        self.assertAlmostEqual(
                            region.evaluate("el => el.scrollTop"), before, delta=4
                        )
                        if viewport["width"] < 1200:
                            expect(cart).to_have_attribute("open", "")
                        line.get_by_label("Cantidad").fill("2.5")
                        self._save_long_ticket_quantity(page, line, "2.5")
                        self.assertAlmostEqual(
                            region.evaluate("el => el.scrollTop"), before, delta=4
                        )
                        expect(checkout).to_be_in_viewport(ratio=1)

                        line.get_by_role("link", name="Descuento", exact=True).click()
                        editor = page.locator("#line-editor-dialog")
                        expect(editor).to_have_attribute("open", "")
                        discount = editor.get_by_label("Descuento (€)")
                        expect(discount).to_be_focused()
                        discount.fill("1.00")
                        before = region.evaluate("el => el.scrollTop")
                        editor.get_by_role("button", name="Guardar cambios").click()
                        expect(editor).not_to_be_visible()
                        expect(line.get_by_text("Descuento: −1,00 €")).to_be_visible()
                        self.assertAlmostEqual(
                            region.evaluate("el => el.scrollTop"), before, delta=4
                        )
                        expect(
                            footer.locator("dt", has_text="Descuento")
                        ).to_be_in_viewport(ratio=1)
                        expect(checkout).to_be_in_viewport(ratio=1)
                        line.get_by_role("link", name="Editar precio").click()
                        expect(editor).to_have_attribute("open", "")
                        expect(
                            editor.get_by_label("Precio unitario sin IVA")
                        ).to_be_visible()
                        editor.get_by_role("button", name="Cerrar editor").click()
                        expect(
                            line.get_by_role("link", name="Editar precio")
                        ).to_be_focused()
                        expect(
                            page.locator("#sale-cart-content.htmx-settling")
                        ).to_have_count(0)
                        expect(
                            page.locator(".quantity-form.htmx-request")
                        ).to_have_count(0)

                        # A 422 from an intermediate line must reveal the top alert,
                        # while retaining the drawer, footer and authoritative value.
                        line.get_by_label("Cantidad").fill("0")
                        self._save_long_ticket_quantity(page, line, "2.5", status=422)
                        expect(region.locator("[role=alert]")).to_be_in_viewport(
                            ratio=1
                        )
                        expect(checkout).to_be_in_viewport(ratio=1)
                        checkout.click()
                        checkout_dialog = page.locator("#checkout-dialog")
                        expect(checkout_dialog).to_have_attribute("open", "")
                        expect(
                            checkout_dialog.locator("#checkout-title")
                        ).to_be_visible()
                        page.keyboard.press("Escape")
                        expect(checkout_dialog).not_to_be_visible()

                        # Add/delete also replace the same shell. Exercise them at
                        # desktop's current scroll position; mobile drawer stays modal.
                        if viewport["width"] >= 1200:
                            line.get_by_label("Cantidad").scroll_into_view_if_needed()
                            before = region.evaluate("el => el.scrollTop")
                            line.get_by_role("button", name="Eliminar").click()
                            expect(cart.locator(".cart-line")).to_have_count(19)
                            self.assertAlmostEqual(
                                region.evaluate("el => el.scrollTop"), before, delta=4
                            )
                            page.get_by_role(
                                "button", name=re.compile("Café especial")
                            ).click()
                            expect(cart.locator(".cart-line")).to_have_count(20)
                            self.assertAlmostEqual(
                                region.evaluate("el => el.scrollTop"), before, delta=4
                            )
                            # The catalog page can scroll independently; the sticky
                            # ticket remains under the global topbar, CTA in viewport.
                            page.evaluate(
                                "window.scrollTo(0, document.body.scrollHeight)"
                            )
                            expect(checkout).to_be_in_viewport(ratio=1)
                            expect(heading).to_be_in_viewport(ratio=1)
                            self.assertGreaterEqual(
                                heading.bounding_box()["y"],
                                page.locator(".topbar").bounding_box()["height"],
                            )
                        else:
                            trigger = page.locator(
                                '[data-nx-drawer-trigger="sale-cart"]'
                            )
                            cart.get_by_role("button", name="Cerrar ticket").click()
                            expect(cart).not_to_be_visible()
                            expect(trigger).to_be_focused()
                            trigger.click()
                            expect(cart).to_have_attribute("open", "")
                            expect(checkout).to_be_in_viewport(ratio=1)
                            page.keyboard.press("Escape")
                            expect(cart).not_to_be_visible()
                            expect(trigger).to_be_focused()
                        self.assertTrue(
                            page.evaluate(
                                "document.documentElement.scrollWidth <= document.documentElement.clientWidth"
                            )
                        )
                        self.assertEqual(errors, [])
                        context.close()
            finally:
                browser.close()

    def _save_long_ticket_quantity(
        self, page, line, expected, *, step=False, status=200
    ):
        requests = []
        navigations = []

        def record(request):
            if "/quantity/" in request.url and request.method == "POST":
                requests.append(request)

        def navigation(frame):
            if frame == page.main_frame:
                navigations.append(frame.url)

        page.on("request", record)
        page.on("framenavigated", navigation)
        page.locator("#sale-cart-content").evaluate(
            "el => el.dataset.beforeSave = 'true'"
        )
        try:
            with page.expect_response(
                lambda r: "/quantity/" in r.url and r.request.method == "POST"
            ) as response:
                if step:
                    line.locator("[data-quantity-step='1']").click()
                else:
                    line.get_by_label("Cantidad").press("Enter")
            self.assertEqual(response.value.status, status)
            expect(page.locator("#sale-cart-content[data-before-save]")).to_have_count(
                0
            )
            expect(line.get_by_label("Cantidad")).to_have_value(expected)
            expect(page.locator("#sale-cart-content.htmx-settling")).to_have_count(0)
            self.assertEqual(len(requests), 1, [r.post_data for r in requests])
            self.assertEqual(requests[0].headers.get("hx-request"), "true")
            self.assertEqual(navigations, [])
        finally:
            page.remove_listener("request", record)
            page.remove_listener("framenavigated", navigation)
