from django.test import TestCase
from django.urls import reverse

from apps.users.models import CustomUser, RoleChoices
from apps.users.tests.factories import (
    create_business,
    create_store,
    create_store_access,
    create_user,
)


class HomeViewTests(TestCase):
    password = "testpass123"

    @classmethod
    def setUpTestData(cls):
        cls.business = create_business(name="Empresa A", slug="empresa-a")
        cls.other_business = create_business(name="Empresa B", slug="empresa-b")
        cls.active_store = create_store(cls.business, name="Tienda A1", code="A1")
        cls.second_store = create_store(cls.business, name="Tienda A2", code="A2")
        cls.inactive_store = create_store(
            cls.business, name="Tienda A3 inactiva", code="A3", is_active=False
        )
        cls.other_store = create_store(cls.other_business, name="Tienda B1", code="B1")
        cls.owner = create_user(
            cls.business,
            email="owner@home.test",
            password=cls.password,
            role=RoleChoices.OWNER,
        )
        cls.manager = create_user(
            cls.business,
            email="manager@home.test",
            password=cls.password,
            role=RoleChoices.MANAGER,
        )
        cls.cashier = create_user(
            cls.business,
            email="cashier@home.test",
            password=cls.password,
            role=RoleChoices.CASHIER,
        )
        create_store_access(cls.business, cls.manager, cls.active_store, is_active=True)
        create_store_access(cls.business, cls.cashier, cls.active_store, is_active=True)
        create_store_access(
            cls.business, cls.cashier, cls.second_store, is_active=False
        )
        create_store_access(
            cls.business, cls.manager, cls.inactive_store, is_active=True
        )

    def test_root_reverse_and_anonymous_redirect(self):
        url = reverse("core:home")
        self.assertEqual(url, "/")
        response = self.client.get(url)
        self.assertRedirects(
            response,
            f"{reverse('users:login')}?next=/",
            fetch_redirect_response=False,
        )

    def test_login_without_next_uses_home_and_valid_next_is_preserved(self):
        response = self.client.post(
            reverse("users:login"),
            {"username": self.owner.email, "password": self.password},
        )
        self.assertRedirects(response, reverse("core:home"))

        self.client.logout()
        inventory_url = reverse("inventory:dashboard")
        response = self.client.post(
            f"{reverse('users:login')}?next={inventory_url}",
            {
                "username": self.owner.email,
                "password": self.password,
                "next": inventory_url,
            },
        )
        self.assertRedirects(response, inventory_url)

    def test_external_next_falls_back_to_home(self):
        response = self.client.post(
            f"{reverse('users:login')}?next=https://attacker.example/",
            {
                "username": self.owner.email,
                "password": self.password,
                "next": "https://attacker.example/",
            },
        )
        self.assertRedirects(response, reverse("core:home"))

    def test_owner_sees_only_active_stores_in_own_business_and_operation_links(self):
        self.client.force_login(self.owner)
        response = self.client.get(reverse("core:home"))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "core/home.html")
        self.assertContains(response, self.business.name)
        self.assertContains(response, self.active_store.name)
        self.assertContains(response, self.second_store.name)
        self.assertNotContains(response, self.inactive_store.name)
        self.assertNotContains(response, self.other_store.name)
        for url in (
            reverse("sales:sale_list", kwargs={"store_id": self.active_store.pk}),
            reverse(
                "cash_register:register_list",
                kwargs={"store_id": self.active_store.pk},
            ),
            reverse(
                "billing:document_list",
                kwargs={"store_id": self.active_store.pk},
            ),
            reverse("stores:store_detail", kwargs={"pk": self.active_store.pk}),
        ):
            self.assertContains(response, url)

    def test_manager_and_cashier_only_see_active_authorized_stores(self):
        for user in (self.manager, self.cashier):
            with self.subTest(role=user.role):
                self.client.force_login(user)
                response = self.client.get(reverse("core:home"))
                self.assertContains(response, self.active_store.name)
                self.assertNotContains(response, self.second_store.name)
                self.assertNotContains(response, self.inactive_store.name)
                self.assertNotContains(response, self.other_store.name)
                self.client.logout()

    def test_role_aware_navigation(self):
        expectations = (
            (self.owner, True, True),
            (self.manager, True, False),
            (self.cashier, False, False),
        )
        for user, has_users, has_config in expectations:
            with self.subTest(role=user.role):
                self.client.force_login(user)
                response = self.client.get(reverse("core:home"))
                assertion = self.assertContains if has_users else self.assertNotContains
                assertion(response, f'href="{reverse("users:user_list")}"')
                assertion = (
                    self.assertContains if has_config else self.assertNotContains
                )
                assertion(
                    response,
                    f'href="{reverse("business_config:profile")}"',
                )
                self.client.logout()

    def test_user_without_operational_stores_still_gets_home(self):
        manager = create_user(
            self.business,
            email="unassigned@home.test",
            password=self.password,
            role=RoleChoices.MANAGER,
        )
        self.client.force_login(manager)
        response = self.client.get(reverse("core:home"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "No tienes tiendas operativas asignadas.")

    def test_normal_user_without_business_gets_forbidden(self):
        user = create_user(
            self.business,
            email="orphan@home.test",
            password=self.password,
            role=RoleChoices.CASHIER,
        )
        CustomUser.objects.filter(pk=user.pk).update(business=None)
        user.refresh_from_db()
        self.client.force_login(user)
        self.assertEqual(self.client.get(reverse("core:home")).status_code, 403)

    def test_superuser_without_business_gets_admin_home_without_tenant_data(self):
        superuser = CustomUser.objects.create_superuser(
            email="admin@home.test",
            password=self.password,
            role=RoleChoices.OWNER,
            first_name="Admin",
            last_name="User",
            phone="600000000",
        )
        self.client.force_login(superuser)
        response = self.client.get(reverse("core:home"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Administración")
        self.assertContains(response, reverse("admin:index"))
        self.assertNotContains(response, self.active_store.name)
        self.assertNotContains(response, self.other_store.name)
        self.assertNotContains(response, f'href="{reverse("users:user_list")}"')

    def test_superuser_with_business_is_limited_to_that_business(self):
        superuser = CustomUser.objects.create_superuser(
            email="tenant-admin@home.test",
            password=self.password,
            business=self.business,
            role=RoleChoices.OWNER,
            first_name="Admin",
            last_name="Tenant",
            phone="600000000",
        )
        self.client.force_login(superuser)
        response = self.client.get(reverse("core:home"))
        self.assertContains(response, self.active_store.name)
        self.assertContains(response, self.second_store.name)
        self.assertNotContains(response, self.other_store.name)
