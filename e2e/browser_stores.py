"""Real-browser coverage for FE-21 Stores and CashRegister administration."""

from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.test import override_settings
from playwright.sync_api import expect, sync_playwright

from apps.cash_register.models import CashRegister
from apps.onboarding.services import OnboardingService
from apps.stores.models import Store


@override_settings(
    STORAGES={
        "staticfiles": {
            "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"
        }
    }
)
class BrowserStoresTests(StaticLiveServerTestCase):
    password = "E2E-Stores-Password-123!"

    def setUp(self):
        result = OnboardingService.create_business(
            legal_name="Stores E2E SL",
            trade_name="Stores E2E",
            tax_identifier="B10000021",
            phone="923000021",
            email="stores-business@example.com",
            address_line_1="Calle Tiendas 21",
            postal_code="37021",
            city="Salamanca",
            province="Salamanca",
            country_code="ES",
            store_name="Centro",
            owner_first_name="Owner",
            owner_last_name="Stores",
            owner_email="stores.e2e@example.com",
            owner_phone="600000021",
            owner_password=self.password,
            owner_pin="1234",
        )
        self.owner, self.default = result.owner, result.store
        self.second = Store.objects.create(
            business=result.business, name="Gran Vía", code="GRAN-VIA"
        )
        Store.objects.create(
            business=result.business, name="Archivo", code="ARCHIVO", is_active=False
        )
        CashRegister.objects.create(
            business=result.business,
            store=self.second,
            name="Caja principal",
            code="CAJA-01",
        )

    def test_owner_store_workspace_and_responsive_layout(self):
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1280, "height": 800})
            page.goto(f"{self.live_server_url}/login/")
            page.get_by_label("Correo electrónico").fill(self.owner.email)
            page.get_by_label("Contraseña").fill(self.password)
            page.get_by_role("button", name="Iniciar sesión").click()
            page.goto(f"{self.live_server_url}/stores/")
            expect(page.get_by_role("heading", name="Tiendas")).to_be_visible()
            expect(page.get_by_text("Tiendas activas")).to_be_visible()
            page.get_by_placeholder("Buscar tienda...").fill("Gran Vía")
            page.get_by_role("button", name="Filtrar").click()
            expect(page.get_by_role("link", name="Gran Vía")).to_be_visible()
            page.get_by_role("link", name="Gran Vía").click()
            expect(
                page.get_by_role("navigation", name="Secciones de la tienda")
            ).to_be_visible()
            page.get_by_role("link", name="Operación").click()
            page.get_by_role("link", name="Gestionar cajas").click()
            expect(page.get_by_role("heading", name="Cajas")).to_be_visible()
            for width in (375, 767, 768, 1280):
                page.set_viewport_size({"width": width, "height": 812})
                assert page.evaluate(
                    "document.documentElement.scrollWidth <= innerWidth"
                )
            browser.close()
