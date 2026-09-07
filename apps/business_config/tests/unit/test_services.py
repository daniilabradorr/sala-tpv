from django.core.exceptions import ValidationError
from django.test import TestCase

from apps.business_config.models import BusinessProfile, POSSettings
from apps.business_config.services import (
    create_business_configuration,
    update_business_profile,
    update_pos_settings,
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

    def test_normalizes_fiscal_identity(self):
        update_business_profile(
            business=self.business,
            country_code=" es ",
            tax_identifier=" b99999999 ",
        )

        self.profile.refresh_from_db()
        self.assertEqual(self.profile.country_code, "ES")
        self.assertEqual(self.profile.tax_identifier, "B99999999")


class UpdatePOSSettingsTests(TestCase):
    def setUp(self):
        self.business = Business.objects.create(name="Sala POS", slug="sala-pos")
        _, self.settings = create_business_configuration(
            business=self.business,
            legal_name="Sala POS SL",
            tax_identifier="B87654321",
            phone="600000001",
            email="pos@example.com",
            address_line_1="Calle Dos",
            postal_code="28002",
            city="Madrid",
            province="Madrid",
        )

    def test_updates_and_returns_settings_for_supplied_business(self):
        result = update_pos_settings(
            business=self.business,
            prices_include_tax=False,
            allow_split_payments=False,
        )

        self.assertEqual(result, self.settings)
        self.settings.refresh_from_db()
        self.assertFalse(self.settings.prices_include_tax)
        self.assertFalse(self.settings.allow_split_payments)

    def test_missing_settings_are_not_created(self):
        missing = Business.objects.create(name="Sin ajustes", slug="sin-ajustes")

        with self.assertRaises(POSSettings.DoesNotExist):
            update_pos_settings(business=missing, prices_include_tax=False)

        self.assertFalse(POSSettings.objects.filter(business=missing).exists())

    def test_other_business_cannot_modify_settings(self):
        other = Business.objects.create(name="Otra POS", slug="otra-pos")

        with self.assertRaises(POSSettings.DoesNotExist):
            update_pos_settings(business=other, allow_split_payments=False)

        self.settings.refresh_from_db()
        self.assertTrue(self.settings.allow_split_payments)

    def test_non_editable_fields_are_ignored(self):
        other = Business.objects.create(name="Destino", slug="destino")
        update_pos_settings(
            business=self.business,
            prices_include_tax=False,
            business_id=other.pk,
            created_at=None,
        )

        self.settings.refresh_from_db()
        self.assertEqual(self.settings.business, self.business)
        self.assertIsNotNone(self.settings.created_at)

    def test_model_validation_rolls_back_invalid_discount_combination(self):
        with self.assertRaises(ValidationError):
            update_pos_settings(
                business=self.business,
                allow_manual_discounts=False,
                max_manual_discount_percent=20,
            )

        self.settings.refresh_from_db()
        self.assertTrue(self.settings.allow_manual_discounts)
        self.assertEqual(self.settings.max_manual_discount_percent, 20)

    def test_disabled_discounts_with_zero_maximum_are_valid(self):
        update_pos_settings(
            business=self.business,
            allow_manual_discounts=False,
            max_manual_discount_percent=0,
        )

        self.settings.refresh_from_db()
        self.assertFalse(self.settings.allow_manual_discounts)
        self.assertEqual(self.settings.max_manual_discount_percent, 0)
