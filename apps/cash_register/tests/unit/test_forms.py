from decimal import Decimal

from django.test import TestCase

from apps.cash_register.forms import CashAdjustmentForm, CashSessionOpenForm
from apps.cash_register.models import CashMovement
from apps.cash_register.test_factories import (
    create_cash_business,
    create_cash_register,
    create_cash_store,
)


class CashRegisterFormsTests(TestCase):
    def test_open_form_scopes_active_registers_to_business_and_store(self):
        business = create_cash_business()
        store = create_cash_store(business=business)
        active = create_cash_register(business=business, store=store)
        create_cash_register(
            business=business, store=store, code="INACTIVE", is_active=False
        )
        other_store = create_cash_store(business=business)
        create_cash_register(business=business, store=other_store)
        form = CashSessionOpenForm(business=business, store=store)
        self.assertQuerySetEqual(form.fields["cash_register"].queryset, [active])

    def test_adjustment_requires_valid_direction_and_decimal_amount(self):
        form = CashAdjustmentForm(
            data={
                "amount": "5.00",
                "adjustment_direction": CashMovement.AdjustmentDirection.IN,
            }
        )
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data["amount"], Decimal("5.00"))
        self.assertFalse(CashAdjustmentForm(data={"amount": "5.00"}).is_valid())
