from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.cash_register.models import CashSession
from apps.cash_register.test_factories import (
    create_cash_business,
    create_cash_register,
    create_cash_store,
)
from apps.users.models import RoleChoices
from apps.users.tests.factories import create_user
from apps.sales.models import RequestedDocumentTypeChoices, Sale
from apps.sales.tests.factories import create_sale


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
        self.assertContains(response, str(session.expected_cash_amount))
        self.assertIn(closed_register, list(response.context["cash_registers"]))

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

    def test_new_sale_from_session_uses_server_validated_cash_context(self):
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
