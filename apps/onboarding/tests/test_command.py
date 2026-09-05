from io import StringIO
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

from apps.billing.models import BillingSeries
from apps.business_config.models import BusinessProfile, POSSettings
from apps.cash_register.models import CashRegister, CashSession
from apps.catalog.models import Tax
from apps.core.models import Business
from apps.onboarding.services import OnboardingService
from apps.payments.models import PaymentMethod
from apps.stores.models import Store
from apps.users.models import CustomUser, RoleChoices


class CreateBusinessOwnerCommandTests(TestCase):
    def setUp(self):
        self.arguments = {
            "legal_name": "Hostelería Uno SL",
            "tax_identifier": "B11111111",
            "trade_name": "Café Central",
            "phone": "+34910000000",
            "email": "empresa@example.com",
            "address_line_1": "Calle Mayor 1",
            "address_line_2": "Local 2",
            "postal_code": "28001",
            "city": "Madrid",
            "province": "Madrid",
            "country_code": "ES",
            "store_name": "Tienda Centro",
            "store_address_line_1": "Calle Tienda 2",
            "store_address_line_2": "Bajo",
            "store_postal_code": "28002",
            "store_city": "Madrid",
            "store_province": "Madrid",
            "store_phone": "+34910000001",
            "store_email": "tienda@example.com",
            "owner_first_name": "Ana",
            "owner_last_name": "García",
            "owner_email": "owner1@example.com",
            "owner_phone": "600000000",
            "owner_password": "A-secure-password-123",
            "owner_pin": "1234",
        }

    def test_success_provisions_complete_business_without_cash_session(self):
        stdout = StringIO()

        call_command("create_business_owner", stdout=stdout, **self.arguments)

        self.assertEqual(Business.objects.count(), 1)
        self.assertEqual(BusinessProfile.objects.count(), 1)
        self.assertEqual(POSSettings.objects.count(), 1)
        self.assertEqual(Tax.objects.count(), 1)
        self.assertEqual(Store.objects.count(), 1)
        self.assertEqual(
            CustomUser.objects.filter(role=RoleChoices.OWNER).count(),
            1,
        )
        self.assertEqual(CashRegister.objects.count(), 1)
        self.assertEqual(CashSession.objects.count(), 0)
        self.assertEqual(PaymentMethod.objects.count(), 4)
        self.assertEqual(BillingSeries.objects.count(), 5)
        self.assertIn("Empresa creada correctamente.", stdout.getvalue())

    def test_command_delegates_all_provisioning_to_service(self):
        expected = OnboardingService.create_business(**self.arguments)
        patch_target = (
            "apps.onboarding.management.commands.create_business_owner."
            "OnboardingService.create_business"
        )

        with patch(patch_target, return_value=expected) as create_business:
            call_command("create_business_owner", stdout=StringIO(), **self.arguments)

        create_business.assert_called_once_with(**self.arguments)
        self.assertEqual(Business.objects.count(), 1)

    def test_duplicate_fiscal_identity_becomes_command_error_and_rolls_back(self):
        call_command("create_business_owner", stdout=StringIO(), **self.arguments)
        duplicate_arguments = {
            **self.arguments,
            "trade_name": "Otra Empresa",
            "owner_email": "owner2@example.com",
        }

        with self.assertRaisesMessage(
            CommandError,
            "Ya existe una empresa con esta identidad fiscal.",
        ):
            call_command(
                "create_business_owner",
                stdout=StringIO(),
                **duplicate_arguments,
            )

        self.assertEqual(Business.objects.count(), 1)
        self.assertEqual(BusinessProfile.objects.count(), 1)

    @patch(
        "apps.onboarding.management.commands.create_business_owner."
        "OnboardingService.create_business"
    )
    @patch(
        "apps.onboarding.management.commands.create_business_owner.getpass.getpass",
        side_effect=["first-password", "different-password"],
    )
    def test_interactive_password_confirmation_must_match(
        self,
        mocked_getpass,
        create_business,
    ):
        arguments = {**self.arguments, "owner_password": None}

        with self.assertRaisesMessage(CommandError, "Las contraseñas no coinciden."):
            call_command("create_business_owner", stdout=StringIO(), **arguments)

        self.assertEqual(mocked_getpass.call_count, 2)
        create_business.assert_not_called()

    def test_success_output_does_not_expose_secrets(self):
        stdout = StringIO()

        call_command("create_business_owner", stdout=stdout, **self.arguments)

        output = stdout.getvalue()
        self.assertNotIn(self.arguments["owner_password"], output)
        self.assertNotIn(self.arguments["owner_pin"], output)

    def test_empty_pin_becomes_command_error_and_rolls_back(self):
        arguments = {**self.arguments, "owner_pin": ""}

        with self.assertRaisesMessage(
            CommandError,
            "El PIN del propietario es obligatorio.",
        ):
            call_command("create_business_owner", stdout=StringIO(), **arguments)

        self.assertEqual(Business.objects.count(), 0)
        self.assertEqual(BusinessProfile.objects.count(), 0)
        self.assertEqual(POSSettings.objects.count(), 0)
        self.assertEqual(Tax.objects.count(), 0)
        self.assertEqual(Store.objects.count(), 0)
        self.assertEqual(CustomUser.objects.count(), 0)
        self.assertEqual(CashRegister.objects.count(), 0)
        self.assertEqual(CashSession.objects.count(), 0)
        self.assertEqual(PaymentMethod.objects.count(), 0)
        self.assertEqual(BillingSeries.objects.count(), 0)

    def test_same_trade_name_provisions_businesses_with_distinct_slugs(self):
        call_command("create_business_owner", stdout=StringIO(), **self.arguments)
        second_arguments = {
            **self.arguments,
            "legal_name": "Hostelería Dos SL",
            "tax_identifier": "B22222222",
            "email": "empresa2@example.com",
            "owner_email": "owner2@example.com",
        }

        call_command("create_business_owner", stdout=StringIO(), **second_arguments)

        businesses = list(Business.objects.order_by("pk"))
        self.assertEqual(
            [business.name for business in businesses],
            ["Café Central"] * 2,
        )
        self.assertEqual(
            [business.slug for business in businesses],
            ["cafe-central", "cafe-central-2"],
        )
