from django.test import TestCase
from django.urls import reverse

from apps.cash_register.models import CashSession
from apps.cash_register.test_factories import (
    create_cash_business,
    create_cash_register,
    create_cash_store,
)
from apps.users.models import RoleChoices
from apps.users.tests.factories import create_user


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
