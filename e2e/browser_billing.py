"""Real Chromium coverage for the FE-18 Billing workspace."""

from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.test import override_settings
from playwright.sync_api import expect, sync_playwright

from apps.onboarding.services import OnboardingService


@override_settings(
    STORAGES={
        "staticfiles": {
            "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"
        }
    }
)
class BrowserBillingTests(StaticLiveServerTestCase):
    email = "billing.e2e@example.com"
    password = "E2E-Billing-123!"

    def setUp(self):
        result = OnboardingService.create_business(
            legal_name="Facturación E2E SL",
            trade_name="Facturación E2E",
            tax_identifier="B11223344",
            phone="923111111",
            email="billing-business@example.com",
            address_line_1="Calle Fiscal 1",
            postal_code="37001",
            city="Salamanca",
            province="Salamanca",
            country_code="ES",
            store_name="Tienda Billing E2E",
            owner_first_name="Ana",
            owner_last_name="Fiscal",
            owner_email=self.email,
            owner_phone="600000000",
            owner_password=self.password,
            owner_pin="1234",
        )
        self.store_id = result.store.pk

    def test_series_workspace_create_edit_and_responsive(self):
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            try:
                page = browser.new_page(viewport={"width": 375, "height": 812})
                page.goto(f"{self.live_server_url}/users/login/")
                page.get_by_label("Correo electrónico").fill(self.email)
                page.get_by_label("Contraseña").fill(self.password)
                page.get_by_role("button", name="Iniciar sesión").click()
                page.wait_for_url(f"{self.live_server_url}/")
                page.goto(
                    f"{self.live_server_url}/billing/stores/{self.store_id}/series/"
                )
                expect(
                    page.get_by_role("heading", name="Series de facturación")
                ).to_be_visible()
                page.get_by_role("link", name="Nueva serie").click()
                page.get_by_label("Tipo de documento").select_option("F1")
                page.get_by_label("Nombre").fill("Serie completa E2E")
                page.get_by_label("Prefijo").fill("E2E-F1")
                page.get_by_label("Dígitos").fill("5")
                page.get_by_role("button", name="Guardar serie").click()
                expect(page.get_by_text("Último número emitido")).to_be_visible()
                expect(page.get_by_text("Siguiente número previsto")).to_be_visible()
                expect(page.locator("#billing-series-results")).to_have_count(0)
                assert page.evaluate(
                    "document.documentElement.scrollWidth <= window.innerWidth"
                )
            finally:
                browser.close()
