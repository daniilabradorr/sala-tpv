import json

from django.core import signing
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.cash_register.models import CashCount, CashSession
from apps.cash_register.test_factories import (
    create_cash_business,
    create_cash_register,
    create_cash_store,
)
from apps.users.models import RoleChoices
from apps.users.tests.factories import create_user
from apps.sales.models import RequestedDocumentTypeChoices, Sale
from apps.sales.tests.factories import create_pos_settings, create_sale


class CashRegisterSessionViewIsolationTests(TestCase):
    def setUp(self):
        self.business = create_cash_business()
        self.store = create_cash_store(business=self.business)
        self.user = create_user(
            business=self.business,
            email="cash-view-owner@test.com",
            role=RoleChoices.OWNER,
        )
        self.client.force_login(self.user)

    def detail_url(self, *, store_id, session_id):
        return reverse(
            "cash_register:session_detail",
            kwargs={"store_id": store_id, "session_id": session_id},
        )

    def test_missing_session_returns_404(self):
        response = self.client.get(
            self.detail_url(store_id=self.store.pk, session_id=999999)
        )
        self.assertEqual(response.status_code, 404)
        action_response = self.client.post(
            reverse(
                "cash_register:cash_in",
                kwargs={"store_id": self.store.pk, "session_id": 999999},
            ),
            {"amount": "10.00"},
        )
        self.assertEqual(action_response.status_code, 404)

    def test_session_from_other_business_returns_404(self):
        other_business = create_cash_business()
        other_store = create_cash_store(business=other_business)
        other_user = create_user(
            business=other_business, email="cash-view-other@test.com"
        )
        register = create_cash_register(
            business=other_business, store=other_store, code="OTHER"
        )
        session = CashSession.objects.create(
            business=other_business,
            store=other_store,
            cash_register=register,
            opened_by=other_user,
        )
        response = self.client.get(
            self.detail_url(store_id=self.store.pk, session_id=session.pk)
        )
        self.assertEqual(response.status_code, 404)

    def test_session_from_other_store_returns_404(self):
        other_store = create_cash_store(business=self.business)
        register = create_cash_register(
            business=self.business, store=other_store, code="OTHER"
        )
        session = CashSession.objects.create(
            business=self.business,
            store=other_store,
            cash_register=register,
            opened_by=self.user,
        )
        response = self.client.get(
            self.detail_url(store_id=self.store.pk, session_id=session.pk)
        )
        self.assertEqual(response.status_code, 404)

    def test_register_list_shows_open_and_closed_actions(self):
        closed_register = create_cash_register(
            business=self.business, store=self.store, name="Caja cerrada", code="CLOSED"
        )
        open_register = create_cash_register(
            business=self.business, store=self.store, name="Caja abierta", code="OPEN"
        )
        session = CashSession.objects.create(
            business=self.business,
            store=self.store,
            cash_register=open_register,
            opened_by=self.user,
        )
        response = self.client.get(
            reverse("cash_register:register_list", kwargs={"store_id": self.store.pk})
        )
        self.assertContains(response, "Caja cerrada")
        self.assertContains(response, "Abrir caja")
        self.assertContains(response, "Caja abierta")
        self.assertContains(response, "Entrar en caja")
        self.assertContains(response, "Esperado")
        self.assertIn(closed_register, list(response.context["cash_registers"]))
        rendered_open_register = next(
            item
            for item in response.context["cash_registers"]
            if item.pk == open_register.pk
        )
        self.assertEqual(
            rendered_open_register.open_sessions[0].expected_cash_amount,
            session.expected_cash_amount,
        )

    def test_session_detail_lists_only_its_sales_and_opened_by(self):
        register = create_cash_register(business=self.business, store=self.store)
        session = CashSession.objects.create(
            business=self.business,
            store=self.store,
            cash_register=register,
            opened_by=self.user,
        )
        included = create_sale(
            business=self.business,
            store=self.store,
            opened_by=self.user,
            cash_register=register,
            cash_session=session,
        )
        other_register = create_cash_register(
            business=self.business, store=self.store, code="OTHER-SALES"
        )
        other_session = CashSession.objects.create(
            business=self.business,
            store=self.store,
            cash_register=other_register,
            opened_by=self.user,
        )
        excluded = create_sale(
            business=self.business,
            store=self.store,
            opened_by=self.user,
            cash_register=other_register,
            cash_session=other_session,
        )
        response = self.client.get(
            self.detail_url(store_id=self.store.pk, session_id=session.pk)
        )
        self.assertContains(response, f"#{included.pk}")
        self.assertContains(response, self.user.email)
        self.assertNotContains(response, f"#{excluded.pk}")

    def test_open_from_register_records_authenticated_user(self):
        register = create_cash_register(business=self.business, store=self.store)
        response = self.client.post(
            reverse(
                "cash_register:register_open",
                kwargs={"store_id": self.store.pk, "cash_register_id": register.pk},
            ),
            {"cash_register": register.pk, "opening_amount": "25.00"},
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            CashSession.objects.get(cash_register=register).opened_by, self.user
        )

    def test_open_hx_success_uses_explicit_navigation_contract(self):
        register = create_cash_register(business=self.business, store=self.store)
        response = self.client.post(
            reverse("cash_register:register_open", args=[self.store.pk, register.pk]),
            {"cash_register": register.pk, "opening_amount": "100.00"},
            HTTP_HX_REQUEST="true",
        )
        session = CashSession.objects.get(cash_register=register)
        self.assertEqual(response.status_code, 204)
        self.assertEqual(
            response["HX-Redirect"],
            self.detail_url(store_id=self.store.pk, session_id=session.pk),
        )
        self.assertIn("HX-Request", response.get("Vary", ""))

    def test_open_hx_invalid_renders_partial_with_422_and_vary(self):
        register = create_cash_register(business=self.business, store=self.store)
        response = self.client.post(
            reverse("cash_register:register_open", args=[self.store.pk, register.pk]),
            {"cash_register": register.pk, "opening_amount": "invalid"},
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(response.status_code, 422)
        self.assertContains(response, "cash-dialog-panel", status_code=422)
        self.assertNotContains(response, "<!DOCTYPE html>", status_code=422)
        self.assertIn("HX-Request", response.get("Vary", ""))

    def test_session_tabs_return_partial_without_shell_and_vary(self):
        register = create_cash_register(business=self.business, store=self.store)
        session = CashSession.objects.create(
            business=self.business,
            store=self.store,
            cash_register=register,
            opened_by=self.user,
        )
        for tab, heading in (
            ("summary", "Resumen del cajón"),
            ("sales", "Ventas del turno"),
            ("movements", "Movimientos de efectivo"),
            ("counts", "Arqueos"),
        ):
            response = self.client.get(
                self.detail_url(store_id=self.store.pk, session_id=session.pk)
                + f"?tab={tab}",
                HTTP_HX_REQUEST="true",
            )
            self.assertContains(response, heading)
            self.assertContains(response, 'id="cash-tab-panel"')
            self.assertNotContains(response, "<!DOCTYPE html>")
            self.assertIn("HX-Request", response.get("Vary", ""))

    def test_cash_in_hx_success_closes_dialog_and_refreshes_tab(self):
        register = create_cash_register(business=self.business, store=self.store)
        session = CashSession.objects.create(
            business=self.business,
            store=self.store,
            cash_register=register,
            opened_by=self.user,
            expected_cash_amount="100.00",
        )
        url = reverse("cash_register:cash_in", args=[self.store.pk, session.pk])
        get_response = self.client.get(url, HTTP_HX_REQUEST="true")
        self.assertContains(get_response, "Entrada de efectivo")
        self.assertIn("HX-Request", get_response.get("Vary", ""))
        response = self.client.post(
            url, {"amount": "50.00", "reason": "Cambio"}, HTTP_HX_REQUEST="true"
        )
        self.assertEqual(response.status_code, 204)
        events = json.loads(response["HX-Trigger"])
        self.assertEqual(events["nx:close-modal"]["id"], "cash-operation-dialog")
        self.assertEqual(events["nx:refresh-region"]["selector"], "#cash-tab-panel")
        session.refresh_from_db()
        self.assertEqual(str(session.expected_cash_amount), "150.00")

    def test_close_prepare_does_not_mutate_and_hx_confirm_redirects(self):
        create_pos_settings(
            business=self.business, require_pin_for_sensitive_actions=False
        )
        register = create_cash_register(business=self.business, store=self.store)
        session = CashSession.objects.create(
            business=self.business,
            store=self.store,
            cash_register=register,
            opened_by=self.user,
            expected_cash_amount="125.00",
        )
        url = reverse("cash_register:close", args=[self.store.pk, session.pk])
        prepare = self.client.post(
            url,
            {"counted_amount": "124.00", "notes": "Fin"},
            HTTP_HX_REQUEST="true",
        )
        session.refresh_from_db()
        self.assertEqual(session.status, CashSession.Status.OPEN)
        self.assertContains(prepare, "Confirmar cierre")
        payload = prepare.context["payload"]
        response = self.client.post(
            url,
            {"step": "confirm", "close_payload": payload},
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(response.status_code, 204)
        self.assertEqual(
            response["HX-Redirect"],
            self.detail_url(store_id=self.store.pk, session_id=session.pk),
        )
        session.refresh_from_db()
        self.assertEqual(session.status, CashSession.Status.CLOSED)
        self.assertEqual(str(session.difference_amount), "-1.00")

    def test_close_invalid_pin_remains_on_confirmation_step(self):
        create_pos_settings(
            business=self.business, require_pin_for_sensitive_actions=True
        )
        self.user.set_pin("1234")
        self.user.save()
        register = create_cash_register(business=self.business, store=self.store)
        session = CashSession.objects.create(
            business=self.business,
            store=self.store,
            cash_register=register,
            opened_by=self.user,
            expected_cash_amount="20.00",
        )
        url = reverse("cash_register:close", args=[self.store.pk, session.pk])
        prepare = self.client.post(url, {"counted_amount": "19.00", "notes": "Control"})
        response = self.client.post(
            url,
            {
                "step": "confirm",
                "close_payload": prepare.context["payload"],
                "pin": "9999",
            },
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(response.status_code, 422)
        self.assertContains(response, "Confirmar cierre", status_code=422)
        self.assertContains(response, "PIN indicado no es válido", status_code=422)
        self.assertContains(response, "19,00 €", status_code=422)
        session.refresh_from_db()
        self.assertEqual(session.status, CashSession.Status.OPEN)

    def test_close_signed_payload_is_bound_to_route_and_user(self):
        create_pos_settings(
            business=self.business, require_pin_for_sensitive_actions=False
        )
        register = create_cash_register(business=self.business, store=self.store)
        session = CashSession.objects.create(
            business=self.business,
            store=self.store,
            cash_register=register,
            opened_by=self.user,
        )
        payload = signing.dumps(
            {
                "counted_amount": "0.00",
                "notes": "",
                "business_id": self.business.pk,
                "store_id": self.store.pk,
                "cash_session_id": session.pk + 1,
                "user_id": self.user.pk,
            },
            salt="cash-close",
        )
        response = self.client.post(
            reverse("cash_register:close", args=[self.store.pk, session.pk]),
            {"step": "confirm", "close_payload": payload},
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(response.status_code, 422)
        self.assertContains(response, "pertenece a otra caja", status_code=422)
        session.refresh_from_db()
        self.assertEqual(session.status, CashSession.Status.OPEN)

    def test_close_conflict_returns_opt_in_swappable_409(self):
        create_pos_settings(
            business=self.business, require_pin_for_sensitive_actions=False
        )
        register = create_cash_register(business=self.business, store=self.store)
        session = CashSession.objects.create(
            business=self.business,
            store=self.store,
            cash_register=register,
            opened_by=self.user,
        )
        url = reverse("cash_register:close", args=[self.store.pk, session.pk])
        prepare = self.client.post(url, {"counted_amount": "0.00", "notes": ""})
        session.status = CashSession.Status.CLOSED
        session.closed_at = timezone.now()
        session.closed_by = self.user
        session.counted_cash_amount = "0.00"
        session.save()
        response = self.client.post(
            url,
            {"step": "confirm", "close_payload": prepare.context["payload"]},
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response["X-Netxodo-Allow-Error-Swap"], "true")
        self.assertContains(response, "Esta caja ya ha sido cerrada.", status_code=409)
        self.assertContains(
            response,
            "Otro usuario completó la operación antes que tú.",
            status_code=409,
        )

    def test_contextual_register_open_rejects_manipulated_register(self):
        register_a = create_cash_register(business=self.business, store=self.store)
        register_b = create_cash_register(business=self.business, store=self.store)
        response = self.client.post(
            reverse(
                "cash_register:register_open",
                kwargs={
                    "store_id": self.store.pk,
                    "cash_register_id": register_a.pk,
                },
            ),
            {"cash_register": register_b.pk, "opening_amount": "25.00"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.context["form"].errors.as_data()["cash_register"][0].code,
            "invalid_choice",
        )
        self.assertFalse(CashSession.objects.filter(cash_register=register_a).exists())
        self.assertFalse(CashSession.objects.filter(cash_register=register_b).exists())

    def test_new_sale_from_session_uses_server_validated_cash_context(self):
        create_pos_settings(business=self.business, require_open_cash_register=True)
        register = create_cash_register(business=self.business, store=self.store)
        session = CashSession.objects.create(
            business=self.business,
            store=self.store,
            cash_register=register,
            opened_by=self.user,
        )
        response = self.client.post(
            reverse(
                "sales:sale_open_for_session",
                kwargs={"store_id": self.store.pk, "session_id": session.pk},
            ),
            {
                "cash_register": register.pk,
                "cash_session": session.pk,
                "document_type_requested": RequestedDocumentTypeChoices.TICKET,
            },
        )
        self.assertEqual(response.status_code, 302)
        sale = Sale.objects.get()
        self.assertEqual(sale.business, self.business)
        self.assertEqual(sale.store, self.store)
        self.assertEqual(sale.cash_register, register)
        self.assertEqual(sale.cash_session, session)
        self.assertEqual(sale.opened_by, self.user)

    def test_contextual_sale_does_not_require_cash_fields_in_post(self):
        create_pos_settings(business=self.business, require_open_cash_register=True)
        register = create_cash_register(business=self.business, store=self.store)
        session = CashSession.objects.create(
            business=self.business,
            store=self.store,
            cash_register=register,
            opened_by=self.user,
        )
        response = self.client.post(
            reverse(
                "sales:sale_open_for_session",
                kwargs={"store_id": self.store.pk, "session_id": session.pk},
            ),
            {"document_type_requested": RequestedDocumentTypeChoices.TICKET},
        )
        self.assertEqual(response.status_code, 302)
        sale = Sale.objects.get()
        self.assertEqual(sale.cash_register, register)
        self.assertEqual(sale.cash_session, session)
        self.assertEqual(sale.opened_by, self.user)

    def test_contextual_sale_rejects_manipulated_cash_context(self):
        create_pos_settings(business=self.business, require_open_cash_register=True)
        register_a = create_cash_register(business=self.business, store=self.store)
        session_a = CashSession.objects.create(
            business=self.business,
            store=self.store,
            cash_register=register_a,
            opened_by=self.user,
        )
        register_b = create_cash_register(business=self.business, store=self.store)
        session_b = CashSession.objects.create(
            business=self.business,
            store=self.store,
            cash_register=register_b,
            opened_by=self.user,
        )
        response = self.client.post(
            reverse(
                "sales:sale_open_for_session",
                kwargs={"store_id": self.store.pk, "session_id": session_a.pk},
            ),
            {
                "cash_register": register_b.pk,
                "cash_session": session_b.pk,
                "document_type_requested": RequestedDocumentTypeChoices.TICKET,
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Sale.objects.exists())

    def test_contextual_sale_keeps_session_when_cash_register_not_required(self):
        create_pos_settings(business=self.business, require_open_cash_register=False)
        register = create_cash_register(business=self.business, store=self.store)
        session = CashSession.objects.create(
            business=self.business,
            store=self.store,
            cash_register=register,
            opened_by=self.user,
        )
        response = self.client.post(
            reverse(
                "sales:sale_open_for_session",
                kwargs={"store_id": self.store.pk, "session_id": session.pk},
            ),
            {"document_type_requested": RequestedDocumentTypeChoices.TICKET},
        )
        self.assertEqual(response.status_code, 302)
        sale = Sale.objects.get()
        self.assertEqual(sale.cash_register, register)
        self.assertEqual(sale.cash_session, session)

    def test_contextual_sale_from_other_store_returns_404(self):
        other_store = create_cash_store(business=self.business)
        register = create_cash_register(business=self.business, store=other_store)
        session = CashSession.objects.create(
            business=self.business,
            store=other_store,
            cash_register=register,
            opened_by=self.user,
        )
        response = self.client.get(
            reverse(
                "sales:sale_open_for_session",
                kwargs={"store_id": self.store.pk, "session_id": session.pk},
            )
        )
        self.assertEqual(response.status_code, 404)

    def test_contextual_sale_from_other_business_returns_404(self):
        other_business = create_cash_business()
        other_store = create_cash_store(business=other_business)
        other_user = create_user(business=other_business, email="other-sale@test.com")
        register = create_cash_register(business=other_business, store=other_store)
        session = CashSession.objects.create(
            business=other_business,
            store=other_store,
            cash_register=register,
            opened_by=other_user,
        )
        response = self.client.get(
            reverse(
                "sales:sale_open_for_session",
                kwargs={"store_id": self.store.pk, "session_id": session.pk},
            )
        )
        self.assertEqual(response.status_code, 404)

    def test_new_sale_from_closed_session_is_rejected(self):
        register = create_cash_register(business=self.business, store=self.store)
        session = CashSession.objects.create(
            business=self.business,
            store=self.store,
            cash_register=register,
            opened_by=self.user,
        )
        session.status = CashSession.Status.CLOSED
        session.closed_at = timezone.now()
        session.closed_by = self.user
        session.counted_cash_amount = session.expected_cash_amount
        session.save()
        response = self.client.get(
            reverse(
                "sales:sale_open_for_session",
                kwargs={"store_id": self.store.pk, "session_id": session.pk},
            )
        )
        self.assertEqual(response.status_code, 403)

    def test_closed_session_is_read_only_and_shows_final_cash(self):
        register = create_cash_register(business=self.business, store=self.store)
        session = CashSession.objects.create(
            business=self.business,
            store=self.store,
            cash_register=register,
            opened_by=self.user,
            opening_amount="25.00",
            expected_cash_amount="25.00",
        )
        session.status = CashSession.Status.CLOSED
        session.closed_at = timezone.now()
        session.closed_by = self.user
        session.counted_cash_amount = "25.00"
        session.save()

        response = self.client.get(
            self.detail_url(store_id=self.store.pk, session_id=session.pk)
        )

        session.refresh_from_db()
        self.assertEqual(session.status, CashSession.Status.CLOSED)
        self.assertContains(response, "✓ CAJA CERRADA")
        self.assertContains(response, "Inicial 25,00 €")
        self.assertContains(response, "Esperado 25,00 €")
        self.assertContains(response, "Contado 25,00 €")
        self.assertContains(response, "Diferencia 0,00 €")
        self.assertContains(response, self.user.email)
        self.assertContains(response, "Vista histórica de solo lectura")
        for action in ("Nueva venta", "Cerrar caja"):
            self.assertNotContains(response, action)
        self.assertNotContains(response, 'class="cash-actions"')
        self.assertNotContains(response, "cash-primary-action")
        for url in (
            reverse("cash_register:cash_in", args=[self.store.pk, session.pk]),
            reverse("cash_register:cash_out", args=[self.store.pk, session.pk]),
            reverse("cash_register:adjustment", args=[self.store.pk, session.pk]),
            reverse("cash_register:review", args=[self.store.pk, session.pk]),
            reverse("cash_register:close", args=[self.store.pk, session.pk]),
        ):
            self.assertNotContains(response, f'href="{url}"')

    def test_session_operation_cancel_returns_to_session_without_javascript(self):
        register = create_cash_register(business=self.business, store=self.store)
        session = CashSession.objects.create(
            business=self.business,
            store=self.store,
            cash_register=register,
            opened_by=self.user,
        )
        response = self.client.get(
            reverse(
                "cash_register:cash_in",
                kwargs={"store_id": self.store.pk, "session_id": session.pk},
            )
        )
        cancel_url = self.detail_url(store_id=self.store.pk, session_id=session.pk)
        self.assertContains(response, f'href="{cancel_url}"')
        self.assertNotContains(response, "javascript:history.back()")

    def test_session_detail_renders_cash_count_operational_fields(self):
        register = create_cash_register(business=self.business, store=self.store)
        session = CashSession.objects.create(
            business=self.business,
            store=self.store,
            cash_register=register,
            opened_by=self.user,
            opening_amount="20.00",
            expected_cash_amount="20.00",
        )
        count = CashCount.objects.create(
            business=self.business,
            store=self.store,
            cash_session=session,
            count_type=CashCount.CountType.REVIEW,
            counted_amount="19.00",
            expected_amount="20.00",
            difference_amount="-1.00",
            counted_by=self.user,
            notes="Arqueo de cambio de turno",
        )

        response = self.client.get(
            self.detail_url(store_id=self.store.pk, session_id=session.pk)
            + "?tab=counts"
        )

        self.assertContains(response, count.get_count_type_display())
        rendered_at = timezone.localtime(count.created_at).strftime("%H:%M")
        self.assertContains(response, rendered_at)
        self.assertContains(response, self.user.email)
        self.assertContains(response, "20,00 €")
        self.assertContains(response, "19,00 €")
        self.assertContains(response, "-1,00 €")
        self.assertContains(response, "Arqueo de cambio de turno")
