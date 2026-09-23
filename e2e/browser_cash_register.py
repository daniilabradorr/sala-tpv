"""Browser coverage for the FE-13 operational cash-register workspace."""

from decimal import Decimal

from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.test import override_settings
from playwright.sync_api import expect, sync_playwright

from apps.cash_register.models import CashMovement, CashRegister
from apps.cash_register.services import CashRegisterService
from apps.onboarding.services import OnboardingService


@override_settings(
    STORAGES={
        "staticfiles": {
            "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"
        }
    }
)
class BrowserCashRegisterTests(StaticLiveServerTestCase):
    def setUp(self):
        self.password = "Cash-E2E-123!"
        self.result = OnboardingService.create_business(
            legal_name="Cash E2E SL",
            trade_name="Cash E2E",
            tax_identifier="B12345678",
            phone="923111111",
            email="cash@e2e.test",
            address_line_1="Calle Caja 1",
            postal_code="37001",
            city="Salamanca",
            province="Salamanca",
            country_code="ES",
            store_name="Tienda Centro",
            owner_first_name="Eva",
            owner_last_name="Caja",
            owner_email="cash.e2e@example.com",
            owner_phone="600000000",
            owner_password=self.password,
            owner_pin="1234",
        )
        self.closed_register = CashRegister.objects.create(
            business=self.result.business,
            store=self.result.store,
            name="Caja cerrada",
            code="CLOSED",
        )
        self.inactive_register = CashRegister.objects.create(
            business=self.result.business,
            store=self.result.store,
            name="Caja inactiva",
            code="INACTIVE",
            is_active=False,
        )
        self.session = CashRegisterService().open_cash_session(
            business=self.result.business,
            store_id=self.result.store.pk,
            cash_register_id=self.result.cash_register.pk,
            user=self.result.owner,
            opening_amount=Decimal("100.00"),
        )

    def _login(self, page):
        page.goto(f"{self.live_server_url}/users/login/")
        page.get_by_label("Correo electrónico").fill(self.result.owner.email)
        page.get_by_label("Contraseña").fill(self.password)
        page.get_by_role("button", name="Iniciar sesión").click()

    def test_register_cards_opening_movements_tabs_and_responsive(self):
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1440, "height": 900})
            self._login(page)
            page.goto(
                f"{self.live_server_url}/cash-register/stores/{self.result.store.pk}/"
            )
            expect(page.get_by_text("Caja cerrada", exact=True)).to_be_visible()
            expect(page.get_by_text("Caja inactiva", exact=True)).to_be_visible()
            expect(page.get_by_role("link", name="Entrar en caja")).to_be_visible()
            page.get_by_role("link", name="Entrar en caja").click()
            expect(page.get_by_text("100,00 €").first).to_be_visible()
            page.get_by_role("link", name="Entrada", exact=True).click()
            page.get_by_label("Importe").fill("50")
            page.get_by_label("Motivo").fill("Cambio para caja")
            page.get_by_role("button", name="Registrar entrada").click()
            expect(page.get_by_text("150,00 €").first).to_be_visible()
            page.get_by_role("tab", name="Movimientos").click()
            expect(page.get_by_text("Entrada manual de efectivo")).to_be_visible()
            for width, height in ((1440, 900), (900, 900), (375, 812)):
                page.set_viewport_size({"width": width, "height": height})
                page.goto(
                    f"{self.live_server_url}/cash-register/stores/{self.result.store.pk}/sessions/{self.session.pk}/"
                )
                expect(page.get_by_role("tab", name="Resumen")).to_be_visible()
                expect(page.get_by_text("150,00 €").first).to_be_visible()
                self.assertLessEqual(
                    page.evaluate("document.documentElement.scrollWidth"),
                    page.evaluate("document.documentElement.clientWidth"),
                )
            browser.close()
        self.session.refresh_from_db()
        self.assertEqual(self.session.expected_cash_amount, Decimal("150.00"))
        self.assertTrue(
            CashMovement.objects.filter(
                cash_session=self.session,
                movement_type=CashMovement.MovementType.CASH_IN,
                balance_after=Decimal("150.00"),
            ).exists()
        )
