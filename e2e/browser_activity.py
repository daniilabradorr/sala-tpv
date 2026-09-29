"""Real Chromium coverage for the FE-20 Activity surface."""

import re

from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.test import override_settings
from playwright.sync_api import expect, sync_playwright

from apps.audit.constants import AuditEventType, AuditModule
from apps.audit.services import log_event
from apps.onboarding.services import OnboardingService


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
        log_event(
            business=result.business,
            store=result.store,
            user=result.owner,
            event_type=AuditEventType.SALE_COMPLETED,
            module=AuditModule.SALES,
            message="Venta #20 completada.",
            entity_type="sales.sale",
            entity_id="20",
            old_payload={"total_amount": "10.00", "token": "never-visible"},
            new_payload={"total_amount": "20.00", "token": "never-visible"},
        )
        log_event(
            business=result.business,
            user=None,
            event_type=AuditEventType.BUSINESS_CONFIG_CHANGED,
            module=AuditModule.BUSINESS_CONFIG,
            message="Configuración del negocio modificada.",
        )

    def test_activity_timeline_filters_detail_and_responsive_layout(self):
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            try:
                page = browser.new_page(viewport={"width": 1280, "height": 900})
                page.goto(f"{self.live_server_url}/users/login/")
                page.get_by_label("Correo electrónico").fill(self.EMAIL)
                page.get_by_label("Contraseña").fill(self.PASSWORD)
                page.get_by_role("button", name="Iniciar sesión").click()
                page.get_by_role("navigation", name="Navegación principal").get_by_role(
                    "link", name="Actividad", exact=True
                ).click()
                expect(page).to_have_url(re.compile(r"/activity/"))
                expect(
                    page.get_by_role("heading", name="Actividad", exact=True)
                ).to_be_visible()
                expect(page.locator("#activity-results")).to_have_count(1)
                expect(page.get_by_text("Sistema", exact=True)).to_be_visible()
                page.get_by_label("Módulo").select_option("sales")
                page.get_by_role("button", name="Aplicar filtros").click()
                expect(page).to_have_url(re.compile(r"module=sales"))
                expect(page.locator("#activity-results")).to_have_count(1)
                page.get_by_role("button", name="Ver detalle").click()
                expect(page.locator("#activity-drawer")).to_be_visible()
                expect(page.get_by_text("SALE_COMPLETED", exact=True)).to_be_visible()
                self.assertNotIn("never-visible", page.content())
                page.get_by_role("button", name="Cerrar detalle").click()
                for width in (375, 767, 768, 1280):
                    page.set_viewport_size({"width": width, "height": 900})
                    self.assertLessEqual(
                        page.evaluate("document.documentElement.scrollWidth"), width
                    )
            finally:
                browser.close()
