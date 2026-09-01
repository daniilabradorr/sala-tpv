from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import TestCase

from apps.business_config.helpers import get_display_price, resolve_tax_rate
from apps.business_config.models import BusinessProfile, POSSettings
from apps.business_config.services import create_business_configuration
from apps.catalog.models import Tax
from apps.catalog.services import BusinessDefaultTaxResolutionError
from apps.core.models import Business


def create_configuration(business, **overrides):
    data = {
        "legal_name": "Sala Centro SL",
        "tax_identifier": "B12345678",
        "phone": "+34 600 123 456",
        "email": "administracion@sala.example",
        "address_line_1": "Calle Mayor 1",
        "postal_code": "28001",
        "city": "Madrid",
        "province": "Madrid",
    }
    data.update(overrides)
    return create_business_configuration(business=business, **data)


class BusinessConfigurationCreationTests(TestCase):
    def test_creating_business_does_not_create_configuration(self):
        business = Business.objects.create(name="Sala Centro")

        self.assertFalse(BusinessProfile.objects.filter(business=business).exists())
        self.assertFalse(POSSettings.objects.filter(business=business).exists())

    def test_service_creates_profile_with_supplied_fiscal_data(self):
        business = Business.objects.create(name="Sala Centro")

        profile, _ = create_configuration(
            business,
            legal_name="Sala Centro Restauración SL",
            tax_identifier="B87654321",
            email="fiscal@sala-centro.example",
        )

        self.assertEqual(profile.legal_name, "Sala Centro Restauración SL")
        self.assertEqual(profile.tax_identifier, "B87654321")
        self.assertEqual(profile.email, "fiscal@sala-centro.example")
        self.assertEqual(profile.address_line_1, "Calle Mayor 1")

    def test_service_creates_pos_settings_with_netxodo_defaults(self):
        business = Business.objects.create(name="Sala Centro")

        _, settings = create_configuration(business)

        self.assertTrue(settings.prices_include_tax)
        self.assertTrue(settings.enable_stock_control)
        self.assertFalse(settings.allow_sale_without_stock)
        self.assertTrue(settings.allow_manual_price)
        self.assertTrue(settings.allow_manual_discounts)
        self.assertEqual(settings.max_manual_discount_percent, Decimal("20.00"))
        self.assertTrue(settings.require_open_cash_register)
        self.assertTrue(settings.allow_split_payments)
        self.assertTrue(settings.require_pin_for_sensitive_actions)

    def test_service_does_not_create_duplicate_configuration_silently(self):
        business = Business.objects.create(name="Sala Norte")
        create_configuration(business)

        with self.assertRaises(ValidationError):
            create_configuration(business)

        self.assertEqual(BusinessProfile.objects.filter(business=business).count(), 1)
        self.assertEqual(POSSettings.objects.filter(business=business).count(), 1)


class BusinessProfileTaxTests(TestCase):
    def setUp(self):
        self.business = Business.objects.create(name="Sala Centro")
        self.profile, _ = create_configuration(self.business)

    def test_default_tax_rate_is_21_by_default(self):
        self.assertEqual(self.profile.default_tax_rate, Decimal("21.00"))

    def canonical_tax(self, rate=Decimal("10.00")):
        return Tax.objects.create(
            business=self.business,
            name=f"IVA {rate}",
            code=f"IVA_{rate}",
            rate=rate,
            is_default=True,
        )

    def test_canonical_tax_is_used_as_fallback(self):
        tax = self.canonical_tax()
        self.profile.default_tax_rate = Decimal("21.00")
        self.profile.save()

        effective_tax_rate = self.profile.resolve_tax_rate()

        self.assertEqual(effective_tax_rate, tax.rate)

    def test_explicit_tax_rate_overrides_default_tax_rate(self):
        self.profile.default_tax_rate = Decimal("21.00")
        self.profile.save()

        effective_tax_rate = self.profile.resolve_tax_rate(Decimal("10.00"))

        self.assertEqual(effective_tax_rate, Decimal("10.00"))

    def test_default_tax_rate_must_be_between_0_and_100(self):
        self.profile.default_tax_rate = Decimal("150.00")

        with self.assertRaises(ValidationError):
            self.profile.full_clean()


class POSSettingsPriceRulesTests(TestCase):
    def setUp(self):
        self.business = Business.objects.create(name="Sala Centro")
        self.profile, self.settings = create_configuration(self.business)
        self.profile.default_tax_rate = Decimal("21.00")
        self.profile.save()
        Tax.objects.create(
            business=self.business,
            name="IVA 21",
            code="IVA_21",
            rate=Decimal("21.00"),
            is_default=True,
        )

    def test_prices_include_tax_true_only_changes_display_price(self):
        self.settings.prices_include_tax = True
        self.settings.save()

        base_price = Decimal("10.00")
        original_base_price = Decimal("10.00")

        display_price = self.settings.get_display_price(base_price)

        self.assertEqual(base_price, original_base_price)
        self.assertEqual(display_price, Decimal("12.10"))

    def test_prices_include_tax_false_returns_base_price(self):
        self.settings.prices_include_tax = False
        self.settings.save()

        base_price = Decimal("10.00")
        display_price = self.settings.get_display_price(base_price)

        self.assertEqual(display_price, Decimal("10.00"))

    def test_resolve_tax_rate_prefers_explicit_tax_rate(self):
        effective_tax_rate = self.settings.resolve_tax_rate(Decimal("10.00"))

        self.assertEqual(effective_tax_rate, Decimal("10.00"))

    def test_helper_resolve_tax_rate_uses_default_when_explicit_is_none(self):
        resolved = resolve_tax_rate(None, Decimal("21.00"))

        self.assertEqual(resolved, Decimal("21.00"))

    def test_helper_get_display_price_does_not_change_base_storage_rule(self):
        base_price = Decimal("10.00")
        display_price = get_display_price(
            base_price=base_price,
            tax_rate=Decimal("21.00"),
            prices_include_tax=True,
        )

        self.assertEqual(base_price, Decimal("10.00"))
        self.assertEqual(display_price, Decimal("12.10"))


class MissingCanonicalTaxTests(TestCase):
    def setUp(self):
        self.business = Business.objects.create(name="Sin configuración fiscal")
        create_configuration(self.business)

    def test_pos_settings_tax_resolution_fails_closed(self):
        with self.assertRaises(BusinessDefaultTaxResolutionError):
            self.business.pos_settings.resolve_tax_rate()

    def test_final_price_does_not_treat_missing_tax_as_zero(self):
        with self.assertRaises(BusinessDefaultTaxResolutionError):
            self.business.pos_settings.calculate_final_price(Decimal("10.00"))

    def test_legacy_profile_rate_cannot_rescue_missing_tax(self):
        self.business.profile.default_tax_rate = Decimal("21.00")
        self.business.profile.save()

        with self.assertRaises(BusinessDefaultTaxResolutionError):
            self.business.profile.resolve_tax_rate()

    def test_other_business_default_tax_is_not_used(self):
        other_business = Business.objects.create(name="Con configuración fiscal")
        create_configuration(other_business, email="other@sala.example")
        Tax.objects.create(
            business=other_business,
            name="IVA 10",
            code="IVA_10",
            rate=Decimal("10.00"),
            is_default=True,
        )

        with self.assertRaises(BusinessDefaultTaxResolutionError):
            self.business.pos_settings.resolve_tax_rate()


class POSSettingsValidationTests(TestCase):
    def setUp(self):
        self.business = Business.objects.create(name="Sala Centro")
        create_configuration(self.business)

    def test_manual_discount_must_be_zero_when_manual_discounts_are_disabled(self):
        settings = POSSettings(
            business=self.business,
            prices_include_tax=True,
            enable_stock_control=True,
            allow_sale_without_stock=False,
            allow_manual_price=False,
            allow_manual_discounts=False,
            max_manual_discount_percent=Decimal("10.00"),
            require_open_cash_register=True,
            allow_split_payments=True,
            require_pin_for_sensitive_actions=True,
        )

        with self.assertRaises(ValidationError):
            settings.full_clean()

    def test_sale_requires_open_cash_register_returns_flag(self):
        settings = self.business.pos_settings
        settings.require_open_cash_register = True
        settings.save()

        self.assertTrue(settings.sale_requires_open_cash_register())

        settings.require_open_cash_register = False
        settings.save()

        self.assertFalse(settings.sale_requires_open_cash_register())

    def test_enable_stock_control_is_true_by_default(self):
        settings = self.business.pos_settings

        self.assertTrue(settings.enable_stock_control)

    def test_require_pin_for_sensitive_actions_is_true_by_default(self):
        settings = self.business.pos_settings

        self.assertTrue(settings.require_pin_for_sensitive_actions)


class BusinessProfileValidationTests(TestCase):
    def setUp(self):
        self.business = Business.objects.create(name="Sala Centro")
        self.profile, _ = create_configuration(self.business)

    def test_tax_identifier_is_required(self):
        self.profile.tax_identifier = ""

        with self.assertRaises(ValidationError) as context:
            self.profile.full_clean()

        self.assertIn("tax_identifier", context.exception.message_dict)

    def test_fiscal_address_fields_are_required(self):
        required_fields = [
            "address_line_1",
            "postal_code",
            "city",
            "province",
        ]

        for field in required_fields:
            with self.subTest(field=field):
                profile = self.business.profile
                original_value = getattr(profile, field)
                setattr(profile, field, "")

                with self.assertRaises(ValidationError) as context:
                    profile.full_clean()

                self.assertIn(field, context.exception.message_dict)
                setattr(profile, field, original_value)
