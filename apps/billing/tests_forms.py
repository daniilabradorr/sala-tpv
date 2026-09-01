import uuid
from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from apps.billing.forms import (
    BillingDocumentFilterForm,
    IssueSaleDocumentForm,
    SaleReturnRectificationForm,
    SubstituteSimplifiedDocumentForm,
)
from apps.billing.models import BillingDocumentTypeChoices, BillingSeries
from apps.billing.services import issue_sale_document, substitute_simplified_document
from apps.business_config.services import create_business_configuration
from apps.cash_register.test_factories import create_cash_register
from apps.sales.models import (
    RequestedDocumentTypeChoices,
    SaleReturnStatusChoices,
    SaleStatusChoices,
)
from apps.sales.tests.factories import (
    create_sale,
    create_sale_line,
    create_sale_return,
    create_sale_return_line,
    create_sales_business,
    create_sales_customer,
    create_sales_product,
    create_sales_store,
    create_sales_tax,
    create_sales_user,
)


class BillingFormsFixture(TestCase):
    def setUp(self):
        self.business = create_sales_business()
        self.other_business = create_sales_business()
        self.store = create_sales_store(business=self.business)
        self.other_store = create_sales_store(business=self.business)
        self.user = create_sales_user(business=self.business)
        self.customer = create_sales_customer(
            business=self.business, legal_name="Cliente SL", tax_identifier="B87654321"
        )
        self.other_customer = create_sales_customer(business=self.other_business)
        create_business_configuration(
            business=self.business,
            legal_name="Emisor SL",
            tax_identifier="B12345678",
            phone="600000000",
            email="billing@example.test",
            address_line_1="Calle 1",
            postal_code="28001",
            city="Madrid",
            province="Madrid",
        )
        tax = create_sales_tax(business=self.business)
        self.product = create_sales_product(business=self.business, tax=tax)

    def sale(
        self,
        requested=RequestedDocumentTypeChoices.TICKET,
        customer=None,
        store=None,
        cash_register=None,
    ):
        sale = create_sale(
            business=self.business,
            store=store or self.store,
            opened_by=self.user,
            customer=customer,
            status=SaleStatusChoices.COMPLETED,
            document_type_requested=requested,
            cash_register=cash_register,
        )
        create_sale_line(business=self.business, sale=sale, product=self.product)
        return sale

    def series(self, kind, prefix=None, **overrides):
        values = {
            "business": self.business,
            "store": self.store,
            "name": prefix or kind,
            "document_type": kind,
            "prefix": prefix or f"{kind}-{uuid.uuid4().hex[:5]}",
            "year": timezone.localdate().year,
        }
        values.update(overrides)
        return BillingSeries.objects.create(**values)

    def issued_original(self, sale, kind):
        return issue_sale_document(
            business=self.business,
            sale_id=sale.pk,
            series_id=self.series(kind).pk,
            issued_by=self.user,
            idempotency_key=uuid.uuid4(),
        )

    def completed_return(self, sale):
        return_doc = create_sale_return(
            business=self.business,
            store=self.store,
            original_sale=sale,
            created_by=self.user,
        )
        create_sale_return_line(
            business=self.business,
            return_doc=return_doc,
            original_line=sale.lines.get(),
        )
        return_doc.status = SaleReturnStatusChoices.COMPLETED
        return_doc.completed_at = timezone.now()
        return_doc.save()
        return return_doc


class BillingDocumentFilterFormTests(BillingFormsFixture):
    def test_customer_queryset_is_tenant_scoped_and_keeps_inactive_history(self):
        inactive = create_sales_customer(business=self.business, is_active=False)
        form = BillingDocumentFilterForm(business=self.business)
        self.assertQuerySetEqual(
            form.fields["customer"].queryset.order_by("pk"),
            [self.customer, inactive],
            transform=lambda item: item,
        )
        self.assertNotIn(self.other_customer, form.fields["customer"].queryset)

    def test_cross_tenant_customer_tampering_is_rejected(self):
        form = BillingDocumentFilterForm(
            {"customer": self.other_customer.pk}, business=self.business
        )
        self.assertFalse(form.is_valid())
        self.assertIn("customer", form.errors)

    def test_choices_and_ordered_date_range_are_valid(self):
        today = timezone.localdate()
        form = BillingDocumentFilterForm(
            {
                "document_type": BillingDocumentTypeChoices.F1,
                "status": "issued",
                "date_from": today - timedelta(days=1),
                "date_to": today,
            },
            business=self.business,
        )
        self.assertTrue(form.is_valid(), form.errors)

    def test_reversed_date_range_is_invalid(self):
        today = timezone.localdate()
        form = BillingDocumentFilterForm(
            {"date_from": today, "date_to": today - timedelta(days=1)},
            business=self.business,
        )
        self.assertFalse(form.is_valid())
        self.assertIn("__all__", form.errors)


class IssueSaleDocumentFormTests(BillingFormsFixture):
    def test_invoice_and_ticket_expose_only_expected_series(self):
        f1, f2 = self.series("F1"), self.series("F2")
        invoice = self.sale(RequestedDocumentTypeChoices.INVOICE, self.customer)
        ticket = self.sale()
        self.assertQuerySetEqual(
            IssueSaleDocumentForm(business=self.business, sale=invoice)
            .fields["series"]
            .queryset,
            [f1],
            transform=lambda item: item,
        )
        self.assertQuerySetEqual(
            IssueSaleDocumentForm(business=self.business, sale=ticket)
            .fields["series"]
            .queryset,
            [f2],
            transform=lambda item: item,
        )

    def test_series_scope_excludes_other_tenant_store_inactive_and_year(self):
        sale = self.sale()
        valid = self.series("F2")
        self.series("F2", business=self.other_business, store=None)
        self.series("F2", store=self.other_store)
        self.series("F2", is_active=False)
        self.series("F2", year=timezone.localdate().year - 1)
        queryset = (
            IssueSaleDocumentForm(business=self.business, sale=sale)
            .fields["series"]
            .queryset
        )
        self.assertQuerySetEqual(queryset, [valid], transform=lambda item: item)

    def test_series_scope_enforces_cash_register_compatibility(self):
        register = create_cash_register(business=self.business, store=self.store)
        other_register = create_cash_register(business=self.business, store=self.store)
        sale = self.sale(cash_register=register)
        global_series = self.series("F2")
        matching = self.series("F2", cash_register=register)
        self.series("F2", cash_register=other_register)
        queryset = (
            IssueSaleDocumentForm(business=self.business, sale=sale)
            .fields["series"]
            .queryset
        )
        self.assertCountEqual(queryset, [global_series, matching])

    def test_uuid_is_required_and_only_legitimate_fields_exist(self):
        sale, series = self.sale(), self.series("F2")
        key = uuid.uuid4()
        form = IssueSaleDocumentForm(
            {"series": series.pk, "idempotency_key": key},
            business=self.business,
            sale=sale,
        )
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(set(form.fields), {"series", "idempotency_key"})
        missing = IssueSaleDocumentForm(
            {"series": series.pk}, business=self.business, sale=sale
        )
        self.assertFalse(missing.is_valid())


class SubstituteSimplifiedDocumentFormTests(BillingFormsFixture):
    def test_customer_and_f3_series_are_scoped(self):
        sale = self.sale(customer=self.customer)
        valid = self.series("F3")
        self.series("F2")
        self.series("F3", business=self.other_business, store=None)
        self.series("F3", store=self.other_store)
        self.series("F3", is_active=False)
        inactive = create_sales_customer(business=self.business, is_active=False)
        form = SubstituteSimplifiedDocumentForm(business=self.business, sale=sale)
        self.assertQuerySetEqual(
            form.fields["series"].queryset, [valid], transform=lambda x: x
        )
        self.assertIn(self.customer, form.fields["customer"].queryset)
        self.assertNotIn(inactive, form.fields["customer"].queryset)
        self.assertNotIn(self.other_customer, form.fields["customer"].queryset)
        self.assertEqual(form.initial["customer"], self.customer.pk)

    def test_cross_tenant_customer_and_missing_uuid_are_rejected(self):
        sale, series = self.sale(), self.series("F3")
        form = SubstituteSimplifiedDocumentForm(
            {"customer": self.other_customer.pk, "series": series.pk},
            business=self.business,
            sale=sale,
        )
        self.assertFalse(form.is_valid())
        self.assertIn("customer", form.errors)
        self.assertIn("idempotency_key", form.errors)


class SaleReturnRectificationFormTests(BillingFormsFixture):
    def test_f1_exposes_r1_and_f2_exposes_r5(self):
        r1, r5 = self.series("R1"), self.series("R5")
        sale_f1 = self.sale(RequestedDocumentTypeChoices.INVOICE, self.customer)
        self.issued_original(sale_f1, BillingDocumentTypeChoices.F1)
        form_f1 = SaleReturnRectificationForm(
            business=self.business, sale_return=self.completed_return(sale_f1)
        )
        self.assertQuerySetEqual(
            form_f1.fields["series"].queryset, [r1], transform=lambda x: x
        )
        sale_f2 = self.sale()
        self.issued_original(sale_f2, BillingDocumentTypeChoices.F2)
        form_f2 = SaleReturnRectificationForm(
            business=self.business, sale_return=self.completed_return(sale_f2)
        )
        self.assertQuerySetEqual(
            form_f2.fields["series"].queryset, [r5], transform=lambda x: x
        )

    def test_f2_companion_is_required_only_with_historical_f3(self):
        sale = self.sale(customer=self.customer)
        self.issued_original(sale, BillingDocumentTypeChoices.F2)
        return_doc = self.completed_return(sale)
        form = SaleReturnRectificationForm(
            business=self.business, sale_return=return_doc
        )
        self.assertFalse(form.fields["companion_f3_series"].required)
        substitute_simplified_document(
            business=self.business,
            sale_id=sale.pk,
            customer=self.customer,
            series_id=self.series("F3").pk,
            issued_by=self.user,
            idempotency_key=uuid.uuid4(),
        )
        companion = self.series("F3")
        form = SaleReturnRectificationForm(
            business=self.business, sale_return=return_doc
        )
        self.assertTrue(form.fields["companion_f3_series"].required)
        self.assertIn(companion, form.fields["companion_f3_series"].queryset)

    def test_missing_original_fails_closed_and_form_never_assigns_it(self):
        return_doc = self.completed_return(self.sale())
        key = uuid.uuid4()
        form = SaleReturnRectificationForm(
            {"idempotency_key": key}, business=self.business, sale_return=return_doc
        )
        self.assertFalse(form.is_valid())
        self.assertIn("__all__", form.errors)
        return_doc.refresh_from_db()
        self.assertIsNone(return_doc.original_billing_document_id)
