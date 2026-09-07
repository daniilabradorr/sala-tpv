from django.test import Client, RequestFactory, TestCase, override_settings
from django.urls import reverse
from django.views.defaults import bad_request, server_error

from apps.users.models import RoleChoices
from apps.users.tests.factories import create_business, create_user


@override_settings(DEBUG=False)
class HttpContractTests(TestCase):
    password = "testpass123"

    def setUp(self):
        self.business = create_business(name="Negocio HTTP", slug="negocio-http")
        self.other_business = create_business(
            name="Otro negocio HTTP", slug="otro-negocio-http"
        )
        self.owner = create_user(
            business=self.business,
            email="http-owner@example.com",
            password=self.password,
            role=RoleChoices.OWNER,
        )
        self.cashier = create_user(
            business=self.business,
            email="http-cashier@example.com",
            password=self.password,
            role=RoleChoices.CASHIER,
        )
        self.other_user = create_user(
            business=self.other_business,
            email="other-http-user@example.com",
            password=self.password,
            role=RoleChoices.CASHIER,
        )

    def test_anonymous_protected_views_redirect_to_login_with_next(self):
        for view_name in ("inventory:dashboard", "users:profile"):
            with self.subTest(view_name=view_name):
                protected_url = reverse(view_name)
                response = self.client.get(protected_url)

                self.assertRedirects(
                    response,
                    f"{reverse('users:login')}?next={protected_url}",
                    fetch_redirect_response=False,
                )

    def test_login_preserves_safe_next_destination(self):
        protected_url = reverse("inventory:dashboard")
        redirect_response = self.client.get(protected_url)

        response = self.client.post(
            redirect_response.url,
            {
                "username": self.owner.email,
                "password": self.password,
                "next": protected_url,
            },
        )

        self.assertRedirects(response, protected_url, fetch_redirect_response=False)

    def test_login_rejects_external_next_destination(self):
        response = self.client.post(
            f"{reverse('users:login')}?next=https://attacker.example/",
            {
                "username": self.owner.email,
                "password": self.password,
                "next": "https://attacker.example/",
            },
        )

        self.assertRedirects(
            response, reverse("users:profile"), fetch_redirect_response=False
        )

    def test_direct_login_redirects_to_profile(self):
        response = self.client.post(
            reverse("users:login"),
            {"username": self.owner.email, "password": self.password},
        )

        self.assertRedirects(
            response, reverse("users:profile"), fetch_redirect_response=False
        )

    def test_authenticated_user_is_redirected_away_from_login(self):
        self.client.force_login(self.owner)

        response = self.client.get(reverse("users:login"))

        self.assertRedirects(
            response, reverse("users:profile"), fetch_redirect_response=False
        )

    def test_authenticated_user_without_permission_gets_generic_403(self):
        self.client.force_login(self.cashier)

        response = self.client.get(reverse("users:user_list"))

        self.assertEqual(response.status_code, 403)
        self.assertTemplateUsed(response, "403.html")
        self.assertContains(response, "Acceso denegado", status_code=403)
        self.assertNotIn(reverse("users:login"), response.headers.get("Location", ""))
        self.assertNotContains(
            response,
            "Solo owner o manager pueden acceder a esta página.",
            status_code=403,
        )

    def test_unknown_url_uses_generic_404(self):
        response = self.client.get("/ruta-que-no-existe/")

        self.assertEqual(response.status_code, 404)
        self.assertTemplateUsed(response, "404.html")
        self.assertContains(
            response, "No hemos encontrado esta página o recurso.", status_code=404
        )

    def test_tenant_hidden_user_uses_generic_404(self):
        self.client.force_login(self.owner)

        response = self.client.get(
            reverse("users:user_detail", kwargs={"pk": self.other_user.pk})
        )

        self.assertEqual(response.status_code, 404)
        self.assertTemplateUsed(response, "404.html")
        self.assertNotContains(response, self.other_business.name, status_code=404)

    def test_csrf_failure_uses_generic_403_without_reason(self):
        csrf_client = Client(enforce_csrf_checks=True)

        response = csrf_client.post(
            reverse("users:login"),
            {"username": self.owner.email, "password": self.password},
        )

        self.assertEqual(response.status_code, 403)
        self.assertTemplateUsed(response, "403.html")
        self.assertNotContains(response, "CSRF", status_code=403)

    def test_bad_request_handler_uses_generic_400(self):
        request = RequestFactory().get("/")

        with self.assertTemplateUsed("400.html"):
            response = bad_request(request, Exception("detalle interno"))

        self.assertEqual(response.status_code, 400)
        self.assertNotContains(response, "detalle interno", status_code=400)

    def test_server_error_handler_uses_safe_generic_500(self):
        request = RequestFactory().get("/")

        with self.assertTemplateUsed("500.html"):
            response = server_error(request)

        self.assertEqual(response.status_code, 500)
        body = response.content.decode()
        for sensitive_text in (
            "Traceback",
            "SECRET_KEY",
            "DATABASE_URL",
            "Internal Server Error",
            "excepción artificial",
        ):
            with self.subTest(sensitive_text=sensitive_text):
                self.assertNotIn(sensitive_text, body)
