from django.contrib.messages import constants
from django.contrib.messages.storage.base import Message
from django.template.loader import render_to_string
from django.test import TestCase
from django.urls import reverse

from apps.users.models import CustomUser, RoleChoices
from apps.users.tests.factories import create_business, create_user


class AppShellIntegrationTests(TestCase):
    password = "testpass123"

    @classmethod
    def setUpTestData(cls):
        cls.business = create_business(name="Shell Business", slug="shell-business")
        cls.owner = create_user(
            cls.business,
            email="owner@shell.test",
            password=cls.password,
            role=RoleChoices.OWNER,
        )
        cls.manager = create_user(
            cls.business,
            email="manager@shell.test",
            password=cls.password,
            role=RoleChoices.MANAGER,
        )
        cls.cashier = create_user(
            cls.business,
            email="cashier@shell.test",
            password=cls.password,
            role=RoleChoices.CASHIER,
        )

    def test_login_uses_public_layout_without_erp_sidebar(self):
        response = self.client.get(reverse("users:login"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Iniciar sesión")
        self.assertNotContains(response, 'id="app-sidebar"')
        self.assertContains(
            response,
            '<a class="skip-link" href="#main-content">Saltar al contenido principal</a>',
            html=True,
        )
        self.assertContains(response, '<main id="main-content"', count=1)

    def test_owner_sees_complete_business_navigation(self):
        self.client.force_login(self.owner)
        response = self.client.get(reverse("core:home"))

        for label in (
            "Inicio",
            "Tiendas",
            "Productos",
            "Inventario",
            "Clientes",
            "Usuarios",
            "Configuración",
            "Mi perfil",
        ):
            self.assertContains(response, label)
        self.assertContains(response, 'id="app-sidebar"')

    def test_manager_sees_user_management_but_not_owner_configuration(self):
        self.client.force_login(self.manager)
        response = self.client.get(reverse("core:home"))

        self.assertContains(response, f'href="{reverse("users:user_list")}"')
        self.assertNotContains(response, f'href="{reverse("business_config:profile")}"')

    def test_cashier_does_not_see_management_navigation(self):
        self.client.force_login(self.cashier)
        response = self.client.get(reverse("core:home"))

        self.assertNotContains(response, f'href="{reverse("users:user_list")}"')
        self.assertNotContains(response, f'href="{reverse("business_config:profile")}"')

    def test_superuser_without_business_sees_admin_navigation(self):
        superuser = CustomUser.objects.create_superuser(
            email="admin@shell.test",
            password=self.password,
            role=RoleChoices.OWNER,
            first_name="Admin",
            last_name="Shell",
            phone="600000000",
        )
        self.client.force_login(superuser)

        response = self.client.get(reverse("core:home"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, f'href="{reverse("admin:index")}"')
        self.assertContains(response, 'id="app-sidebar"')

    def test_logout_remains_post_only(self):
        self.client.force_login(self.owner)
        logout_url = reverse("users:logout")

        self.assertEqual(self.client.get(logout_url).status_code, 405)
        response = self.client.post(logout_url)
        self.assertRedirects(response, reverse("users:login"))

    def test_catalog_page_renders_inside_shell(self):
        self.client.force_login(self.owner)

        response = self.client.get(reverse("catalog:dashboard"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'id="app-sidebar"')
        active_items = [
            item
            for group in response.context["shell_navigation"]
            for item in group["items"]
            if item["active"]
        ]
        self.assertEqual([item["id"] for item in active_items], ["products"])

    def test_authenticated_shell_has_one_main_and_skip_link(self):
        self.client.force_login(self.owner)

        response = self.client.get(reverse("core:home"))

        self.assertContains(response, '<main id="main-content"', count=1)
        self.assertContains(response, 'class="skip-link" href="#main-content"')
        self.assertContains(response, 'aria-current="page"', count=1)
        active_items = [
            item
            for group in response.context["shell_navigation"]
            for item in group["items"]
            if item["active"]
        ]
        self.assertEqual([item["id"] for item in active_items], ["home"])

    def test_messages_expose_appropriate_live_region_roles(self):
        html = render_to_string(
            "includes/messages.html",
            {
                "messages": [
                    Message(constants.SUCCESS, "Operación completada."),
                    Message(constants.ERROR, "No se pudo completar."),
                ]
            },
        )

        self.assertIn('class="message message-success" role="status"', html)
        self.assertIn('class="message message-error" role="alert"', html)
        self.assertNotIn("aria-live", html)
