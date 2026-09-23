"""Real Chromium coverage for the FE-12 responsive returns workflow."""

import re
from decimal import Decimal

from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.test import override_settings
from playwright.sync_api import expect, sync_playwright

from apps.billing.models import BillingDocument
from apps.cash_register.models import CashSession
from apps.inventory.models import StockMovement
from apps.onboarding.services import OnboardingService
from apps.payments.models import Payment
from apps.sales.models import SaleReturn, SaleReturnStatusChoices
from apps.sales.services import (
    add_sale_line,
    add_sale_return_line,
    complete_sale,
    complete_sale_return,
    create_sale_return,
    open_sale,
)
from apps.sales.tests.factories import (
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
        self.session = CashSession.objects.create(
            business=result.business,
            store=result.store,
            cash_register=result.cash_register,
            opened_by=result.owner,
        )
        self.product = create_sales_product(
            business=result.business,
            name="Coca-Cola 33cl",
            sku="COLA-33",
            base_price=Decimal("2.00"),
            track_stock=True,
        )
        self.inventory = create_sales_inventory_item(
            business=result.business,
            store=result.store,
            product=self.product,
            current_stock=Decimal("50.000"),
        )
        sale = open_sale(
            business=result.business,
            store=result.store,
            cash_register=result.cash_register,
            cash_session=self.session,
            opened_by=result.owner,
        )
        add_sale_line(
            business=result.business,
            sale=sale,
            product=self.product,
            quantity=Decimal("2.000"),
            user=result.owner,
        )
        complete_sale(business=result.business, sale=sale, closed_by=result.owner)
        self.sale = sale

    def _login(self, page):
        page.goto(f"{self.live_server_url}/users/login/")
        page.get_by_label("Correo electrónico").fill(self.result.owner.email)
        page.get_by_label("Contraseña").fill(self.password)
        page.get_by_role("button", name="Iniciar sesión").click()

    def _create_draft(self, page, reason="Producto defectuoso"):
        page.goto(
            f"{self.live_server_url}/sales/stores/{self.result.store.pk}/sales/{self.sale.pk}/"
        )
        page.get_by_role("link", name="Crear devolución").click()
        page.get_by_label("Motivo de la devolución").fill(reason)
        page.get_by_role("button", name="Iniciar devolución").click()
        return page.url

    def _assert_interactive_workspace(self, page):
        row = page.locator(".return-line").filter(has_text="Coca-Cola 33cl")
        expect(row).to_be_visible()
        expect(row.locator('[data-label="Vendido"]')).to_contain_text(
            re.compile(r"2[,.]000")
        )
        expect(row.locator('[data-label="Devuelto"]')).to_be_visible()
        expect(row.locator('[data-label="Disponible"]')).to_be_visible()
        quantity = row.get_by_label("Cantidad a devolver de Coca-Cola 33cl")
        expect(quantity).to_be_editable()
        quantity.fill("0")
        row.get_by_role("button", name="Sumar una unidad de Coca-Cola 33cl").click()
        expect(quantity).to_have_value("1")
        row.get_by_role("button", name="Restar una unidad de Coca-Cola 33cl").click()
        expect(quantity).to_have_value("0")
        row.get_by_role("button", name="Sumar una unidad de Coca-Cola 33cl").click()
        expect(row.get_by_label("Devolver al stock disponible")).to_be_checked()
        row.get_by_role("button", name="Actualizar").click()
        expect(page.locator(".return-total strong")).to_have_text(
            re.compile(r"2[,.]42 €")
        )
        # The workspace was replaced by HTMX: exercise controls from the new DOM.
        swapped_row = page.locator(".return-line").filter(has_text="Coca-Cola 33cl")
        swapped_quantity = swapped_row.get_by_label(
            "Cantidad a devolver de Coca-Cola 33cl"
        )
        swapped_row.get_by_role(
            "button", name="Restar una unidad de Coca-Cola 33cl"
        ).click()
        expect(swapped_quantity).to_have_value("0")
        swapped_row.get_by_role(
            "button", name="Sumar una unidad de Coca-Cola 33cl"
        ).click()
        expect(swapped_quantity).to_have_value("1")
        self.assertLessEqual(
            page.evaluate("document.documentElement.scrollWidth"),
            page.evaluate("document.documentElement.clientWidth"),
        )

    def test_create_and_edit_return_at_supported_viewports(self):
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            draft_url = None
            for width, height in ((1440, 900), (900, 900), (375, 812)):
                page = browser.new_page(viewport={"width": width, "height": height})
                self._login(page)
                draft_url = draft_url or self._create_draft(page)
                page.goto(draft_url)
                self._assert_interactive_workspace(page)
                page.close()
            browser.close()

    def test_happy_return_completes_and_restocks(self):
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1440, "height": 900})
            self._login(page)
            self._create_draft(page)
            self._assert_interactive_workspace(page)
            page.get_by_label("PIN de seguridad").fill("1234")
            page.get_by_role("button", name="Completar devolución").click()
            expect(page.get_by_text("✓ Devolución completada")).to_be_visible()
            expect(page.get_by_text("Reembolso")).to_be_visible()
            expect(page.get_by_text("Documento rectificativo")).to_be_visible()
            browser.close()
        returned = SaleReturn.objects.get(original_sale=self.sale)
        self.assertEqual(returned.status, SaleReturnStatusChoices.COMPLETED)
        self.assertEqual(returned.lines.get().quantity, Decimal("1.000"))
        self.assertTrue(
            StockMovement.objects.filter(sale_return=returned, quantity__gt=0).exists()
        )

    def test_already_returned_and_invalid_quantity_stays_safe(self):
        previous = create_sale_return(
            business=self.result.business,
            store=self.result.store,
            original_sale=self.sale,
            created_by=self.result.owner,
            reason="Primera unidad",
        )
        add_sale_return_line(
            business=self.result.business,
            return_doc=previous,
            original_line=self.sale.lines.get(),
            quantity=Decimal("1.000"),
            restock=True,
            user=self.result.owner,
        )
        complete_sale_return(
            business=self.result.business,
            return_doc=previous,
            completed_by=self.result.owner,
            pin="1234",
        )
        movement_count = StockMovement.objects.count()
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 375, "height": 812})
            self._login(page)
            self._create_draft(page, "Segunda unidad")
            row = page.locator(".return-line").filter(has_text="Coca-Cola 33cl")
            expect(row.locator('[data-label="Vendido"]')).to_contain_text(
                re.compile(r"2[,.]000")
            )
            expect(row.locator('[data-label="Devuelto"]')).to_contain_text(
                re.compile(r"1[,.]000")
            )
            expect(row.locator('[data-label="Disponible"]')).to_contain_text(
                re.compile(r"1[,.]000")
            )
            row.get_by_label("Cantidad a devolver de Coca-Cola 33cl").fill("2")
            row.get_by_role("button", name="Actualizar").click()
            expect(page.get_by_role("alert")).to_contain_text("supera")
            browser.close()
        draft = SaleReturn.objects.filter(original_sale=self.sale).latest("pk")
        self.assertEqual(draft.status, SaleReturnStatusChoices.DRAFT)
        self.assertFalse(draft.lines.exists())
        self.assertEqual(Payment.objects.filter(sale_return=draft).count(), 0)
        self.assertEqual(BillingDocument.objects.filter(sale_return=draft).count(), 0)
        self.assertEqual(StockMovement.objects.count(), movement_count)

    def test_cancel_draft_has_no_operational_side_effects(self):
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 900, "height": 900})
            self._login(page)
            self._create_draft(page, "Cancelar prueba")
            self._assert_interactive_workspace(page)
            movement_count = StockMovement.objects.count()
            page.get_by_role("link", name="Cancelar", exact=True).click()
            page.get_by_label("PIN de seguridad").fill("1234")
            page.get_by_role("button", name="Cancelar devolución").click()
            expect(page.get_by_text("Devolución cancelada")).to_be_visible()
            browser.close()
        returned = SaleReturn.objects.get(original_sale=self.sale)
        self.assertEqual(returned.status, SaleReturnStatusChoices.CANCELLED)
        self.assertEqual(StockMovement.objects.count(), movement_count)
        self.assertFalse(Payment.objects.filter(sale_return=returned).exists())
        self.assertFalse(BillingDocument.objects.filter(sale_return=returned).exists())
