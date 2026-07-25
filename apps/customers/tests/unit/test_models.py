from decimal import Decimal

from django import forms
from django.core.exceptions import ValidationError
from django.test import TestCase

from apps.customers.models import (
    CustomerAccount,
    CustomerTypeChoices,
    EntryTypeChoices,
)
from apps.customers.tests.factories import (
    create_account,
    create_customer,
    create_customer_user,
    create_entry,
)
from apps.users.models import RoleChoices
from apps.users.tests.factories import create_business, create_user


class CustomerModelTests(TestCase):
    def setUp(self):
        self.business = create_business(slug="cust-models")

    def test_create_valid_person(self):
        customer = create_customer(
            business=self.business, customer_type=CustomerTypeChoices.PERSON
        )
        self.assertEqual(customer.customer_type, CustomerTypeChoices.PERSON)

    def test_create_valid_company(self):
        customer = create_customer(
            business=self.business, customer_type=CustomerTypeChoices.COMPANY
        )
        self.assertEqual(customer.customer_type, CustomerTypeChoices.COMPANY)

    def test_normalizes_name(self):
        self.assertEqual(
            create_customer(business=self.business, name="  Ana  ").name, "Ana"
        )

    def test_normalizes_legal_name(self):
        self.assertEqual(
            create_customer(business=self.business, legal_name="  Ana SL  ").legal_name,
            "Ana SL",
        )

    def test_normalizes_tax_identifier(self):
        self.assertEqual(
            create_customer(
                business=self.business, tax_identifier=" b123 "
            ).tax_identifier,
            "B123",
        )

    def test_normalizes_country_code(self):
        self.assertEqual(
            create_customer(business=self.business, country_code=" pt ").country_code,
            "PT",
        )

    def test_normalizes_foreign_id_type(self):
        self.assertEqual(
            create_customer(
                business=self.business, foreign_id_type=" pass ", foreign_id="x"
            ).foreign_id_type,
            "PASS",
        )

    def test_normalizes_foreign_id(self):
        self.assertEqual(
            create_customer(
                business=self.business, foreign_id_type="pass", foreign_id=" x1 "
            ).foreign_id,
            "X1",
        )

    def test_normalizes_email(self):
        self.assertEqual(
            create_customer(business=self.business, email="A@EXAMPLE.COM").email,
            "a@example.com",
        )

    def test_normalizes_address_and_contact(self):
        customer = create_customer(
            business=self.business,
            phone=" 600 ",
            address_line_1=" Calle ",
            postal_code=" 08001 ",
            city=" Bcn ",
            province=" Cat ",
        )
        self.assertEqual(
            (
                customer.phone,
                customer.address_line_1,
                customer.postal_code,
                customer.city,
                customer.province,
            ),
            ("600", "Calle", "08001", "Bcn", "Cat"),
        )

    def test_blank_name_rejected(self):
        with self.assertRaises(ValidationError):
            create_customer(business=self.business, name=" ")

    def test_blank_country_code_rejected(self):
        with self.assertRaises(ValidationError):
            create_customer(business=self.business, country_code="")

    def test_one_letter_country_code_rejected(self):
        with self.assertRaises(ValidationError):
            create_customer(business=self.business, country_code="E")

    def test_three_letter_country_code_rejected(self):
        with self.assertRaises(ValidationError):
            create_customer(business=self.business, country_code="ESP")

    def test_numeric_country_code_rejected(self):
        with self.assertRaises(ValidationError):
            create_customer(business=self.business, country_code="E1")

    def test_foreign_type_only_rejected(self):
        with self.assertRaises(ValidationError):
            create_customer(business=self.business, foreign_id_type="PASS")

    def test_foreign_number_only_rejected(self):
        with self.assertRaises(ValidationError):
            create_customer(business=self.business, foreign_id="X1")

    def test_complete_foreign_id_accepted(self):
        customer = create_customer(
            business=self.business,
            country_code="FR",
            foreign_id_type="PASS",
            foreign_id="X1",
        )
        self.assertTrue(customer.has_foreign_tax_data)

    def test_duplicate_tax_identifier_same_business_rejected_by_db_or_validation(self):
        create_customer(business=self.business, tax_identifier="B123")
        with self.assertRaises(Exception):
            create_customer(business=self.business, tax_identifier="B123")

    def test_same_tax_identifier_other_business_accepted(self):
        create_customer(business=self.business, tax_identifier="B123")
        other = create_business(name="Other", slug="cust-models-other")
        self.assertEqual(
            create_customer(business=other, tax_identifier="B123").tax_identifier,
            "B123",
        )

    def test_duplicate_foreign_id_same_business_and_country_rejected(self):
        create_customer(
            business=self.business,
            country_code="FR",
            foreign_id_type="PASS",
            foreign_id="X1",
        )
        with self.assertRaises(Exception):
            create_customer(
                business=self.business,
                country_code="FR",
                foreign_id_type="PASS",
                foreign_id="X1",
            )

    def test_same_foreign_id_other_business_accepted(self):
        create_customer(
            business=self.business,
            country_code="FR",
            foreign_id_type="PASS",
            foreign_id="X1",
        )
        other = create_business(name="Other", slug="cust-models-other-foreign")
        self.assertEqual(
            create_customer(
                business=other,
                country_code="FR",
                foreign_id_type="PASS",
                foreign_id="X1",
            ).foreign_id,
            "X1",
        )

    def test_same_foreign_id_different_country_accepted(self):
        create_customer(
            business=self.business,
            country_code="FR",
            foreign_id_type="PASS",
            foreign_id="X1",
        )
        self.assertEqual(
            create_customer(
                business=self.business,
                country_code="PT",
                foreign_id_type="PASS",
                foreign_id="X1",
            ).country_code,
            "PT",
        )

    def test_fiscal_name_uses_legal_name(self):
        self.assertEqual(
            create_customer(
                business=self.business, name="Ana", legal_name="Ana SL"
            ).fiscal_name,
            "Ana SL",
        )

    def test_fiscal_name_falls_back_to_name(self):
        self.assertEqual(
            create_customer(business=self.business, name="Ana").fiscal_name, "Ana"
        )

    def test_es_customer_with_tax_identifier_has_complete_national_identity(self):
        customer = create_customer(
            business=self.business,
            country_code="ES",
            tax_identifier="B1",
        )
        self.assertTrue(customer.has_national_tax_data)
        self.assertFalse(customer.has_foreign_tax_data)
        self.assertTrue(customer.has_complete_fiscal_identity)

    def test_es_customer_with_only_foreign_id_is_not_fiscally_complete(self):
        customer = create_customer(
            business=self.business,
            country_code="ES",
            foreign_id_type="PASS",
            foreign_id="X1",
        )
        self.assertFalse(customer.has_national_tax_data)
        self.assertFalse(customer.has_foreign_tax_data)
        self.assertFalse(customer.has_complete_fiscal_identity)

    def test_foreign_customer_with_foreign_id_has_complete_foreign_identity(self):
        customer = create_customer(
            business=self.business,
            country_code="FR",
            foreign_id_type="PASS",
            foreign_id="X1",
        )
        self.assertFalse(customer.has_national_tax_data)
        self.assertTrue(customer.has_foreign_tax_data)
        self.assertTrue(customer.has_complete_fiscal_identity)

    def test_foreign_customer_with_only_national_tax_identifier_is_not_complete(self):
        customer = create_customer(
            business=self.business,
            country_code="FR",
            tax_identifier="B1",
        )
        self.assertFalse(customer.has_national_tax_data)
        self.assertFalse(customer.has_foreign_tax_data)
        self.assertFalse(customer.has_complete_fiscal_identity)


class CustomerAccountModelTests(TestCase):
    def setUp(self):
        self.business = create_business(slug="acct-models")

    def test_account_same_business(self):
        account = create_account(business=self.business)
        self.assertEqual(account.customer.business_id, account.business_id)

    def test_account_other_business_rejected(self):
        customer = create_customer(business=self.business)
        other = create_business(name="Other", slug="acct-other")
        with self.assertRaises(ValidationError):
            CustomerAccount.objects.create(business=other, customer=customer)

    def test_credit_limit_zero_accepted(self):
        self.assertEqual(
            create_account(
                business=self.business, credit_limit=Decimal("0.00")
            ).credit_limit,
            Decimal("0.00"),
        )

    def test_credit_limit_positive_accepted(self):
        self.assertEqual(
            create_account(
                business=self.business, credit_limit=Decimal("10.00")
            ).credit_limit,
            Decimal("10.00"),
        )

    def test_credit_limit_negative_rejected(self):
        with self.assertRaises(ValidationError):
            create_account(business=self.business, credit_limit=Decimal("-0.01"))

    def test_available_credit_without_debt(self):
        self.assertEqual(
            create_account(
                business=self.business,
                balance=Decimal("0.00"),
                credit_limit=Decimal("10.00"),
            ).available_credit,
            Decimal("10.00"),
        )

    def test_available_credit_with_debt(self):
        self.assertEqual(
            create_account(
                business=self.business,
                balance=Decimal("4.00"),
                credit_limit=Decimal("10.00"),
            ).available_credit,
            Decimal("6.00"),
        )

    def test_available_credit_with_negative_balance_does_not_increase_limit(self):
        self.assertEqual(
            create_account(
                business=self.business,
                balance=Decimal("-5.00"),
                credit_limit=Decimal("10.00"),
            ).available_credit,
            Decimal("10.00"),
        )

    def test_balance_not_editable_in_modelform(self):
        class AccountForm(forms.ModelForm):
            class Meta:
                model = CustomerAccount
                fields = "__all__"

        self.assertNotIn("balance", AccountForm().fields)


class CustomerAccountEntryModelTests(TestCase):
    def setUp(self):
        self.business = create_business(slug="entry-models")
        self.account = create_account(business=self.business)

    def test_entry_same_business(self):
        self.assertEqual(
            create_entry(business=self.business, account=self.account).business,
            self.business,
        )

    def test_entry_other_business_account_rejected(self):
        other_account = create_account(
            business=create_business(name="Other", slug="entry-other")
        )
        with self.assertRaises(ValidationError):
            create_entry(business=self.business, account=other_account)

    def test_created_by_same_business_accepted(self):
        user = create_customer_user(business=self.business)
        self.assertEqual(
            create_entry(
                business=self.business, account=self.account, created_by=user
            ).created_by,
            user,
        )

    def test_created_by_other_business_rejected(self):
        user = create_customer_user(
            business=create_business(name="Other", slug="entry-user-other")
        )
        with self.assertRaises(ValidationError):
            create_entry(business=self.business, account=self.account, created_by=user)

    def test_normal_user_without_business_rejected(self):
        user = create_user(
            business=None,
            email="normal-without-business@customers.test",
            role=RoleChoices.CASHIER,
            is_superuser=True,
        )
        user.is_superuser = False
        with self.assertRaises(ValidationError):
            create_entry(business=self.business, account=self.account, created_by=user)

    def test_superuser_without_business_accepted(self):
        user = create_user(
            business=None,
            email="super@customers.test",
            role=RoleChoices.OWNER,
            is_superuser=True,
            is_staff=True,
        )
        self.assertEqual(
            create_entry(
                business=self.business, account=self.account, created_by=user
            ).created_by,
            user,
        )

    def test_created_by_none_accepted(self):
        self.assertIsNone(
            create_entry(
                business=self.business, account=self.account, created_by=None
            ).created_by
        )

    def test_charge_positive_accepted(self):
        self.assertTrue(
            create_entry(
                business=self.business,
                account=self.account,
                entry_type=EntryTypeChoices.CHARGE,
                amount=Decimal("1.00"),
            ).is_charge
        )

    def test_charge_zero_rejected(self):
        with self.assertRaises(ValidationError):
            create_entry(
                business=self.business,
                account=self.account,
                entry_type=EntryTypeChoices.CHARGE,
                amount=Decimal("0.00"),
            )

    def test_charge_negative_rejected(self):
        with self.assertRaises(ValidationError):
            create_entry(
                business=self.business,
                account=self.account,
                entry_type=EntryTypeChoices.CHARGE,
                amount=Decimal("-1.00"),
            )

    def test_payment_negative_accepted(self):
        self.assertTrue(
            create_entry(
                business=self.business,
                account=self.account,
                entry_type=EntryTypeChoices.PAYMENT,
                amount=Decimal("-1.00"),
            ).is_payment
        )

    def test_payment_positive_rejected(self):
        with self.assertRaises(ValidationError):
            create_entry(
                business=self.business,
                account=self.account,
                entry_type=EntryTypeChoices.PAYMENT,
                amount=Decimal("1.00"),
            )

    def test_refund_negative_accepted(self):
        self.assertTrue(
            create_entry(
                business=self.business,
                account=self.account,
                entry_type=EntryTypeChoices.REFUND,
                amount=Decimal("-1.00"),
            ).is_refund
        )

    def test_refund_positive_rejected(self):
        with self.assertRaises(ValidationError):
            create_entry(
                business=self.business,
                account=self.account,
                entry_type=EntryTypeChoices.REFUND,
                amount=Decimal("1.00"),
            )

    def test_adjustment_positive_accepted(self):
        self.assertTrue(
            create_entry(
                business=self.business,
                account=self.account,
                entry_type=EntryTypeChoices.ADJUSTMENT,
                amount=Decimal("1.00"),
            ).is_adjustment
        )

    def test_adjustment_negative_accepted(self):
        self.assertTrue(
            create_entry(
                business=self.business,
                account=self.account,
                entry_type=EntryTypeChoices.ADJUSTMENT,
                amount=Decimal("-1.00"),
            ).is_adjustment
        )

    def test_adjustment_zero_rejected(self):
        with self.assertRaises(ValidationError):
            create_entry(
                business=self.business,
                account=self.account,
                entry_type=EntryTypeChoices.ADJUSTMENT,
                amount=Decimal("0.00"),
            )

    def test_notes_are_stripped(self):
        self.assertEqual(
            create_entry(
                business=self.business, account=self.account, notes=" ok "
            ).notes,
            "ok",
        )
