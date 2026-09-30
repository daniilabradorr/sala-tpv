from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone

from apps.billing.models import BillingDocumentTypeChoices, BillingSeries
from apps.business_config.models import BusinessProfile, POSSettings
from apps.cash_register.models import CashRegister, CashSession
from apps.catalog.models import Tax
from apps.core.models import Business
from apps.onboarding.services import (
    OnboardingDuplicateBusinessError,
    OnboardingInvalidOwnerPasswordError,
    OnboardingInvalidOwnerPinError,
    OnboardingService,
)
from apps.payments.models import PaymentMethod, PaymentMethodCodeChoices
from apps.stores.models import Store
from apps.users.models import CustomUser, RoleChoices, UserStoreAccess


class OnboardingServiceTests(TestCase):
    def onboarding_data(self, **overrides):
        data = {
            "legal_name": "Netxodo Retail SL",
            "trade_name": " Netxodo Centro ",
            "tax_identifier": " b12345678 ",
            "phone": "+34910000000",
            "email": "empresa@example.com",
            "address_line_1": "Calle Mayor 1",
            "address_line_2": "Local B",
            "postal_code": "28001",
            "city": "Madrid",
            "province": "Madrid",
            "store_name": "Tienda Centro",
            "owner_first_name": "Dani",
            "owner_last_name": "Labrador",
            "owner_email": "owner@example.com",
            "owner_phone": "600000000",
            "owner_password": "secure-password-123",
            "owner_pin": "1234",
        }
        data.update(overrides)
        return data

    def test_successful_onboarding_creates_complete_minimum_configuration(self):
        result = OnboardingService.create_business(**self.onboarding_data())

        self.assertEqual(Business.objects.count(), 1)
        self.assertEqual(result.business.name, "Netxodo Centro")
        self.assertEqual(BusinessProfile.objects.count(), 1)
        self.assertEqual(POSSettings.objects.count(), 1)
        self.assertEqual(result.profile.tax_identifier, "B12345678")
        self.assertEqual(result.profile.country_code, "ES")
        self.assertEqual(result.profile.legal_name, "Netxodo Retail SL")
        self.assertEqual(Tax.objects.filter(is_default=True).count(), 1)
        self.assertEqual(Tax.objects.count(), 1)
        self.assertEqual(result.tax.rate, 21)

        self.assertEqual(Store.objects.count(), 1)
        self.assertTrue(result.store.is_default)
        self.assertTrue(result.store.is_active)
        self.assertEqual(result.store.business, result.business)
        self.assertEqual(result.store.address_line_1, result.profile.address_line_1)
        self.assertEqual(result.store.phone_store, result.profile.phone)

        self.assertEqual(CustomUser.objects.count(), 1)
        self.assertEqual(result.owner.role, RoleChoices.OWNER)
        self.assertEqual(result.owner.business, result.business)
        self.assertTrue(result.owner.check_password("secure-password-123"))
        self.assertNotEqual(result.owner.password, "secure-password-123")
        self.assertTrue(result.owner.check_pin("1234"))
        self.assertEqual(UserStoreAccess.objects.count(), 0)

        self.assertEqual(CashRegister.objects.count(), 1)
        self.assertEqual(result.cash_register.name, "Caja principal")
        self.assertEqual(result.cash_register.code, "CAJA-01")
        self.assertEqual(CashSession.objects.count(), 0)

        methods = {method.code: method for method in result.payment_methods}
        self.assertEqual(PaymentMethod.objects.count(), 4)
        self.assertEqual(set(methods), set(PaymentMethodCodeChoices.values))
        self.assertTrue(methods[PaymentMethodCodeChoices.CASH].affects_cash_register)
        for code in (
            PaymentMethodCodeChoices.CARD,
            PaymentMethodCodeChoices.BIZUM,
            PaymentMethodCodeChoices.TRANSFER,
        ):
            self.assertFalse(methods[code].affects_cash_register)

        expected_types = {"F1", "F2", "F3", "R1", "R5"}
        self.assertEqual(BillingSeries.objects.count(), 5)
        self.assertEqual(
            {series.document_type for series in result.billing_series}, expected_types
        )
        for series in result.billing_series:
            self.assertEqual(series.store, result.store)
            self.assertIsNone(series.cash_register)
            self.assertEqual(series.current_number, 0)
            self.assertEqual(series.padding, 6)
            self.assertEqual(series.year, timezone.localdate().year)
            self.assertEqual(
                series.prefix, f"{series.document_type}-{result.store.code}"
            )

    def test_store_specific_values_override_profile_fallbacks(self):
        result = OnboardingService.create_business(
            **self.onboarding_data(
                store_address_line_1="Gran Vía 2",
                store_phone="911111111",
                store_email="centro@example.com",
            )
        )
        self.assertEqual(result.store.address_line_1, "Gran Vía 2")
        self.assertEqual(result.store.phone_store, "911111111")
        self.assertEqual(result.store.email_store, "centro@example.com")

    def test_duplicate_normalized_fiscal_identity_is_rejected_without_fragments(self):
        OnboardingService.create_business(**self.onboarding_data())

        with self.assertRaises(OnboardingDuplicateBusinessError):
            OnboardingService.create_business(
                **self.onboarding_data(
                    tax_identifier=" b12345678 ",
                    owner_email="other-owner@example.com",
                )
            )

        self.assertEqual(Business.objects.count(), 1)
        self.assertEqual(BusinessProfile.objects.count(), 1)
        self.assertEqual(PaymentMethod.objects.count(), 4)
        self.assertEqual(BillingSeries.objects.count(), 5)

    def test_late_billing_series_failure_rolls_back_everything(self):
        real_create = BillingSeries.objects.create

        def create_then_fail(**kwargs):
            if kwargs["document_type"] == BillingDocumentTypeChoices.R5:
                raise RuntimeError("late billing failure")
            return real_create(**kwargs)

        with (
            patch(
                "apps.onboarding.services.BillingSeries.objects.create",
                side_effect=create_then_fail,
            ),
            self.assertRaisesRegex(RuntimeError, "late billing failure"),
        ):
            OnboardingService.create_business(**self.onboarding_data())

        self.assert_no_onboarding_records()

    def test_invalid_profile_data_rolls_back_business(self):
        with self.assertRaises(ValidationError):
            OnboardingService.create_business(**self.onboarding_data(email="invalid"))

        self.assert_no_onboarding_records()

    def test_missing_owner_password_does_not_create_onboarding_fragments(self):
        for invalid_password in (None, "", "   "):
            with (
                self.subTest(owner_password=invalid_password),
                self.assertRaises(OnboardingInvalidOwnerPasswordError),
            ):
                OnboardingService.create_business(
                    **self.onboarding_data(owner_password=invalid_password)
                )

            self.assert_no_onboarding_records()

    def test_missing_owner_pin_does_not_create_onboarding_fragments(self):
        for invalid_pin in (None, "", "   "):
            with (
                self.subTest(owner_pin=invalid_pin),
                self.assertRaises(OnboardingInvalidOwnerPinError),
            ):
                OnboardingService.create_business(
                    **self.onboarding_data(owner_pin=invalid_pin)
                )

            self.assert_no_onboarding_records()

    def assert_no_onboarding_records(self):
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
        self.assertEqual(CashSession.objects.count(), 0)
