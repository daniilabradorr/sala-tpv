"""Real Chromium smoke coverage for the FE-12 responsive returns workspace."""

from decimal import Decimal

from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.test import override_settings
from playwright.sync_api import expect, sync_playwright

from apps.onboarding.services import OnboardingService
from apps.sales.services import add_sale_line, complete_sale, open_sale
from apps.sales.tests.factories import create_sales_product


@override_settings(
    STORAGES={
        "staticfiles": {
            "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"
        }
    }
)
class BrowserReturnsTests(StaticLiveServerTestCase):
    def setUp(self):
        self.password = "Returns-E2E-123!"
        result = OnboardingService.create_business(
            legal_name="Returns E2E SL",
            trade_name="Returns E2E",
            tax_identifier="B12345678",
            phone="923111111",
            email="returns@e2e.test",
            address_line_1="Calle Uno",
            postal_code="37001",
            city="Salamanca",
            province="Salamanca",
            country_code="ES",
            store_name="Tienda Centro",
            owner_first_name="Eva",
            owner_last_name="Returns",
            owner_email="returns.e2e@example.com",
            owner_phone="600000000",
            owner_password=self.password,
            owner_pin="1234",
        )
        self.result = result
        product = create_sales_product(
            business=result.business,
            name="Coca-Cola 33cl",
            sku="COLA-33",
            base_price=Decimal("2.00"),
            track_stock=True,
        )
        sale = open_sale(
            business=result.business, store=result.store, opened_by=result.owner
        )
        add_sale_line(
            business=result.business,
            sale=sale,
            product=product,
            quantity=Decimal("2.000"),
            user=result.owner,
        )
        complete_sale(business=result.business, sale=sale, closed_by=result.owner)
        self.sale = sale

    def test_create_and_edit_return_at_supported_viewports(self):
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            for width, height in ((1440, 900), (900, 900), (375, 812)):
                page = browser.new_page(viewport={"width": width, "height": height})
                page.goto(f"{self.live_server_url}/users/login/")
                page.get_by_label("Correo electrónico").fill(self.result.owner.email)
                page.get_by_label("Contraseña").fill(self.password)
                page.get_by_role("button", name="Iniciar sesión").click()
                page.goto(
                    f"{self.live_server_url}/sales/stores/{self.result.store.pk}/sales/{self.sale.pk}/"
                )
                expect(
                    page.get_by_role("link", name="Crear devolución")
                ).to_be_visible()
                if width == 1440:
                    page.get_by_role("link", name="Crear devolución").click()
                    page.get_by_label("Motivo de la devolución").fill(
                        "Producto defectuoso"
                    )
                    page.get_by_role("button", name="Iniciar devolución").click()
                    expect(page.get_by_text("Coca-Cola 33cl")).to_be_visible()
                    expect(page.get_by_text("2.000", exact=True).first).to_be_visible()
                    page.get_by_label("Sumar una unidad").click()
                    page.get_by_role("button", name="Actualizar").click()
                    expect(page.get_by_text("2.42 €", exact=True)).to_be_visible()
                    self.return_url = page.url
                else:
                    page.goto(self.return_url)
                    expect(
                        page.get_by_role(
                            "heading", name=f"Devolución de venta #{self.sale.pk}"
                        )
                    ).to_be_visible()
                    self.assertLessEqual(
                        page.evaluate("document.documentElement.scrollWidth"), width
                    )
                page.close()
            browser.close()
