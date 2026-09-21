from django.test import SimpleTestCase, override_settings

from apps.onboarding.forms import OnboardingForm


def valid_form_data(**overrides):
    data = {
        "legal_name": "Acme Sociedad Limitada",
        "tax_identifier": "  b12345678 ",
        "trade_name": "Acme",
        "phone": "910000000",
        "email": "hola@acme.example",
        "address_line_1": "Calle Mayor 1",
        "address_line_2": "",
        "postal_code": "28001",
        "city": "Madrid",
        "province": "Madrid",
        "store_name": "Centro",
        "same_business_address": "on",
        "store_address_line_1": "No debe copiarse",
        "store_address_line_2": "",
        "store_postal_code": "",
        "store_city": "",
        "store_province": "",
        "store_phone": "",
        "store_email": "",
        "owner_first_name": "Ada",
        "owner_last_name": "Lovelace",
        "owner_email": "ada@acme.example",
        "owner_phone": "",
        "owner_password": "A-secure-password-2026!",
        "owner_password_confirmation": "A-secure-password-2026!",
        "owner_pin": "2468",
    }
    data.update(overrides)
    return data


@override_settings(AUTH_PASSWORD_VALIDATORS=[])
class OnboardingFormTests(SimpleTestCase):
    def test_normalizes_identity_and_same_address_overrides(self):
        form = OnboardingForm(valid_form_data())
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data["tax_identifier"], "B12345678")
        self.assertEqual(form.service_data()["country_code"], "ES")
        self.assertIsNone(form.cleaned_data["store_address_line_1"])

    def test_custom_address_normalizes_blanks_to_none(self):
        data = valid_form_data(
            same_business_address="",
            store_address_line_1="Otra calle 2",
            store_city="Sevilla",
        )
        form = OnboardingForm(data)
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data["store_address_line_1"], "Otra calle 2")
        self.assertIsNone(form.cleaned_data["store_phone"])

    def test_required_and_email_validation(self):
        form = OnboardingForm(valid_form_data(legal_name="", email="no-es-email"))
        self.assertFalse(form.is_valid())
        self.assertIn("legal_name", form.errors)
        self.assertIn("email", form.errors)

    def test_password_confirmation_and_django_validation(self):
        mismatch = OnboardingForm(
            valid_form_data(owner_password_confirmation="different-password")
        )
        self.assertFalse(mismatch.is_valid())
        self.assertIn("owner_password_confirmation", mismatch.errors)

    def test_pin_accepts_four_and_six_digits(self):
        for pin in ("1234", "123456"):
            with self.subTest(pin=pin):
                form = OnboardingForm(valid_form_data(owner_pin=pin))
                self.assertTrue(form.is_valid(), form.errors)

    def test_pin_rejects_invalid_values(self):
        for pin in ("123", "1234567", "12ab"):
            with self.subTest(pin=pin):
                form = OnboardingForm(valid_form_data(owner_pin=pin))
                self.assertFalse(form.is_valid())
                self.assertIn("owner_pin", form.errors)
