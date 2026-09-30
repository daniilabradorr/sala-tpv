"""Real Chromium coverage for FE-23 configuration."""

import re

from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.test import override_settings
from playwright.sync_api import expect, sync_playwright

from apps.onboarding.services import OnboardingService
from apps.payments.models import PaymentMethod
from apps.users.models import CustomUser, RoleChoices


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
        self.business = result.business
        self.manager = CustomUser.objects.create_user(
            business=self.business,
            email="config-manager@example.com",
            password="Configuration-Password-123!",
            role=RoleChoices.MANAGER,
        )
        self.cashier = CustomUser.objects.create_user(
            business=self.business,
            email="config-cashier@example.com",
            password="Configuration-Password-123!",
            role=RoleChoices.CASHIER,
        )

    def login(self, page, email):
        page.goto(f"{self.live_server_url}/users/login/")
        page.get_by_label("Correo electrónico").fill(email)
        page.get_by_label("Contraseña").fill("Configuration-Password-123!")
        page.get_by_role("button", name="Iniciar sesión").click()

    def test_owner_configures_mvp_payment_method_without_horizontal_overflow(self):
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 375, "height": 812})
            self.login(page, self.owner.email)
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

    def test_owner_reviews_and_persists_business_and_pos_changes(self):
        profile = self.business.profile
        settings = self.business.pos_settings
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1280, "height": 900})
            self.login(page, self.owner.email)
            page.goto(f"{self.live_server_url}/config/profile/")
            for section in (
                "Datos legales",
                "Identidad comercial",
                "Contacto",
                "Dirección",
                "Ticket",
                "Política de devoluciones",
            ):
                expect(page.get_by_text(section, exact=True)).to_be_visible()
            page.get_by_label("NIF/CIF").fill("B10000999")
            page.get_by_role("button", name="Guardar cambios").click()
            expect(page.get_by_text("Antes:", exact=True)).to_be_visible()
            expect(page.get_by_text("Después:", exact=True)).to_be_visible()
            page.get_by_role("button", name="Confirmar y guardar").click()
            expect(
                page.get_by_text("Datos de empresa actualizados correctamente.")
            ).to_be_visible()
            page.goto(f"{self.live_server_url}/config/pos/")
            expect(
                page.get_by_role("heading", name="Configuración actual")
            ).to_be_visible()
            page.get_by_label("Permitir descuentos manuales").uncheck()
            page.get_by_label("Activar control de stock").uncheck()
            page.get_by_label("Requiere caja abierta").uncheck()
            expect(page.locator("[data-pending-count]")).to_contain_text("cambio")
            page.get_by_role("button", name="Guardar cambios").click()
            expect(
                page.get_by_text(
                    "Desactivar el control de stock hará que las ventas no validen inventario."
                )
            ).to_be_visible()
            expect(
                page.get_by_text("Las ventas dejarán de exigir una caja abierta.")
            ).to_be_visible()
            page.get_by_role("button", name="Confirmar y guardar").click()
            browser.close()
        profile.refresh_from_db()
        self.assertEqual(profile.tax_identifier, "B10000999")
        settings.refresh_from_db()
        self.assertFalse(settings.allow_manual_discounts)
        self.assertEqual(settings.max_manual_discount_percent, 0)
        self.assertFalse(settings.enable_stock_control)
        self.assertFalse(settings.require_open_cash_register)

    def test_profile_review_cancel_does_not_persist(self):
        profile = self.business.profile
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page()
            self.login(page, self.owner.email)
            page.goto(f"{self.live_server_url}/config/profile/")
            tax_identifier = page.get_by_label("NIF/CIF")
            tax_identifier.fill("B10000998")
            page.get_by_role("button", name="Guardar cambios").click()
            page.get_by_role("button", name="Seguir editando").click()
            expect(tax_identifier).to_have_value("B10000998")
            browser.close()
        profile.refresh_from_db()
        self.assertEqual(profile.tax_identifier, "B10000023")

    def test_owner_updates_payment_method_through_real_form(self):
        card = PaymentMethod.objects.get(business=self.business, code="card")
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page()
            self.login(page, self.owner.email)
            page.goto(f"{self.live_server_url}/config/payments/{card.pk}/")
            page.get_by_label("Nombre").fill("Tarjeta bancaria")
            page.get_by_label("Permite reembolso").uncheck()
            page.get_by_role("button", name="Guardar").click()
            expect(
                page.get_by_text("Método de pago actualizado correctamente.")
            ).to_be_visible()
            expect(
                page.get_by_role("heading", name=re.compile("^Tarjeta bancaria"))
            ).to_be_visible()
            browser.close()
        card.refresh_from_db()
        self.assertEqual(card.name, "Tarjeta bancaria")
        self.assertTrue(card.is_active)
        self.assertFalse(card.allows_refund)
        self.assertEqual(card.code, "card")
        self.assertFalse(card.affects_cash_register)
        self.assertEqual(card.business, self.business)

    def test_manager_and_cashier_have_no_configuration_access(self):
        method = PaymentMethod.objects.get(business=self.business, code="card")
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            for actor in (self.manager, self.cashier):
                context = browser.new_context()
                page = context.new_page()
                self.login(page, actor.email)
                expect(page.locator('a[href="/config/profile/"]')).to_have_count(0)
                page.get_by_role("button", name="Buscar módulo o acción").click()
                expect(
                    page.locator('[data-command-dialog] a[href="/config/profile/"]')
                ).to_have_count(0)
                for path in (
                    "/config/profile/",
                    "/config/pos/",
                    f"/config/payments/{method.pk}/",
                ):
                    response = page.goto(f"{self.live_server_url}{path}")
                    self.assertEqual(response.status, 403)
                context.close()
            browser.close()

    def test_configuration_has_no_overflow_at_product_breakpoints(self):
        card_pk = PaymentMethod.objects.get(business=self.business, code="card").pk
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            for width, height in ((375, 812), (767, 900), (768, 900), (1280, 900)):
                context = browser.new_context(
                    viewport={"width": width, "height": height}
                )
                page = context.new_page()
                self.login(page, self.owner.email)
                for path in (
                    "/config/profile/",
                    "/config/pos/",
                    f"/config/payments/{card_pk}/",
                ):
                    page.goto(f"{self.live_server_url}{path}")
                    self.assertLessEqual(
                        page.evaluate("document.documentElement.scrollWidth"), width
                    )
                context.close()
            browser.close()
