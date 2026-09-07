from django.core.exceptions import ValidationError
from django.test import TestCase

from apps.business_config.models import BusinessProfile
from apps.business_config.services import (
    create_business_configuration,
    update_business_profile,
)
from apps.core.models import Business


class UpdateBusinessProfileTests(TestCase):
    def setUp(self):
        self.business = Business.objects.create(name="Sala", slug="sala")
        self.profile, _ = create_business_configuration(
            business=self.business,
            legal_name="Sala SL",
            tax_identifier="B12345678",
            phone="600000000",
            email="sala@example.com",
            address_line_1="Calle Uno",
            postal_code="28001",
            city="Madrid",
            province="Madrid",
        )

    def test_updates_and_returns_the_profile_for_the_supplied_business(self):
        result = update_business_profile(
            business=self.business,
            legal_name="Sala Actualizada SL",
            phone="699999999",
        )

        self.assertEqual(result, self.profile)
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.legal_name, "Sala Actualizada SL")
        self.assertEqual(self.profile.phone, "699999999")

    def test_does_not_create_a_missing_profile(self):
        missing_business = Business.objects.create(name="Sin perfil", slug="sin-perfil")

        with self.assertRaises(BusinessProfile.DoesNotExist):
            update_business_profile(business=missing_business, legal_name="No crear")

        self.assertFalse(
            BusinessProfile.objects.filter(business=missing_business).exists()
        )

    def test_other_business_cannot_update_this_profile(self):
        other = Business.objects.create(name="Otra", slug="otra")

        with self.assertRaises(BusinessProfile.DoesNotExist):
            update_business_profile(business=other, legal_name="Intento")

        self.profile.refresh_from_db()
        self.assertEqual(self.profile.legal_name, "Sala SL")

    def test_non_editable_fields_are_ignored(self):
        original_tax = self.profile.default_tax_rate

        update_business_profile(
            business=self.business,
            legal_name="Permitido SL",
            default_tax_rate="99.00",
            created_at=None,
        )

        self.profile.refresh_from_db()
        self.assertEqual(self.profile.legal_name, "Permitido SL")
        self.assertEqual(self.profile.default_tax_rate, original_tax)
        self.assertIsNotNone(self.profile.created_at)

    def test_model_validation_is_preserved_and_update_rolls_back(self):
        with self.assertRaises(ValidationError):
            update_business_profile(business=self.business, email="invalid")

        self.profile.refresh_from_db()
        self.assertEqual(self.profile.email, "sala@example.com")
