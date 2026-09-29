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

    def test_owner_list_and_lifecycle_get_contract(self):
        register = CashRegister.objects.create(
            business=self.business, store=self.store, name="Principal", code="CAJA-01"
        )
        self.client.force_login(self.owner)
        self.assertEqual(
            self.client.get(
                reverse(
                    "cash_register:register_admin",
                    kwargs={"store_id": self.store.pk},
                )
            ).status_code,
            200,
        )
        for route in ("register_activate", "register_deactivate"):
            with self.subTest(route=route):
                response = self.client.get(
                    reverse(
                        f"cash_register:{route}",
                        kwargs={
                            "store_id": self.store.pk,
                            "cash_register_id": register.pk,
                        },
                    )
                )
                self.assertEqual(response.status_code, 405)

    def test_cashier_cannot_access_any_admin_route(self):
        register = CashRegister.objects.create(
            business=self.business, store=self.store, name="Principal", code="CAJA-01"
        )
        self.client.force_login(self.cashier)
        requests = (
            ("get", "register_admin", {"store_id": self.store.pk}, None),
            ("get", "register_create", {"store_id": self.store.pk}, None),
            (
                "get",
                "register_update",
                {"store_id": self.store.pk, "cash_register_id": register.pk},
                None,
            ),
            (
                "post",
                "register_activate",
                {"store_id": self.store.pk, "cash_register_id": register.pk},
                {},
            ),
            (
                "post",
                "register_deactivate",
                {"store_id": self.store.pk, "cash_register_id": register.pk},
                {},
            ),
        )
        for method, route, kwargs, data in requests:
            with self.subTest(route=route):
                response = getattr(self.client, method)(
                    reverse(f"cash_register:{route}", kwargs=kwargs), data=data
                )
                self.assertEqual(response.status_code, 403)

    def test_superuser_without_business_cannot_access_admin(self):
        superuser = create_user(
            business=self.business,
            email="register-superuser@test.com",
            role=RoleChoices.OWNER,
            is_superuser=True,
            is_staff=True,
        )
        superuser.business = None
        superuser.save(update_fields=["business", "updated_at"])
        self.client.force_login(superuser)
        response = self.client.get(
            reverse("cash_register:register_admin", kwargs={"store_id": self.store.pk})
        )
        self.assertEqual(response.status_code, 403)

    def test_cross_tenant_all_admin_routes_are_isolated(self):
        other_business = create_cash_business(
            name="Isolated business", slug="isolated-business"
        )
        other_store = create_cash_store(
            business=other_business, name="Isolated store", code="ISOLATED"
        )
        other_register = CashRegister.objects.create(
            business=other_business,
            store=other_store,
            name="Isolated register",
            code="ISOLATED-01",
        )
        self.client.force_login(self.owner)
        requests = (
            ("get", "register_admin", {"store_id": other_store.pk}, None),
            (
                "post",
                "register_create",
                {"store_id": other_store.pk},
                {"name": "X", "code": "X"},
            ),
            (
                "post",
                "register_update",
                {"store_id": other_store.pk, "cash_register_id": other_register.pk},
                {"name": "X", "code": "X"},
            ),
            (
                "post",
                "register_activate",
                {"store_id": other_store.pk, "cash_register_id": other_register.pk},
                {},
            ),
            (
                "post",
                "register_deactivate",
                {"store_id": other_store.pk, "cash_register_id": other_register.pk},
                {},
            ),
        )
        for method, route, kwargs, data in requests:
            with self.subTest(route=route):
                response = getattr(self.client, method)(
                    reverse(f"cash_register:{route}", kwargs=kwargs), data=data
                )
                self.assertEqual(response.status_code, 404)
        other_register.refresh_from_db()
        self.assertEqual(other_register.name, "Isolated register")
        self.assertTrue(other_register.is_active)

    def test_manipulated_create_and_update_cannot_reassign_context_or_status(self):
        other_business = create_cash_business(name="Manipulated", slug="manipulated")
        other_store = create_cash_store(business=other_business)
        self.client.force_login(self.owner)
        self.client.post(
            reverse(
                "cash_register:register_create", kwargs={"store_id": self.store.pk}
            ),
            {
                "name": "Principal",
                "code": "CAJA-01",
                "business": other_business.pk,
                "store": other_store.pk,
                "is_active": "",
            },
        )
        register = CashRegister.objects.get(code="CAJA-01")
        self.assertEqual(register.business, self.business)
        self.assertEqual(register.store, self.store)
        self.assertTrue(register.is_active)
        self.client.post(
            reverse(
                "cash_register:register_update",
                kwargs={"store_id": self.store.pk, "cash_register_id": register.pk},
            ),
            {
                "name": "Editada",
                "code": "CAJA-02",
                "business": other_business.pk,
                "store": other_store.pk,
                "is_active": "",
            },
        )
        register.refresh_from_db()
        self.assertEqual(register.business, self.business)
        self.assertEqual(register.store, self.store)
        self.assertTrue(register.is_active)
