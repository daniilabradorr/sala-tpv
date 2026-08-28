from django.test import TestCase
from django.utils import timezone

from apps.cash_register.models import CashRegister

from apps.billing.models import BillingDocumentTypeChoices, BillingSeries
from apps.billing.selectors import active_billing_series
from apps.sales.tests.factories import create_sales_business, create_sales_store


class ActiveBillingSeriesSelectorTests(TestCase):
    def setUp(self):
        self.business = create_sales_business()
        self.other_business = create_sales_business()
        self.store = create_sales_store(business=self.business)
        self.other_store = create_sales_store(business=self.business)
        self.year = timezone.localdate().year

    def make(
        self,
        prefix,
        *,
        business=None,
        store=None,
        cash_register=None,
        active=True,
        year=None,
        document_type=BillingDocumentTypeChoices.R1,
    ):
        return BillingSeries.objects.create(
            business=business or self.business,
            store=store,
            cash_register=cash_register,
            name=prefix,
            prefix=prefix,
            document_type=document_type,
            year=year or self.year,
            is_active=active,
        )

    def test_sentinel_distinguishes_omitted_none_and_concrete_store(self):
        global_series = self.make("GLOBAL")
        scoped = self.make("STORE", store=self.store)
        other_scoped = self.make("OTHER", store=self.other_store)
        self.make("TENANT", business=self.other_business)
        self.make("INACTIVE", active=False)
        self.make("YEAR", year=self.year - 1)
        self.make("TYPE", document_type=BillingDocumentTypeChoices.R5)
        omitted = active_billing_series(
            business=self.business,
            document_type=BillingDocumentTypeChoices.R1,
            year=self.year,
        )
        self.assertEqual(set(omitted), {global_series, scoped, other_scoped})
        only_global = active_billing_series(
            business=self.business,
            document_type=BillingDocumentTypeChoices.R1,
            year=self.year,
            store=None,
        )
        self.assertEqual(set(only_global), {global_series})
        compatible = active_billing_series(
            business=self.business,
            document_type=BillingDocumentTypeChoices.R1,
            year=self.year,
            store=self.store,
        )
        self.assertEqual(set(compatible), {global_series, scoped})

    def test_sentinel_distinguishes_cash_register_scopes(self):
        register = CashRegister.objects.create(
            business=self.business, store=self.store, name="Principal", code="MAIN"
        )
        other_register = CashRegister.objects.create(
            business=self.business, store=self.store, name="Secondary", code="SECOND"
        )
        global_series = self.make("CASHGLOBAL")
        scoped = self.make("CASHMAIN", store=self.store, cash_register=register)
        other_scoped = self.make(
            "CASHOTHER", store=self.store, cash_register=other_register
        )
        omitted = active_billing_series(
            business=self.business,
            document_type=BillingDocumentTypeChoices.R1,
            year=self.year,
        )
        self.assertEqual(set(omitted), {global_series, scoped, other_scoped})
        only_global = active_billing_series(
            business=self.business,
            document_type=BillingDocumentTypeChoices.R1,
            year=self.year,
            cash_register=None,
        )
        self.assertEqual(set(only_global), {global_series})
        compatible = active_billing_series(
            business=self.business,
            document_type=BillingDocumentTypeChoices.R1,
            year=self.year,
            cash_register=register,
        )
        self.assertEqual(set(compatible), {global_series, scoped})
