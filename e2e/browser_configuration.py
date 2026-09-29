"""Real Chromium coverage for FE-23 configuration."""

import re

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
class BrowserConfigurationTests(StaticLiveServerTestCase):
    def setUp(self):
        result = OnboardingService.create_business(
            legal_name="Configuración E2E SL",
            trade_name="Configuración E2E",
            tax_identifier="B10000023",
            phone="600000023",
            email="config@example.com",
            address_line_1="Calle Configuración",
            postal_code="28023",
            city="Madrid",
            province="Madrid",
            country_code="ES",
            store_name="Centro",
            owner_first_name="Owner",
            owner_last_name="Config",
            owner_email="config-owner@example.com",
            owner_phone="600100023",
            owner_password="Configuration-Password-123!",
            owner_pin="1234",
        )
        self.owner = result.owner

    def test_owner_configures_mvp_payment_method_without_horizontal_overflow(self):
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 375, "height": 812})
            page.goto(f"{self.live_server_url}/users/login/")
            page.get_by_label("Correo electrónico").fill(self.owner.email)
            page.get_by_label("Contraseña").fill("Configuration-Password-123!")
            page.get_by_role("button", name="Iniciar sesión").click()
            page.goto(f"{self.live_server_url}/config/pos/")
            expect(
                page.get_by_role("heading", name="Configuración", exact=True)
            ).to_be_visible()
            for name in ("Efectivo", "Tarjeta", "Bizum", "Transferencia"):
                expect(
                    page.get_by_role("heading", name=re.compile(f"^{name}"))
                ).to_be_visible()
            assert page.evaluate(
                "document.documentElement.scrollWidth <= window.innerWidth"
            )
            card = page.locator(
                "article", has=page.get_by_role("heading", name=re.compile("^Tarjeta"))
            )
            card.get_by_role("link", name="Configurar").click()
            expect(
                page.get_by_role("heading", name="Configurar Tarjeta")
            ).to_be_visible()
            expect(page.get_by_text("card", exact=True)).to_be_visible()
            browser.close()
