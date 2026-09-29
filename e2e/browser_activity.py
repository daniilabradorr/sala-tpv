"""Real Chromium coverage for the FE-20 Activity surface."""

import re

from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.test import override_settings
from playwright.sync_api import expect, sync_playwright

from apps.audit.constants import AuditEventType, AuditModule
from apps.audit.services import log_event
from apps.onboarding.services import OnboardingService
from apps.purchases.models import Purchase, Supplier
from apps.sales.models import SaleStatusChoices
from apps.sales.tests.factories import create_sale
from apps.stores.models import Store
from apps.users.models import CustomUser, RoleChoices, UserStoreAccess


@override_settings(
    STORAGES={
        "staticfiles": {
            "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"
        }
    }
)
class BrowserActivityTests(StaticLiveServerTestCase):
    EMAIL = "activity.e2e@example.com"
    PASSWORD = "E2E-Activity-Password-123!"
    MANAGER_EMAIL = "activity-manager.e2e@example.com"
    CASHIER_EMAIL = "activity-cashier.e2e@example.com"

    def setUp(self):
        result = OnboardingService.create_business(
            legal_name="Activity E2E SL",
            trade_name="Activity E2E",
            tax_identifier="B10000020",
            phone="923000020",
            email="activity-business@example.com",
            address_line_1="Calle Actividad 20",
            postal_code="37020",
            city="Salamanca",
            province="Salamanca",
            country_code="ES",
            store_name="Centro Activity",
            owner_first_name="Activity",
            owner_last_name="E2E",
            owner_email=self.EMAIL,
            owner_phone="600000020",
            owner_password=self.PASSWORD,
            owner_pin="1234",
        )
        store_b = Store.objects.create(
            business=result.business, name="Norte Activity", code="ACT-NORTH"
        )
        manager = CustomUser.objects.create_user(
            business=result.business,
            email=self.MANAGER_EMAIL,
            password=self.PASSWORD,
            role=RoleChoices.MANAGER,
            first_name="Manager",
        )
        cashier = CustomUser.objects.create_user(
            business=result.business,
            email=self.CASHIER_EMAIL,
            password=self.PASSWORD,
            role=RoleChoices.CASHIER,
            first_name="Cashier",
        )
        UserStoreAccess.objects.create(
            business=result.business, user=manager, store=result.store
        )
        UserStoreAccess.objects.create(
            business=result.business, user=cashier, store=result.store
        )
        sale = create_sale(
            business=result.business,
            store=result.store,
            opened_by=result.owner,
            status=SaleStatusChoices.COMPLETED,
        )
        sale_event = log_event(
            business=result.business,
            store=result.store,
            user=result.owner,
            event_type=AuditEventType.SALE_COMPLETED,
            module=AuditModule.SALES,
            message=f"Venta #{sale.pk} completada.",
            entity=sale,
            old_payload={"total_amount": "10.00", "token": "never-visible"},
            new_payload={"total_amount": "20.00"},
            metadata={
                "safe_context": "Metadata Activity E2E",
                "token": "metadata-never-visible",
            },
            ip_address="192.0.2.208",
        )
        supplier = Supplier.objects.create(
            business=result.business, name="Proveedor Activity"
        )
        purchase = Purchase.objects.create(
            business=result.business,
            store=result.store,
            supplier=supplier,
            created_by=result.owner,
            reference="ACT-PURCHASE",
        )
        purchase_event = log_event(
            business=result.business,
            store=result.store,
            user=result.owner,
            event_type=AuditEventType.PURCHASE_CREATED,
            module=AuditModule.PURCHASES,
            message=f"Compra #{purchase.pk} creada.",
            entity=purchase,
        )
        global_event = log_event(
            business=result.business,
            user=None,
            event_type=AuditEventType.BUSINESS_CONFIG_CHANGED,
            module=AuditModule.BUSINESS_CONFIG,
            message="Configuración del negocio modificada.",
        )
        hidden_event = log_event(
            business=result.business,
            store=store_b,
            user=result.owner,
            event_type=AuditEventType.SALE_COMPLETED,
            module=AuditModule.SALES,
            message="Venta Store B secreta.",
        )
        self.store_a_id = result.store.pk
        self.store_b_id = store_b.pk
        self.owner_id = result.owner.pk
        self.sale_event_id = sale_event.pk
        self.purchase_event_id = purchase_event.pk
        self.global_event_id = global_event.pk
        self.hidden_event_id = hidden_event.pk

    def _login(self, page, email):
        page.goto(f"{self.live_server_url}/users/login/")
        page.get_by_label("Correo electrónico").fill(email)
        page.get_by_label("Contraseña").fill(self.PASSWORD)
        page.get_by_role("button", name="Iniciar sesión").click()

    def test_activity_timeline_filters_detail_and_responsive_layout(self):
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            try:
                page = browser.new_page(viewport={"width": 1280, "height": 900})
                self._login(page, self.EMAIL)
                page.get_by_role("navigation", name="Navegación principal").get_by_role(
                    "link", name="Actividad", exact=True
                ).click()
                expect(page).to_have_url(re.compile(r"/activity/"))
                expect(
                    page.get_by_role("heading", name="Actividad", exact=True)
                ).to_be_visible()
                expect(page.locator("#activity-results")).to_have_count(1)
                expect(
                    page.locator("#activity-results").get_by_text("Sistema", exact=True)
                ).to_be_visible()
                system_item = page.locator(
                    ".activity-item", has_text="Configuración del negocio modificada."
                )
                system_item.get_by_role("button", name="Ver detalle").click()
                expect(
                    page.locator("#activity-drawer").get_by_text("Sistema", exact=True)
                ).to_be_visible()
                page.get_by_role("button", name="Cerrar detalle").click()
                filters = page.locator("#activity-filters")
                expect(filters).to_be_visible()
                filters.get_by_label("Módulo", exact=True).select_option("sales")
                filters.get_by_role("button", name="Aplicar filtros").click()
                expect(page).to_have_url(re.compile(r"module=sales"))
                expect(page.locator("#activity-results")).to_have_count(1)
                sale_item = page.locator(".activity-item", has_text="Venta #")
                sale_item.get_by_role("button", name="Ver detalle").click()
                expect(page.locator("#activity-drawer")).to_be_visible()
                expect(
                    page.locator("#activity-drawer").get_by_text(
                        "Activity E2E", exact=True
                    )
                ).to_be_visible()
                expect(
                    page.locator("#activity-drawer").get_by_text(
                        "Centro Activity", exact=True
                    )
                ).to_be_visible()
                expect(
                    page.locator("#activity-drawer").get_by_text("Ventas", exact=True)
                ).to_be_visible()
                technical = page.locator("#activity-drawer .activity-technical")
                expect(
                    technical.get_by_text("SALE_COMPLETED", exact=True)
                ).to_be_hidden()
                expect(page.locator("#activity-drawer time")).to_have_count(1)
                expect(
                    page.locator("#activity-drawer").get_by_text("Venta", exact=True)
                ).to_be_visible()
                expect(
                    page.locator("#activity-drawer").get_by_text(
                        re.compile(r"Venta #\d+ completada\.")
                    )
                ).to_be_visible()
                expect(
                    page.locator("#activity-drawer").get_by_text("10,00 €", exact=True)
                ).to_be_visible()
                expect(
                    page.locator("#activity-drawer").get_by_text("20,00 €", exact=True)
                ).to_be_visible()
                token_row = page.locator("#activity-drawer").get_by_role(
                    "row", name=re.compile(r"Token")
                )
                expect(
                    token_row.get_by_role("cell", name="Dato protegido")
                ).to_have_count(2)
                self.assertNotIn("never-visible", page.content())
                self.assertNotIn("metadata-never-visible", page.content())
                technical.get_by_text("Información técnica", exact=True).click()
                expect(
                    technical.get_by_text("SALE_COMPLETED", exact=True)
                ).to_be_visible()
                expect(
                    technical.get_by_text("Metadata Activity E2E", exact=True)
                ).to_be_visible()
                expect(technical.get_by_text("192.0.2.208", exact=True)).to_be_visible()
                expect(
                    technical.get_by_text("Dato protegido", exact=True)
                ).to_be_visible()
                trigger = sale_item.get_by_role("button", name="Ver detalle")
                page.get_by_role("button", name="Cerrar detalle").click()
                expect(trigger).to_be_focused()
                trigger.click()
                page.get_by_role("link", name="Ver venta").click()
                expect(page).to_have_url(re.compile(r"/sales/stores/.*/sales/"))
                page.goto(f"{self.live_server_url}/activity/")
                purchase_item = page.locator(".activity-item", has_text="Compra #")
                purchase_item.get_by_role("button", name="Ver detalle").click()
                page.get_by_role("link", name="Ver compra").click()
                expect(page).to_have_url(re.compile(r"/purchases/\d+/"))
                page.goto(f"{self.live_server_url}/activity/")
                for width in (375, 767, 768, 1280):
                    page.set_viewport_size({"width": width, "height": 900})
                    self.assertLessEqual(
                        page.evaluate("document.documentElement.scrollWidth"), width
                    )
                    filters = page.locator("#activity-filters")
                    if width <= 767:
                        trigger = page.locator(".activity-filter-panel > summary")
                        expect(filters).to_be_hidden()
                        trigger.click()
                        expect(filters).to_be_visible()
                        page.keyboard.press("Escape")
                        expect(filters).to_be_hidden()
                        expect(trigger).to_be_focused()
                    else:
                        expect(filters).to_be_visible()
            finally:
                browser.close()

    def test_filter_chips_update_form_url_results_and_browser_history(self):
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            try:
                page = browser.new_page(viewport={"width": 1280, "height": 900})
                self._login(page, self.EMAIL)
                page.goto(f"{self.live_server_url}/activity/")
                filters = page.locator("#activity-filters")
                filters.get_by_label("Periodo", exact=True).select_option("7d")
                filters.get_by_label("Tienda", exact=True).select_option(
                    str(self.store_a_id)
                )
                filters.get_by_label("Actor", exact=True).select_option(
                    str(self.owner_id)
                )
                filters.get_by_label("Módulo", exact=True).select_option("sales")
                filters.get_by_label("Buscar", exact=True).fill("Venta")
                filters.get_by_role("button", name="Aplicar filtros").click()
                expect(page.locator("#activity-filters")).to_have_count(1)
                expect(page.locator("#activity-results")).to_have_count(1)
                expect(filters.get_by_label("Evento", exact=True)).to_have_value("")
                expect(
                    filters.get_by_label("Evento", exact=True).locator("option")
                ).to_have_count(5)
                filters.get_by_label("Evento", exact=True).select_option(
                    "SALE_COMPLETED"
                )
                filters.get_by_role("button", name="Aplicar filtros").click()
                expect(page).to_have_url(re.compile(r"event_type=SALE_COMPLETED"))
                page.get_by_role("link", name="Eliminar filtro Ventas").click()
                expect(filters.get_by_label("Módulo", exact=True)).to_have_value("")
                expect(filters.get_by_label("Evento", exact=True)).to_have_value("")
                expect(page).not_to_have_url(re.compile(r"module=|event_type="))
                expect(page).to_have_url(re.compile(r"period=7d"))
                expect(filters.get_by_label("Tienda", exact=True)).to_have_value(
                    str(self.store_a_id)
                )
                expect(filters.get_by_label("Actor", exact=True)).to_have_value(
                    str(self.owner_id)
                )
                expect(filters.get_by_label("Buscar", exact=True)).to_have_value(
                    "Venta"
                )
                page.go_back()
                expect(filters.get_by_label("Módulo", exact=True)).to_have_value(
                    "sales"
                )
                page.go_forward()
                expect(filters.get_by_label("Módulo", exact=True)).to_have_value("")
                page.get_by_role("link", name="Limpiar todo").click()
                expect(page).to_have_url(re.compile(r"/activity/$"))
                expect(filters.get_by_label("Periodo", exact=True)).to_have_value("30d")
                expect(filters.get_by_label("Tienda", exact=True)).to_have_value("")
                expect(filters.get_by_label("Actor", exact=True)).to_have_value("")
                expect(filters.get_by_label("Buscar", exact=True)).to_have_value("")
                expect(page.locator("#activity-filters")).to_have_count(1)
                expect(page.locator("#activity-results")).to_have_count(1)
                filters.get_by_label("Buscar", exact=True).fill(
                    "resultado-e2e-inexistente"
                )
                filters.get_by_role("button", name="Aplicar filtros").click()
                expect(
                    page.get_by_role("heading", name="No encontramos actividad")
                ).to_be_visible()
                expect(page.locator("#activity-results")).to_have_count(1)
                page.get_by_role("link", name="LIMPIAR FILTROS").click()
                expect(page).to_have_url(re.compile(r"/activity/$"))
                expect(filters.get_by_label("Buscar", exact=True)).to_have_value("")
                expect(page.locator("#activity-workspace")).to_have_count(1)
                expect(page.locator("#activity-filters")).to_have_count(1)
                expect(page.locator("#activity-results")).to_have_count(1)
            finally:
                browser.close()

    def test_pagination_keeps_single_workspace_and_selected_filters(self):
        business = Store.objects.get(pk=self.store_a_id).business
        store = Store.objects.get(pk=self.store_a_id)
        owner = CustomUser.objects.get(pk=self.owner_id)
        for index in range(27):
            log_event(
                business=business,
                store=store,
                user=owner,
                event_type=AuditEventType.SALE_COMPLETED,
                module=AuditModule.SALES,
                message=f"Actividad paginada E2E {index:02d}",
            )
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            try:
                page = browser.new_page(viewport={"width": 1280, "height": 900})
                self._login(page, self.EMAIL)
                page.goto(f"{self.live_server_url}/activity/")
                filters = page.locator("#activity-filters")
                filters.get_by_label("Módulo", exact=True).select_option("sales")
                filters.get_by_label("Buscar", exact=True).fill("Actividad paginada")
                filters.get_by_role("button", name="Aplicar filtros").click()
                expect(
                    page.locator(".activity-item").filter(has_text="Actividad paginada")
                ).to_have_count(25)
                pagination = page.get_by_role(
                    "navigation", name="Paginación de actividad"
                )
                pagination.get_by_role("link", name="Siguiente").click()
                expect(page).to_have_url(re.compile(r"[?&]page=2(?:&|$)"))
                pagination = page.get_by_role(
                    "navigation", name="Paginación de actividad"
                )
                expect(
                    pagination.get_by_text(re.compile(r"Página 2 de 2"))
                ).to_be_visible()
                expect(page.locator(".activity-item")).to_have_count(2)
                expect(pagination.get_by_role("link", name="Anterior")).to_be_visible()
                expect(page.locator("#activity-workspace")).to_have_count(1)
                expect(page.locator("#activity-filters")).to_have_count(1)
                expect(page.locator("#activity-results")).to_have_count(1)
                expect(filters.get_by_label("Módulo", exact=True)).to_have_value(
                    "sales"
                )
                expect(filters.get_by_label("Buscar", exact=True)).to_have_value(
                    "Actividad paginada"
                )
                pagination.get_by_role("link", name="Anterior").click()
                expect(page).not_to_have_url(re.compile(r"[?&]page=2(?:&|$)"))
                pagination = page.get_by_role(
                    "navigation", name="Paginación de actividad"
                )
                expect(
                    pagination.get_by_text(re.compile(r"Página 1 de 2"))
                ).to_be_visible()
                expect(
                    page.locator(".activity-item").filter(has_text="Actividad paginada")
                ).to_have_count(25)
            finally:
                browser.close()

    def test_manager_scope_and_cashier_permissions(self):
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            try:
                manager_page = browser.new_page()
                self._login(manager_page, self.MANAGER_EMAIL)
                manager_page.goto(f"{self.live_server_url}/activity/")
                expect(
                    manager_page.get_by_text("Venta Store B secreta.")
                ).to_have_count(0)
                expect(
                    manager_page.get_by_text("Configuración del negocio modificada.")
                ).to_have_count(0)
                expect(
                    manager_page.get_by_text(re.compile(r"Venta #\d+ completada"))
                ).to_be_visible()
                response = manager_page.goto(
                    f"{self.live_server_url}/activity/?period=30d&store={self.store_b_id}"
                )
                self.assertEqual(response.status, 422)
                expect(
                    manager_page.get_by_text("Venta Store B secreta.")
                ).to_have_count(0)
                response = manager_page.goto(
                    f"{self.live_server_url}/activity/{self.hidden_event_id}/"
                )
                self.assertEqual(response.status, 404)
                response = manager_page.goto(
                    f"{self.live_server_url}/activity/{self.global_event_id}/"
                )
                self.assertEqual(response.status, 404)
                response = manager_page.goto(
                    f"{self.live_server_url}/activity/{self.sale_event_id}/"
                )
                self.assertEqual(response.status, 200)
                manager_technical = manager_page.locator(".activity-technical")
                manager_technical.get_by_text("Información técnica", exact=True).click()
                expect(
                    manager_technical.get_by_text("192.0.2.208", exact=True)
                ).to_have_count(0)
                expect(
                    manager_technical.get_by_text("Metadata Activity E2E", exact=True)
                ).to_have_count(0)

                cashier_page = browser.new_page()
                self._login(cashier_page, self.CASHIER_EMAIL)
                navigation = cashier_page.get_by_role(
                    "navigation", name="Navegación principal"
                )
                expect(navigation.get_by_role("link", name="Actividad")).to_have_count(
                    0
                )
                cashier_page.locator("[data-command-trigger]").click()
                expect(
                    cashier_page.locator("[data-command-dialog]").get_by_role(
                        "link", name="Actividad"
                    )
                ).to_have_count(0)
                response = cashier_page.goto(f"{self.live_server_url}/activity/")
                self.assertEqual(response.status, 403)
            finally:
                browser.close()
