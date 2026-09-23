"""Real Chromium coverage for the FE-13 cash-register workspace."""

from decimal import Decimal

from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.test import override_settings
from playwright.sync_api import expect, sync_playwright

from apps.cash_register.models import CashCount, CashMovement, CashSession
from apps.cash_register.test_factories import (
    create_cash_business,
    create_cash_register,
    create_cash_store,
)
from apps.users.models import RoleChoices
from apps.users.tests.factories import create_user
from apps.sales.tests.factories import create_pos_settings


@override_settings(
    STORAGES={
        "staticfiles": {
            "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"
        }
    }
)
class CashRegisterBrowserTests(StaticLiveServerTestCase):
    def test_register_open_tabs_and_responsive_layouts(self):
        # All ORM setup happens before Playwright creates its event-loop context.
        business = create_cash_business()
        store = create_cash_store(business=business)
        user = create_user(
            business=business,
            email="cash-browser@test.com",
            role=RoleChoices.OWNER,
            password="Cash-E2E-123!",
        )
        closed = create_cash_register(
            business=business, store=store, name="Caja A", code="A"
        )
        opened = create_cash_register(
            business=business, store=store, name="Caja B", code="B"
        )
        create_cash_register(
            business=business, store=store, name="Caja C", code="C", is_active=False
        )
        open_session = CashSession.objects.create(
            business=business,
            store=store,
            cash_register=opened,
            opened_by=user,
            opening_amount=Decimal("100.00"),
            expected_cash_amount=Decimal("100.00"),
        )
        create_pos_settings(business=business, require_pin_for_sensitive_actions=False)

        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1440, "height": 900})
            page.goto(f"{self.live_server_url}/users/login/")
            page.get_by_label("Correo electrónico").fill(user.email)
            page.get_by_label("Contraseña").fill("Cash-E2E-123!")
            page.get_by_role("button", name="Iniciar sesión").click()
            page.goto(f"{self.live_server_url}/cash-register/stores/{store.pk}/")

            closed_card = page.locator(".register-card").filter(has_text="Caja A")
            open_card = page.locator(".register-card").filter(has_text="Caja B")
            inactive_card = page.locator(".register-card").filter(has_text="Caja C")
            expect(closed_card.get_by_text("CERRADA", exact=True)).to_be_visible()
            expect(open_card.get_by_text("ABIERTA", exact=True)).to_be_visible()
            expect(open_card).to_contain_text("Inicial")
            expect(open_card).to_contain_text("Esperado")
            expect(open_card).to_contain_text(user.email)
            expect(open_card.get_by_role("link", name="Entrar en caja")).to_be_visible()
            expect(inactive_card.get_by_text("INACTIVA", exact=True)).to_be_visible()
            expect(inactive_card.get_by_role("link")).to_have_count(0)

            closed_card.get_by_role("link", name="Abrir caja").click()
            expect(page.get_by_role("dialog")).to_be_visible()
            page.get_by_label("Efectivo inicial").fill("100")
            page.get_by_role("button", name="Abrir caja").click()
            expect(page.get_by_text("Caja abierta correctamente.")).to_be_visible()

            page.goto(
                f"{self.live_server_url}/cash-register/stores/{store.pk}/sessions/{open_session.pk}/"
            )
            for width, height in ((1440, 900), (900, 900), (375, 812)):
                page.set_viewport_size({"width": width, "height": height})
                expect(page.get_by_text("Esperado", exact=True).first).to_be_visible()
                page.get_by_role("tab", name="Ventas").click()
                page.get_by_role("tab", name="Movimientos").click()
                page.get_by_role("tab", name="Arqueos").click()
                page.get_by_role("tab", name="Resumen").click()
                self.assertEqual(page.locator("#cash-tab-panel").count(), 1)
                self.assertLessEqual(
                    page.evaluate("document.documentElement.scrollWidth"), width
                )

            page.set_viewport_size({"width": 1440, "height": 900})
            page.get_by_role("link", name="Entrada", exact=True).click()
            page.get_by_label("Importe").fill("50")
            page.get_by_label("Motivo").fill("Cambio para caja")
            page.get_by_role("button", name="Registrar entrada").click()
            expect(page.get_by_text("150,00 €", exact=True).first).to_be_visible()

            page.get_by_role("link", name="Salida", exact=True).click()
            page.get_by_label("Importe").fill("20")
            page.get_by_label("Motivo").fill("Retirada")
            page.get_by_role("button", name="Registrar salida").click()
            expect(page.get_by_text("130,00 €", exact=True).first).to_be_visible()

            page.get_by_role("link", name="Ajuste", exact=True).click()
            page.get_by_label("Dirección del ajuste").select_option("out")
            page.get_by_label("Importe").fill("5")
            page.get_by_label("Motivo").fill("Error de conteo inicial")
            page.get_by_role("button", name="Registrar ajuste").click()
            expect(page.get_by_text("125,00 €", exact=True).first).to_be_visible()

            page.get_by_role("link", name="Arqueo", exact=True).click()
            page.get_by_label("Efectivo contado").fill("123")
            expect(page.get_by_text("Faltan 2,00 €", exact=True)).to_be_visible()
            page.get_by_role("button", name="Guardar arqueo").click()

            page.get_by_role("link", name="Cerrar caja", exact=True).click()
            page.get_by_label("Efectivo contado").fill("124")
            page.get_by_role("button", name="Continuar").click()
            expect(page.get_by_text("Confirmar cierre", exact=True)).to_be_visible()
            expect(page.get_by_text("124,00 €", exact=True)).to_be_visible()
            page.get_by_role("button", name="Cerrar caja").click()
            expect(page.get_by_text("✓ CAJA CERRADA", exact=True)).to_be_visible()
            expect(page.get_by_role("link", name="Entrada", exact=True)).to_have_count(
                0
            )

            page.goto(
                f"{self.live_server_url}/cash-register/stores/{store.pk}/history/"
            )
            expect(page.get_by_text("Historial de caja", exact=True)).to_be_visible()
            self.assertEqual(page.locator("#cash-history-results").count(), 1)
            browser.close()

        # Playwright has fully exited before direct ORM assertions resume.
        created = CashSession.objects.get(cash_register=closed)
        self.assertEqual(created.status, CashSession.Status.OPEN)
        self.assertEqual(created.opening_amount, Decimal("100.00"))
        self.assertEqual(created.expected_cash_amount, Decimal("100.00"))
        self.assertEqual(created.opened_by, user)
        open_session.refresh_from_db()
        self.assertEqual(open_session.status, CashSession.Status.CLOSED)
        self.assertEqual(open_session.expected_cash_amount, Decimal("125.00"))
        self.assertEqual(open_session.counted_cash_amount, Decimal("124.00"))
        self.assertEqual(open_session.difference_amount, Decimal("-1.00"))
        self.assertEqual(open_session.closed_by, user)
        movements = list(
            CashMovement.objects.filter(cash_session=open_session).order_by(
                "created_at"
            )
        )
        self.assertEqual(
            [(item.movement_type, item.balance_after) for item in movements],
            [
                (CashMovement.MovementType.CASH_IN, Decimal("150.00")),
                (CashMovement.MovementType.CASH_OUT, Decimal("130.00")),
                (CashMovement.MovementType.ADJUSTMENT, Decimal("125.00")),
            ],
        )
        self.assertEqual(
            movements[-1].adjustment_direction,
            CashMovement.AdjustmentDirection.OUT,
        )
        review = CashCount.objects.get(
            cash_session=open_session, count_type=CashCount.CountType.REVIEW
        )
        self.assertEqual(review.expected_amount, Decimal("125.00"))
        self.assertEqual(review.counted_amount, Decimal("123.00"))
        self.assertEqual(review.difference_amount, Decimal("-2.00"))
        self.assertTrue(
            CashCount.objects.filter(
                cash_session=open_session, count_type=CashCount.CountType.CLOSING
            ).exists()
        )
