from django.test import Client, RequestFactory, TestCase
from django.urls import reverse

from apps.core.context_processors import app_shell
from apps.core.shell import ACTIVE_STORE_SESSION_KEY
from apps.onboarding.services import OnboardingService
from apps.stores.models import Store
from apps.users.models import CustomUser, RoleChoices, UserStoreAccess


class AppShellTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        result = OnboardingService.create_business(
            legal_name="Shell SL",
            trade_name="Shell",
            tax_identifier="B12345670",
            phone="923000000",
            email="shell-business@example.com",
            address_line_1="Calle Shell 1",
            postal_code="37001",
            city="Salamanca",
            province="Salamanca",
            country_code="ES",
            store_name="Principal",
            owner_first_name="Shell",
            owner_last_name="Owner",
            owner_email="shell-owner@example.com",
            owner_phone="600000010",
            owner_password="Safe-Shell-Password-123!",
            owner_pin="1234",
        )
        cls.business = result.business
        cls.owner = result.owner
        cls.default_store = result.store
        cls.other_store = Store.objects.create(
            business=cls.business, name="Secundaria", code="SECOND"
        )
        cls.manager = CustomUser.objects.create_user(
            email="shell-manager@example.com",
            password="Safe-Shell-Password-123!",
            business=cls.business,
            role=RoleChoices.MANAGER,
        )
        cls.cashier = CustomUser.objects.create_user(
            email="shell-cashier@example.com",
            password="Safe-Shell-Password-123!",
            business=cls.business,
            role=RoleChoices.CASHIER,
        )
        for user in (cls.manager, cls.cashier):
            UserStoreAccess.objects.create(
                business=cls.business,
                user=user,
                store=cls.default_store,
                can_sell=user == cls.cashier,
            )

    def setUp(self):
        self.client.force_login(self.owner)

    def test_context_processor_tolerates_request_without_user_or_session(self):
        request = RequestFactory().get("/bad-request")

        self.assertEqual(app_shell(request), {})

    def test_default_fallback_and_valid_session(self):
        response = self.client.get(reverse("core:home"))
        self.assertEqual(response.context["active_store"], self.default_store)
        self.assertEqual(
            self.client.session[ACTIVE_STORE_SESSION_KEY], self.default_store.pk
        )
        session = self.client.session
        session[ACTIVE_STORE_SESSION_KEY] = self.other_store.pk
        session.save()
        response = self.client.get(reverse("core:home"))
        self.assertEqual(response.context["active_store"], self.other_store)

    def test_invalid_or_inactive_session_falls_back(self):
        session = self.client.session
        session[ACTIVE_STORE_SESSION_KEY] = 999999
        session.save()
        self.client.get(reverse("core:home"))
        self.assertEqual(
            self.client.session[ACTIVE_STORE_SESSION_KEY], self.default_store.pk
        )
        self.other_store.is_active = False
        self.other_store.save()
        session = self.client.session
        session[ACTIVE_STORE_SESSION_KEY] = self.other_store.pk
        session.save()
        response = self.client.get(reverse("core:home"))
        self.assertEqual(response.context["active_store"], self.default_store)

    def test_first_accessible_store_fallback_without_default(self):
        UserStoreAccess.objects.filter(
            user=self.manager, store=self.default_store
        ).update(is_active=False)
        UserStoreAccess.objects.create(
            business=self.business,
            user=self.manager,
            store=self.other_store,
            is_active=True,
        )
        self.client.force_login(self.manager)
        response = self.client.get(reverse("core:home"))
        self.assertEqual(response.context["active_store"], self.other_store)

    def test_switch_is_post_login_protected_and_does_not_change_default(self):
        url = reverse("stores:store_set_active", args=[self.other_store.pk])
        anonymous = Client()
        self.assertEqual(anonymous.post(url).status_code, 302)
        self.assertEqual(self.client.get(url).status_code, 405)
        self.assertEqual(self.client.post(url).status_code, 302)
        self.assertEqual(
            self.client.session[ACTIVE_STORE_SESSION_KEY], self.other_store.pk
        )
        self.default_store.refresh_from_db()
        self.other_store.refresh_from_db()
        self.assertTrue(self.default_store.is_default)
        self.assertFalse(self.other_store.is_default)

    def test_switch_rejects_unavailable_store_and_open_redirect(self):
        other = OnboardingService.create_business(
            legal_name="Other SL",
            tax_identifier="B12345671",
            phone="923000001",
            email="other-business@example.com",
            address_line_1="Calle Other 1",
            postal_code="37002",
            city="Salamanca",
            province="Salamanca",
            store_name="Ajena",
            owner_first_name="Other",
            owner_last_name="Owner",
            owner_email="other-owner@example.com",
            owner_phone="600000011",
            owner_password="Safe-Shell-Password-123!",
            owner_pin="4321",
        )
        self.assertEqual(
            self.client.post(
                reverse("stores:store_set_active", args=[other.store.pk])
            ).status_code,
            404,
        )
        response = self.client.post(
            reverse("stores:store_set_active", args=[self.other_store.pk]),
            {"next": "https://evil.example/steal"},
        )
        self.assertEqual(response.url, reverse("core:home"))

    def test_switch_rebuilds_store_scoped_redirect_for_new_store(self):
        response = self.client.post(
            reverse("stores:store_set_active", args=[self.other_store.pk]),
            {"next": reverse("sales:sale_list", args=[self.default_store.pk])},
        )
        self.assertEqual(
            response.url, reverse("sales:sale_list", args=[self.other_store.pk])
        )

    def test_switch_preserves_local_query_string(self):
        next_url = f"{reverse('customers:customer_list')}?q=ana&status=active"
        response = self.client.post(
            reverse("stores:store_set_active", args=[self.other_store.pk]),
            {"next": next_url},
        )
        self.assertEqual(response.url, next_url)

    def test_switch_from_payment_uses_new_store_sales_root(self):
        old_payment_url = reverse(
            "payments:create",
            kwargs={"store_id": self.default_store.pk, "sale_id": 123},
        )
        response = self.client.post(
            reverse("stores:store_set_active", args=[self.other_store.pk]),
            {"next": old_payment_url},
        )
        self.assertEqual(
            response.url, reverse("sales:sale_list", args=[self.other_store.pk])
        )
        self.assertNotIn(f"/stores/{self.default_store.pk}/", response.url)

    def test_authorized_store_id_in_url_synchronizes_active_store(self):
        session = self.client.session
        session[ACTIVE_STORE_SESSION_KEY] = self.default_store.pk
        session.save()
        response = self.client.get(
            reverse("sales:sale_list", args=[self.other_store.pk])
        )
        self.assertEqual(response.context["active_store"], self.other_store)
        self.assertEqual(
            self.client.session[ACTIVE_STORE_SESSION_KEY], self.other_store.pk
        )

    def test_unauthorized_store_id_in_url_does_not_synchronize(self):
        self.client.force_login(self.cashier)
        UserStoreAccess.objects.create(
            business=self.business,
            user=self.cashier,
            store=self.other_store,
            is_active=True,
        )
        unauthorized_store = Store.objects.create(
            business=self.business,
            name="Sin acceso",
            code="NO-ACCESS",
        )
        session = self.client.session
        session[ACTIVE_STORE_SESSION_KEY] = self.other_store.pk
        session.save()
        response = self.client.get(
            reverse("sales:sale_list", args=[unauthorized_store.pk])
        )
        self.assertIn(response.status_code, {403, 404})
        self.assertEqual(
            self.client.session[ACTIVE_STORE_SESSION_KEY], self.other_store.pk
        )

    def test_superuser_with_business_is_tenant_limited_in_shell_and_switch(self):
        other = OnboardingService.create_business(
            legal_name="Isolated SL",
            tax_identifier="B12345672",
            phone="923000002",
            email="isolated-business@example.com",
            address_line_1="Calle Isolated 1",
            postal_code="37003",
            city="Salamanca",
            province="Salamanca",
            store_name="Tienda ajena",
            owner_first_name="Isolated",
            owner_last_name="Owner",
            owner_email="isolated-owner@example.com",
            owner_phone="600000012",
            owner_password="Safe-Shell-Password-123!",
            owner_pin="5678",
        )
        superuser = CustomUser.objects.create_superuser(
            email="tenant-superuser@example.com",
            password="Safe-Shell-Password-123!",
            business=self.business,
            role=RoleChoices.OWNER,
        )
        self.client.force_login(superuser)
        response = self.client.get(reverse("core:home"))
        self.assertIn(self.default_store, response.context["shell_stores"])
        self.assertNotIn(other.store, response.context["shell_stores"])
        response = self.client.post(
            reverse("stores:store_set_active", args=[other.store.pk])
        )
        self.assertEqual(response.status_code, 404)

    def test_store_scoped_links_palette_and_shell_are_rendered(self):
        response = self.client.get(reverse("core:home"))
        content = response.content.decode()
        self.assertContains(response, "data-command-dialog")
        self.assertContains(response, "data-store-dialog")
        self.assertContains(response, "user-menu")
        self.assertIn(reverse("sales:sale_list", args=[self.default_store.pk]), content)
        self.assertIn(
            reverse("cash_register:register_list", args=[self.default_store.pk]),
            content,
        )
        self.assertIn(
            reverse("billing:document_list", args=[self.default_store.pk]), content
        )
        self.assertNotIn("Informes", content)
        self.assertNotIn("Actividad", content)

    def test_cashier_navigation_omits_administration_and_sale_permission_rules(self):
        self.client.force_login(self.cashier)
        response = self.client.get(reverse("core:home"))
        labels = [
            item["label"]
            for group in response.context["shell_navigation"]
            for item in group["items"]
        ]
        self.assertNotIn("Usuarios", labels)
        self.assertNotIn("Tiendas", labels)
        self.assertIn("Nueva venta", response.content.decode())
        access = UserStoreAccess.objects.get(user=self.cashier)
        access.can_sell = False
        access.save()
        response = self.client.get(reverse("core:home"))
        actions = [item["label"] for item in response.context["shell_quick_actions"]]
        self.assertNotIn("Nueva venta", actions)

    def test_unauthorized_or_revoked_session_store_is_not_reused(self):
        self.client.force_login(self.cashier)
        session = self.client.session
        session[ACTIVE_STORE_SESSION_KEY] = self.other_store.pk
        session.save()
        response = self.client.get(reverse("core:home"))
        self.assertEqual(response.context["active_store"], self.default_store)

        access = UserStoreAccess.objects.get(
            user=self.cashier, store=self.default_store
        )
        access.is_active = False
        access.save()
        response = self.client.get(reverse("core:home"))
        self.assertIsNone(response.context["active_store"])
        self.assertNotIn(ACTIVE_STORE_SESSION_KEY, self.client.session)

    def test_manager_sees_authorized_administration_and_actions(self):
        self.client.force_login(self.manager)
        response = self.client.get(reverse("core:home"))
        labels = [
            item["label"]
            for group in response.context["shell_navigation"]
            for item in group["items"]
        ]
        self.assertIn("Tiendas", labels)
        self.assertIn("Usuarios", labels)
        self.assertNotIn("Configuración", labels)
        actions = [item["label"] for item in response.context["shell_quick_actions"]]
        self.assertIn("Nueva compra", actions)
        self.assertIn("Nuevo producto", actions)

    def test_profile_does_not_activate_users_module(self):
        response = self.client.get(reverse("users:profile"))
        users = next(
            item
            for group in response.context["shell_navigation"]
            for item in group["items"]
            if item["id"] == "users"
        )
        self.assertFalse(users["active"])

    def test_csrf_is_enforced_by_normal_middleware(self):
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(self.owner)
        response = csrf_client.post(
            reverse("stores:store_set_active", args=[self.other_store.pk])
        )
        self.assertEqual(response.status_code, 403)
