from urllib.parse import parse_qs, urlsplit

from django.test import Client, TestCase
from django.urls import reverse

from apps.users.models import RoleChoices
from apps.users.tests.factories import create_business, create_user


class LoginProfileContractTests(TestCase):
    def setUp(self):
        self.business = create_business()
        self.user = create_user(
            self.business,
            email="persona@example.com",
            password="Valid-pass-123",
            role=RoleChoices.MANAGER,
        )

    def test_login_is_public_accessible_and_non_enumerating(self):
        response = self.client.get(reverse("users:login"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Bienvenido de nuevo")
        self.assertContains(response, 'autocomplete="username"')
        self.assertContains(response, 'autocomplete="current-password"')
        self.assertNotContains(response, "data-app-shell")

        bodies = []
        for email in (self.user.email, "missing@example.com"):
            response = self.client.post(
                reverse("users:login"),
                {"username": email, "password": "wrong"},
            )
            self.assertContains(
                response, "No hemos podido iniciar sesión con esos datos."
            )
            bodies.append(response.content.decode())
        generic_copy = "No hemos podido iniciar sesión con esos datos."
        self.assertEqual([body.count(generic_copy) for body in bodies], [1, 1])
        for body in bodies:
            for leaked_copy in (
                "usuario inexistente",
                "cuenta no encontrada",
                "contraseña incorrecta",
                "inactive",
                "email registrado",
            ):
                self.assertNotIn(leaked_copy, body.lower())

    def test_next_is_honoured_only_for_local_urls(self):
        profile = reverse("users:profile")
        response = self.client.post(
            reverse("users:login") + f"?next={profile}",
            {
                "username": self.user.email,
                "password": "Valid-pass-123",
                "next": profile,
            },
        )
        self.assertRedirects(response, profile)
        self.client.logout()
        response = self.client.post(
            reverse("users:login") + "?next=https://evil.example/",
            {
                "username": self.user.email,
                "password": "Valid-pass-123",
                "next": "https://evil.example/",
            },
        )
        self.assertNotEqual(urlsplit(response["Location"]).netloc, "evil.example")

    def test_anonymous_htmx_navigation_does_not_claim_session_expired(self):
        response = Client().get(reverse("users:profile"), HTTP_HX_REQUEST="true")
        self.assertEqual(response.status_code, 204)
        query = parse_qs(urlsplit(response["HX-Redirect"]).query)
        self.assertEqual(query["next"], [reverse("users:profile")])
        self.assertNotIn("expired", query)
        login = self.client.get(response["HX-Redirect"])
        self.assertContains(login, "Bienvenido de nuevo")
        self.assertNotContains(login, "Tu sesión ha caducado")
        self.assertNotContains(self.client.get(reverse("users:login")), "ha caducado")

    def test_expired_shell_navigation_has_marker_and_preserves_next(self):
        response = Client().get(
            reverse("users:profile"),
            HTTP_HX_REQUEST="true",
            HTTP_X_NETXODO_AUTHENTICATED_SHELL="1",
        )
        self.assertEqual(response.status_code, 204)
        self.assertEqual(response.content, b"")
        query = parse_qs(urlsplit(response["HX-Redirect"]).query)
        self.assertEqual(query["next"], [reverse("users:profile")])
        self.assertEqual(query["expired"], ["1"])
        self.assertContains(
            self.client.get(response["HX-Redirect"]), "Tu sesión ha caducado"
        )

    def test_profile_heading_uses_real_name_and_email(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse("users:profile"))
        self.assertContains(response, "Test User")
        self.assertContains(response, self.user.email)

        self.user.first_name = ""
        self.user.last_name = ""
        self.user.save()
        response = self.client.get(reverse("users:profile"))
        self.assertContains(response, f"<h2>{self.user.email}</h2>", html=True)

    def test_invalid_forms_link_controls_to_error_text(self):
        login = self.client.post(
            reverse("users:login"),
            {"username": self.user.email, "password": "wrong"},
        )
        self.assertContains(login, 'aria-invalid="true"', count=2)

        self.client.force_login(self.user)
        profile = self.client.post(
            reverse("users:profile_update"),
            {"first_name": "Test", "last_name": "User", "phone": "not-a-phone"},
        )
        self.assertContains(profile, 'aria-invalid="true"')
        self.assertContains(profile, 'aria-describedby="id_phone_error"')
        self.assertContains(profile, 'id="id_phone_error"')

        password = self.client.post(
            reverse("users:password_change"),
            {
                "old_password": "wrong",
                "new_password1": "Different-Password-123!",
                "new_password2": "Different-Password-123!",
            },
        )
        self.assertContains(password, 'aria-invalid="true"')
        self.assertContains(password, "id_old_password_error")

        pin = self.client.post(
            reverse("users:pin_change"),
            {"new_pin": "abc", "new_pin_confirm": "abc"},
        )
        self.assertContains(pin, 'aria-invalid="true"')
        self.assertContains(pin, 'aria-describedby="id_new_pin_error"')
        self.assertContains(pin, 'id="id_new_pin_error"')

    def test_profile_update_ignores_sensitive_fields(self):
        self.client.force_login(self.user)
        other_business = create_business("Otro", "otro")
        response = self.client.post(
            reverse("users:profile_update"),
            {
                "first_name": "Nuevo",
                "last_name": "Nombre",
                "phone": "611223344",
                "email": "attacker@example.com",
                "role": RoleChoices.OWNER,
                "business": other_business.pk,
                "pin_hash": "raw-secret",
            },
        )
        self.assertRedirects(response, reverse("users:profile"))
        self.user.refresh_from_db()
        self.assertEqual(self.user.first_name, "Nuevo")
        self.assertEqual(self.user.email, "persona@example.com")
        self.assertEqual(self.user.role, RoleChoices.MANAGER)
        self.assertEqual(self.user.business, self.business)
        self.assertEqual(self.user.pin_hash, "")

    def test_security_tab_exposes_only_pin_state(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse("users:profile") + "?tab=security")
        self.assertContains(response, "No configurado")
        self.user.set_pin("1234")
        self.user.save()
        response = self.client.get(reverse("users:profile") + "?tab=security")
        self.assertContains(response, "Configurado")
        self.assertNotContains(response, "1234")
        self.assertNotContains(response, self.user.pin_hash)
