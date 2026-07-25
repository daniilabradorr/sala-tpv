from django.test import TestCase

from apps.customers.forms import (
    CustomerAccountSettingsForm,
    CustomerCreateForm,
    CustomerUpdateForm,
)
from apps.customers.tests.factories import create_customer
from apps.users.tests.factories import create_business


class CustomerFormTests(TestCase):
    def test_fields_and_validation(self):
        b = create_business(slug="forms")
        form = CustomerCreateForm(
            data={"customer_type": "person", "name": "Ana", "country_code": "ES"},
            business=b,
        )
        self.assertTrue(form.is_valid(), form.errors)
        for field in ["business", "credit_limit", "is_blocked", "balance"]:
            self.assertNotIn(field, form.fields)
        bad = CustomerCreateForm(
            data={"customer_type": "person", "name": "Ana", "country_code": "ESP"},
            business=b,
        )
        self.assertFalse(bad.is_valid())
        partial = CustomerCreateForm(
            data={
                "customer_type": "person",
                "name": "Ana",
                "country_code": "FR",
                "foreign_id": "X",
            },
            business=b,
        )
        self.assertFalse(partial.is_valid())
        create_customer(business=b, tax_identifier="B123")
        dup = CustomerCreateForm(
            data={
                "customer_type": "company",
                "name": "Dup",
                "country_code": "ES",
                "tax_identifier": "b123",
            },
            business=b,
        )
        self.assertFalse(dup.is_valid())
        b2 = create_business(name="Otro", slug="forms2")
        same = CustomerCreateForm(
            data={
                "customer_type": "company",
                "name": "Ok",
                "country_code": "ES",
                "tax_identifier": "b123",
            },
            business=b2,
        )
        self.assertTrue(same.is_valid(), same.errors)
        customer = create_customer(business=b, name="Old")
        update = CustomerUpdateForm(
            data={"customer_type": "person", "name": "New", "country_code": "ES"},
            instance=customer,
            business=b,
        )
        self.assertTrue(update.is_valid(), update.errors)

    def test_account_settings_form(self):
        for value in ["0.00", "10.50"]:
            self.assertTrue(
                CustomerAccountSettingsForm(
                    data={"credit_limit": value, "is_blocked": "on"}
                ).is_valid()
            )
        self.assertFalse(
            CustomerAccountSettingsForm(data={"credit_limit": "-0.01"}).is_valid()
        )
        form = CustomerAccountSettingsForm()
        self.assertNotIn("balance", form.fields)
        self.assertNotIn("customer", form.fields)
        self.assertNotIn("business", form.fields)
