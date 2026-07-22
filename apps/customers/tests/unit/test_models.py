from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import TestCase

from apps.customers.models import (
    Customer,
    CustomerAccount,
    CustomerAccountEntry,
    CustomerAccountEntryTypeChoices,
)
from apps.customers.tests.factories import (
    create_account,
    create_customer,
    create_customer_user,
)
from apps.users.tests.factories import create_business, create_user


class CustomerModelTests(TestCase):
    def test_normalizes_and_properties_and_uniqueness(self):
        b1 = create_business(slug="c1")
        b2 = create_business(name="Otro", slug="c2")
        c = Customer.objects.create(
            business=b1,
            name="  Ana  ",
            legal_name="  Ana SL  ",
            tax_identifier=" b123 ",
            country_code=" es ",
            foreign_id_type=" pass ",
            foreign_id=" x1 ",
            email="A@EXAMPLE.COM",
        )
        self.assertEqual(c.name, "Ana")
        self.assertEqual(c.legal_name, "Ana SL")
        self.assertEqual(c.tax_identifier, "B123")
        self.assertEqual(c.country_code, "ES")
        self.assertEqual(c.foreign_id_type, "PASS")
        self.assertEqual(c.foreign_id, "X1")
        self.assertEqual(c.email, "a@example.com")
        self.assertEqual(c.fiscal_name, "Ana SL")
        self.assertTrue(c.has_national_tax_data)
        self.assertTrue(c.has_foreign_tax_data)
        Customer.objects.create(business=b2, name="Ana otro", tax_identifier="B123")
        with self.assertRaises(ValidationError):
            Customer.objects.create(business=b1, name="Dup", tax_identifier="B123")
        with self.assertRaises(ValidationError):
            Customer.objects.create(
                business=b1, name="Dup F", foreign_id_type="PASS", foreign_id="X1"
            )

    def test_invalid_customer_fields(self):
        b = create_business(slug="invalid")
        for kwargs in [
            {"name": ""},
            {"name": "A", "country_code": "ESP"},
            {"name": "A", "foreign_id": "X"},
            {"name": "A", "foreign_id_type": "PASS"},
        ]:
            with self.assertRaises(ValidationError):
                Customer.objects.create(business=b, **kwargs)
        c = Customer.objects.create(business=b, name="Fallback")
        self.assertEqual(c.fiscal_name, "Fallback")
        self.assertFalse(c.has_national_tax_data)


class CustomerAccountModelTests(TestCase):
    def test_account_rules(self):
        b1 = create_business(slug="a1")
        b2 = create_business(name="B2", slug="a2")
        c = create_customer(business=b1)
        with self.assertRaises(ValidationError):
            CustomerAccount.objects.create(business=b2, customer=c)
        with self.assertRaises(ValidationError):
            CustomerAccount.objects.create(
                business=b1, customer=c, credit_limit=Decimal("-1.00")
            )
        a = create_account(
            business=b1,
            customer=c,
            balance=Decimal("-5.00"),
            credit_limit=Decimal("10.00"),
        )
        self.assertEqual(a.available_credit, Decimal("15.00"))


class CustomerAccountEntryModelTests(TestCase):
    def test_entry_rules(self):
        b1 = create_business(slug="e1")
        b2 = create_business(name="B2", slug="e2")
        account = create_account(business=b1)
        other = create_account(business=b2)
        user_other = create_customer_user(business=b2)
        user_without_business = create_user(
            business=None, email="nobiz@test.com", is_superuser=True, is_staff=True
        )
        user_without_business.is_superuser = False
        with self.assertRaises(ValidationError):
            CustomerAccountEntry.objects.create(
                business=b1,
                account=other,
                entry_type="charge",
                amount=Decimal("1.00"),
                balance_after=Decimal("1.00"),
            )
        with self.assertRaises(ValidationError):
            CustomerAccountEntry.objects.create(
                business=b1,
                account=account,
                entry_type="charge",
                amount=Decimal("1.00"),
                balance_after=Decimal("1.00"),
                created_by=user_other,
            )
        tests = [
            ("charge", Decimal("-1.00")),
            ("payment", Decimal("1.00")),
            ("refund", Decimal("1.00")),
            ("adjustment", Decimal("0.00")),
        ]
        for entry_type, amount in tests:
            with self.assertRaises(ValidationError):
                CustomerAccountEntry.objects.create(
                    business=b1,
                    account=account,
                    entry_type=entry_type,
                    amount=amount,
                    balance_after=Decimal("0.00"),
                )
        entry = CustomerAccountEntry.objects.create(
            business=b1,
            account=account,
            entry_type=CustomerAccountEntryTypeChoices.ADJUSTMENT,
            amount=Decimal("1.00"),
            balance_after=Decimal("1.00"),
            notes=" ok ",
        )
        self.assertEqual(entry.notes, "ok")
