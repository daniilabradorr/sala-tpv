from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import TestCase

from apps.business_config.helpers import get_display_price, resolve_tax_rate
from apps.business_config.models import BusinessProfile, POSSettings
from apps.business_config.services import bootstrap_business_configuration
from apps.core.models import Business


class BusinessConfigBootstrapTests(TestCase):
    def test_signal_creates_profile_and_pos_settings_for_new_business(self):
        business = Business.objects.create(name="Sala Centro")

        self.assertTrue(BusinessProfile.objects.filter(business=business).exists())
        self.assertTrue(POSSettings.objects.filter(business=business).exists())

    def test_bootstrap_service_is_idempotent(self):
        business = Business.objects.create(name="Sala Norte")

        bootstrap_business_configuration(business)
        bootstrap_business_configuration(business)

        self.assertEqual(BusinessProfile.objects.filter(business=business).count(), 1)
        self.assertEqual(POSSettings.objects.filter(business=business).count(), 1)


class BusinessProfileTaxTests(TestCase):
    def setUp(self):
        self.business = Business.objects.create(name="Sala Centro")
        self.profile = self.business.profile

    def test_default_tax_rate_is_21_by_default(self):
        self.assertEqual(self.profile.default_tax_rate, Decimal("21.00"))

    def test_default_tax_rate_is_used_as_fallback(self):
        self.profile.default_tax_rate = Decimal("21.00")
        self.profile.save()

        effective_tax_rate = self.profile.resolve_tax_rate()

        self.assertEqual(effective_tax_rate, Decimal("21.00"))

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
        self.profile = self.business.profile
        self.settings = self.business.pos_settings
        self.profile.default_tax_rate = Decimal("21.00")
        self.profile.save()

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


class POSSettingsValidationTests(TestCase):
    def setUp(self):
        self.business = Business.objects.create(name="Sala Centro")

    def test_manual_discount_must_be_zero_when_manual_discounts_are_disabled(self):
        settings = POSSettings(
            business=self.business,
            prices_include_tax=True,
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
