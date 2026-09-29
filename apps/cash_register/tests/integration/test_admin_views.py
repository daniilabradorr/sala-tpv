from django.test import TestCase
from django.urls import reverse

from apps.cash_register.models import CashRegister
from apps.cash_register.test_factories import create_cash_business, create_cash_store
from apps.users.models import RoleChoices
from apps.users.tests.factories import create_user


class CashRegisterAdminViewTests(TestCase):
    def setUp(self):
        self.business = create_cash_business()
        self.store = create_cash_store(business=self.business)
        self.owner = create_user(
            business=self.business,
            email="register-owner@test.com",
            role=RoleChoices.OWNER,
        )
        self.manager = create_user(
            business=self.business,
            email="register-manager@test.com",
            role=RoleChoices.MANAGER,
        )
        self.cashier = create_user(
            business=self.business,
            email="register-cashier@test.com",
            role=RoleChoices.CASHIER,
        )

    def test_owner_can_create_edit_deactivate_and_activate(self):
        self.client.force_login(self.owner)
        url = reverse(
            "cash_register:register_create", kwargs={"store_id": self.store.pk}
        )
        response = self.client.post(url, {"name": "Secundaria", "code": "caja-02"})
        register = CashRegister.objects.get(store=self.store, code="CAJA-02")
        self.assertRedirects(
            response,
            reverse("cash_register:register_admin", kwargs={"store_id": self.store.pk}),
            fetch_redirect_response=False,
        )
        self.client.post(
            reverse(
                "cash_register:register_update",
                kwargs={"store_id": self.store.pk, "cash_register_id": register.pk},
            ),
            {"name": "Mostrador", "code": "CAJA-03"},
        )
        self.client.post(
            reverse(
                "cash_register:register_deactivate",
                kwargs={"store_id": self.store.pk, "cash_register_id": register.pk},
            )
        )
        register.refresh_from_db()
        self.assertFalse(register.is_active)
        self.client.post(
            reverse(
                "cash_register:register_activate",
                kwargs={"store_id": self.store.pk, "cash_register_id": register.pk},
            )
        )
        register.refresh_from_db()
        self.assertTrue(register.is_active)
        self.assertEqual(register.name, "Mostrador")

    def test_manager_without_store_access_can_admin_but_cashier_cannot(self):
        url = reverse(
            "cash_register:register_admin", kwargs={"store_id": self.store.pk}
        )
        self.client.force_login(self.manager)
        self.assertEqual(self.client.get(url).status_code, 200)
        self.client.force_login(self.cashier)
        self.assertEqual(self.client.get(url).status_code, 403)

    def test_cross_tenant_store_is_not_visible(self):
        other_business = create_cash_business(
            name="Other business", slug="other-business"
        )
        other_store = create_cash_store(
            business=other_business, name="Other", code="OTHER"
        )
        self.client.force_login(self.owner)
        self.assertEqual(
            self.client.get(
                reverse(
                    "cash_register:register_admin", kwargs={"store_id": other_store.pk}
                )
            ).status_code,
            404,
        )
