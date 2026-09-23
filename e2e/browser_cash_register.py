"""Real Chromium coverage for the FE-13 cash-register workspace."""

from decimal import Decimal
import uuid

from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.db import transaction
from django.test import override_settings
from playwright.sync_api import expect, sync_playwright

from apps.cash_register.models import CashCount, CashMovement, CashSession
from apps.cash_register.services import register_payment_cash_movement
from apps.cash_register.test_factories import (
    create_cash_business,
    create_cash_register,
    create_cash_store,
)
from apps.users.models import RoleChoices
from apps.users.tests.factories import create_user
from apps.sales.tests.factories import create_pos_settings
from apps.payments.models import (
    Payment,
    PaymentMethod,
    PaymentStatusChoices,
    PaymentTypeChoices,
)
from apps.sales.models import SaleReturnStatusChoices, SaleStatusChoices
from apps.sales.tests.factories import create_sale, create_sale_return


@override_settings(
    STORAGES={
        "staticfiles": {
            "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"
        }
    }
)
class CashRegisterBrowserTests(StaticLiveServerTestCase):
    def _login(self, page, user, password):
        page.goto(f"{self.live_server_url}/users/login/")
        page.get_by_label("Correo electrónico").fill(user.email)
        page.get_by_label("Contraseña").fill(password)
        page.get_by_role("button", name="Iniciar sesión").click()

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
            self._login(page, user, "Cash-E2E-123!")
            page.goto(f"{self.live_server_url}/cash-register/stores/{store.pk}/")

            closed_card = page.locator(".register-card").filter(has_text="Caja A")
            open_card = page.locator(".register-card").filter(has_text="Caja B")
            inactive_card = page.locator(".register-card").filter(has_text="Caja C")
            expect(closed_card.locator(".cash-status--closed")).to_contain_text(
                "CERRADA"
            )
            expect(open_card.locator(".cash-status--open")).to_contain_text("ABIERTA")
            expect(open_card).to_contain_text("Inicial")
            expect(open_card).to_contain_text("Esperado")
            expect(open_card).to_contain_text(user.email)
            expect(open_card.get_by_role("link", name="Entrar en caja")).to_be_visible()
            expect(inactive_card.locator(".cash-status--inactive")).to_contain_text(
                "INACTIVA"
            )
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
                page.get_by_role("link", name="Entrada", exact=True).click()
                expect(page.get_by_role("dialog")).to_be_visible()
                expect(page.get_by_label("Importe")).to_be_editable()
                page.get_by_role("button", name="Cancelar").click()
                expect(page.get_by_role("dialog")).not_to_be_visible()
                page.get_by_role("tab", name="Ventas").click()
                page.get_by_role("tab", name="Movimientos").click()
                page.get_by_role("tab", name="Arqueos").click()
                page.get_by_role("tab", name="Resumen").click()
                self.assertEqual(page.locator("#cash-tab-panel").count(), 1)
                viewport_metrics = page.evaluate(
                    """() => {
                      const viewport = document.documentElement.clientWidth;
                      const overflowing = [...document.querySelectorAll("*")]
                        .map((el) => {
                          const rect = el.getBoundingClientRect();
                          return {
                            tag: el.tagName,
                            id: el.id || "",
                            cls: typeof el.className === "string" ? el.className : "",
                            left: rect.left,
                            right: rect.right,
                            width: rect.width,
                            scrollWidth: el.scrollWidth,
                          };
                        })
                        .filter((item) => item.right > viewport + 1 || item.left < -1)
                        .slice(0, 10);
                      return {
                        viewport,
                        documentWidth: document.documentElement.scrollWidth,
                        overflowing,
                      };
                    }"""
                )
                self.assertLessEqual(
                    viewport_metrics["documentWidth"],
                    viewport_metrics["viewport"],
                    viewport_metrics["overflowing"],
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
            expect(
                page.get_by_role("heading", name="Confirmar cierre", exact=True)
            ).to_be_visible()
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
            results = page.locator("#cash-history-results")
            expect(results).to_contain_text("Caja A")
            expect(results).to_contain_text("ABIERTA")
            expect(results).to_contain_text("Caja B")
            page.get_by_label("Caja").select_option(str(closed.pk))
            page.get_by_role("button", name="Filtrar").click()
            expect(results).to_contain_text("Caja A")
            expect(results).not_to_contain_text("Caja B")
            self.assertIn(f"cash_register={closed.pk}", page.url)
            self.assertEqual(page.locator("#cash-history-results").count(), 1)
            page.get_by_label("Caja").select_option("")
            page.get_by_label("Usuario").select_option(str(user.pk))
            page.get_by_role("button", name="Filtrar").click()
            expect(results).to_contain_text("Caja A")
            expect(results).to_contain_text("Caja B")
            self.assertIn(f"user={user.pk}", page.url)
            page.go_back()
            expect(page.get_by_label("Caja")).to_have_value(str(closed.pk))
            self.assertEqual(page.locator("#cash-history-results").count(), 1)
            page.get_by_role("link", name="Limpiar filtros").click()
            expect(page.get_by_label("Caja")).to_have_value("")
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

    def test_concurrent_close_swaps_contextual_409(self):
        business = create_cash_business()
        store = create_cash_store(business=business)
        user = create_user(
            business=business,
            email="cash-conflict@test.com",
            role=RoleChoices.OWNER,
            password="Cash-Conflict-123!",
        )
        register = create_cash_register(business=business, store=store)
        session = CashSession.objects.create(
            business=business,
            store=store,
            cash_register=register,
            opened_by=user,
            expected_cash_amount=Decimal("100.00"),
        )
        create_pos_settings(business=business, require_pin_for_sensitive_actions=False)
        detail_url = f"{self.live_server_url}/cash-register/stores/{store.pk}/sessions/{session.pk}/"

        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            first_context = browser.new_context()
            second_context = browser.new_context()
            first = first_context.new_page()
            second = second_context.new_page()
            self._login(first, user, "Cash-Conflict-123!")
            self._login(second, user, "Cash-Conflict-123!")

            first.goto(detail_url)
            first.get_by_role("link", name="Cerrar caja", exact=True).click()
            first.get_by_label("Efectivo contado").fill("100")
            first.get_by_role("button", name="Continuar").click()
            expect(
                first.get_by_role("heading", name="Confirmar cierre", exact=True)
            ).to_be_visible()

            second.goto(detail_url)
            second.get_by_role("link", name="Cerrar caja", exact=True).click()
            second.get_by_label("Efectivo contado").fill("100")
            second.get_by_role("button", name="Continuar").click()
            second.get_by_role("button", name="Cerrar caja").click()
            expect(second.get_by_text("✓ CAJA CERRADA", exact=True)).to_be_visible()

            with first.expect_response(
                lambda response: (
                    response.status == 409 and response.request.method == "POST"
                )
            ) as response_info:
                first.get_by_role("button", name="Cerrar caja").click()
            self.assertEqual(
                response_info.value.headers.get("x-netxodo-allow-error-swap"), "true"
            )
            expect(
                first.get_by_text("Esta caja ya ha sido cerrada.", exact=True)
            ).to_be_visible()
            expect(
                first.get_by_text(
                    "Otro usuario completó la operación antes que tú.", exact=True
                )
            ).to_be_visible()
            expect(first.get_by_role("link", name="Ver caja")).to_be_visible()
            expect(first.get_by_text("Caja cerrada correctamente.")).to_have_count(0)
            first_context.close()
            second_context.close()
            browser.close()

        session.refresh_from_db()
        self.assertEqual(session.status, CashSession.Status.CLOSED)

    def test_payments_summary_stays_separate_from_physical_cash(self):
        business = create_cash_business()
        store = create_cash_store(business=business)
        user = create_user(
            business=business,
            email="cash-payments@test.com",
            role=RoleChoices.OWNER,
            password="Cash-Payments-123!",
        )
        register = create_cash_register(business=business, store=store)
        session = CashSession.objects.create(
            business=business,
            store=store,
            cash_register=register,
            opened_by=user,
            opening_amount=Decimal("100.00"),
            expected_cash_amount=Decimal("100.00"),
        )
        sale = create_sale(
            business=business,
            store=store,
            opened_by=user,
            cash_register=register,
            cash_session=session,
            status=SaleStatusChoices.COMPLETED,
            total_amount=Decimal("120.00"),
        )
        methods = {
            "cash": PaymentMethod.objects.create(
                business=business,
                name="Efectivo",
                code="cash",
                affects_cash_register=True,
            ),
            "card": PaymentMethod.objects.create(
                business=business,
                name="Tarjeta",
                code="card",
                affects_cash_register=False,
            ),
        }

        def payment(code, amount, payment_type=PaymentTypeChoices.SALE_PAYMENT):
            sale_return = None
            if payment_type == PaymentTypeChoices.REFUND:
                sale_return = create_sale_return(
                    business=business,
                    store=store,
                    original_sale=sale,
                    created_by=user,
                    status=SaleReturnStatusChoices.COMPLETED,
                    total_amount=amount,
                )
            return Payment.objects.create(
                business=business,
                store=store,
                sale=sale,
                sale_return=sale_return,
                method=methods[code],
                cash_session=session,
                payment_type=payment_type,
                amount=amount,
                status=PaymentStatusChoices.COMPLETED,
                processed_by=user,
                idempotency_key=uuid.uuid4(),
            )

        cash_payment = payment("cash", Decimal("20.00"))
        payment("card", Decimal("100.00"))
        cash_refund = payment("cash", Decimal("5.00"), PaymentTypeChoices.REFUND)
        payment("card", Decimal("10.00"), PaymentTypeChoices.REFUND)
        with transaction.atomic():
            register_payment_cash_movement(payment=cash_payment)
            register_payment_cash_movement(payment=cash_refund)

        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1440, "height": 900})
            self._login(page, user, "Cash-Payments-123!")
            page.goto(
                f"{self.live_server_url}/cash-register/stores/{store.pk}/sessions/{session.pk}/"
            )
            physical = page.locator(".cash-physical-summary")
            expect(physical).to_contain_text("115,00 €")
            expect(physical).not_to_contain_text("220,00 €")
            cash_method = page.locator(".cash-payment-method").filter(
                has=page.get_by_role("heading", name="Efectivo", exact=True)
            )
            card_method = page.locator(".cash-payment-method").filter(
                has=page.get_by_role("heading", name="Tarjeta", exact=True)
            )
            expect(cash_method).to_contain_text("20,00 €")
            expect(cash_method).to_contain_text("5,00 €")
            expect(cash_method).to_contain_text("15,00 €")
            expect(card_method).to_contain_text("100,00 €")
            expect(card_method).to_contain_text("10,00 €")
            expect(card_method).to_contain_text("90,00 €")
            browser.close()

        session.refresh_from_db()
        self.assertEqual(session.expected_cash_amount, Decimal("115.00"))
        self.assertEqual(CashMovement.objects.filter(cash_session=session).count(), 2)
