from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.test import Client, TestCase
from django.urls import reverse

from apps.billing.models import BillingSeries
from apps.business_config.models import BusinessProfile, POSSettings
from apps.cash_register.models import CashRegister
from apps.catalog.models import Tax
from apps.core.models import Business
from apps.onboarding.services import OnboardingError
from apps.onboarding.tests.test_forms import valid_form_data
from apps.payments.models import PaymentMethod
from apps.stores.models import Store
from apps.users.models import CustomUser, RoleChoices
from apps.users.tests.factories import create_business, create_user


class OnboardingViewTests(TestCase):
    def assert_no_provisioning(self):
        for model in (
            Business,
            BusinessProfile,
            POSSettings,
            Tax,
            Store,
            CustomUser,
            CashRegister,
            PaymentMethod,
            BillingSeries,
        ):
            self.assertEqual(model.objects.count(), 0, model.__name__)

    def assert_session_has_no_secrets(self, password, pin):
        session = dict(self.client.session)
        serialized = repr(session)
        self.assertNotIn(password, serialized)
        self.assertNotIn(pin, serialized)
        for key in session:
            self.assertNotIn("password", key.lower())
            self.assertNotIn("pin", key.lower())

    def test_get_and_invalid_post_never_create_partial_resources(self):
        response = self.client.get(reverse("onboarding:start"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Paso 1 de 4")
        self.assert_no_provisioning()

        password, pin = "A-secure-password-2026!", "2468"
        response = self.client.post(
            reverse("onboarding:start"),
            valid_form_data(legal_name="", owner_password=password, owner_pin=pin),
        )
        self.assertEqual(response.status_code, 200)
        self.assert_no_provisioning()
        self.assert_session_has_no_secrets(password, pin)

    def test_valid_post_provisions_once_authenticates_and_uses_prg(self):
        password, pin = "A-secure-password-2026!", "2468"
        response = self.client.post(
            reverse("onboarding:start"),
            valid_form_data(owner_password=password, owner_pin=pin),
        )
        self.assertRedirects(response, reverse("onboarding:success"))
        self.assertEqual(Business.objects.count(), 1)
        self.assertEqual(BusinessProfile.objects.count(), 1)
        self.assertEqual(POSSettings.objects.count(), 1)
        self.assertEqual(Tax.objects.filter(rate="21.00", is_default=True).count(), 1)
        self.assertEqual(
            Store.objects.filter(is_default=True, is_active=True).count(), 1
        )
        owner = CustomUser.objects.get()
        self.assertEqual(owner.role, RoleChoices.OWNER)
        self.assertTrue(owner.check_password(password))
        self.assertTrue(owner.check_pin(pin))
        self.assertEqual(CashRegister.objects.filter(name="Caja principal").count(), 1)
        self.assertEqual(PaymentMethod.objects.count(), 4)
        self.assertEqual(BillingSeries.objects.count(), 5)
        self.assertEqual(int(self.client.session["_auth_user_id"]), owner.pk)
        self.assert_session_has_no_secrets(password, pin)

        success = self.client.get(reverse("onboarding:success"))
        self.assertEqual(success.status_code, 200)
        self.assertNotContains(success, password)
        self.assertNotContains(success, pin)
        self.assertNotContains(success, "pin_hash")
        self.assertEqual(Business.objects.count(), 1)
        duplicate_post = self.client.post(
            reverse("onboarding:start"), valid_form_data()
        )
        self.assertRedirects(duplicate_post, reverse("core:home"))
        self.assertEqual(Business.objects.count(), 1)

    def test_store_same_address_and_partial_custom_fallback(self):
        self.client.post(
            reverse("onboarding:start"),
            valid_form_data(
                store_email="esto-no-es-email",
                store_postal_code="BAD",
                store_phone="BAD",
            ),
        )
        profile = BusinessProfile.objects.get()
        store = Store.objects.get()
        self.assertEqual(store.address_line_1, profile.address_line_1)
        self.assertEqual(store.email_store, profile.email)

        self.client.logout()
        data = valid_form_data(
            tax_identifier="B87654321",
            owner_email="grace@other.example",
            same_business_address="",
            store_address_line_1="Avenida Sur 4",
            store_city="Sevilla",
        )
        self.client.post(reverse("onboarding:start"), data)
        second = Store.objects.get(business__profile__tax_identifier="B87654321")
        self.assertEqual(second.address_line_1, "Avenida Sur 4")
        self.assertEqual(second.city, "Sevilla")
        self.assertEqual(second.postal_code, "28001")

    def test_duplicate_identity_is_human_readable_and_atomic(self):
        self.client.post(reverse("onboarding:start"), valid_form_data())
        self.client.logout()
        response = self.client.post(
            reverse("onboarding:start"),
            valid_form_data(
                tax_identifier=" b12345678 ", owner_email="other@acme.example"
            ),
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Ya existe un negocio con esta identidad fiscal")
        self.assertEqual(response.context["initial_step"], 1)
        self.assertEqual(Business.objects.count(), 1)
        self.assertEqual(CustomUser.objects.count(), 1)
        self.assertEqual(Store.objects.count(), 1)
        self.assertEqual(PaymentMethod.objects.count(), 4)
        self.assertEqual(BillingSeries.objects.count(), 5)
        self.assertContains(response, 'id="id_tax_identifier"')
        self.assertContains(response, 'aria-invalid="true"')
        self.assertContains(response, 'aria-describedby="id_tax_identifier_error"')

    def test_predictable_invalid_inputs_return_inline_errors_without_resources(self):
        cases = (
            ("postal_code", "1234"),
            ("phone", "telefonoABC"),
            ("owner_phone", "600 ABC"),
            ("store_postal_code", "BAD"),
            ("store_phone", "BAD"),
        )
        for field, value in cases:
            with self.subTest(field=field):
                data = valid_form_data(**{field: value})
                if field.startswith("store_"):
                    data["same_business_address"] = ""
                response = self.client.post(reverse("onboarding:start"), data)
                self.assertEqual(response.status_code, 200)
                self.assertIn(field, response.context["form"].errors)
                self.assert_no_provisioning()

    def test_existing_owner_email_is_rejected_before_provisioning(self):
        existing_business = create_business()
        create_user(existing_business, email="ada@acme.example")
        response = self.client.post(reverse("onboarding:start"), valid_form_data())
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "No podemos utilizar este correo")
        self.assertIn("owner_email", response.context["form"].errors)
        self.assertContains(response, 'id="id_owner_email"')
        self.assertContains(response, 'aria-invalid="true"')
        self.assertContains(response, 'aria-describedby="id_owner_email_error"')
        self.assertEqual(Business.objects.count(), 1)
        self.assertEqual(CustomUser.objects.count(), 1)

    @patch("apps.onboarding.views.OnboardingService.create_business")
    def test_domain_validation_error_is_safely_rendered(self, create_business):
        create_business.side_effect = ValidationError({"internal": "technical detail"})
        response = self.client.post(reverse("onboarding:start"), valid_form_data())
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "No hemos podido validar los datos")
        self.assertNotContains(response, "internal")
        self.assertNotContains(response, "technical detail")

    @patch("apps.onboarding.views.OnboardingService.create_business")
    def test_known_service_error_does_not_show_success(self, create_business):
        create_business.side_effect = OnboardingError("No se pudo preparar el negocio.")
        response = self.client.post(reverse("onboarding:start"), valid_form_data())
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "No se pudo preparar el negocio")
        self.assertNotContains(response, "Tu Netxodo está listo")
        self.assert_no_provisioning()

    def test_authenticated_user_cannot_start_another_onboarding(self):
        self.client.post(reverse("onboarding:start"), valid_form_data())
        response = self.client.get(reverse("onboarding:start"))
        self.assertRedirects(response, reverse("core:home"))

    def test_welcome_requires_matching_onboarding_session_and_store(self):
        business = create_business()
        user = create_user(business)
        self.client.force_login(user)
        response = self.client.get(reverse("onboarding:welcome"))
        self.assertRedirects(response, reverse("core:home"))

        self.client.logout()
        self.client.post(
            reverse("onboarding:start"),
            valid_form_data(
                tax_identifier="B87654321", owner_email="fresh@example.com"
            ),
        )
        response = self.client.get(reverse("onboarding:welcome"))
        self.assertEqual(response.status_code, 200)

    def test_onboarding_post_requires_csrf_and_accepts_valid_token(self):
        client = Client(enforce_csrf_checks=True)
        url = reverse("onboarding:start")
        self.assertEqual(client.post(url, valid_form_data()).status_code, 403)

        client.get(url)
        token = client.cookies["csrftoken"].value
        response = client.post(
            url,
            valid_form_data(tax_identifier="B11223344", owner_email="csrf@example.com"),
            HTTP_X_CSRFTOKEN=token,
        )
        self.assertEqual(response.status_code, 302)
