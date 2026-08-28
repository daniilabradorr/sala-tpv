"""HTTP input validation for billing queries and commands."""

from django import forms
from django.core.exceptions import ValidationError
from django.utils import timezone

from apps.billing.models import (
    BillingDocumentRelationTypeChoices,
    BillingDocumentStatusChoices,
    BillingDocumentTypeChoices,
    BillingSeries,
)
from apps.billing.selectors import (
    active_billing_series,
    issued_billing_document,
    issued_original_documents_for_sale,
)
from apps.customers.models import Customer
from apps.sales.models import RequestedDocumentTypeChoices


class BillingDocumentFilterForm(forms.Form):
    customer = forms.ModelChoiceField(Customer.objects.none(), required=False)
    document_type = forms.ChoiceField(
        choices=[("", "Todos"), *BillingDocumentTypeChoices.choices], required=False
    )
    status = forms.ChoiceField(
        choices=[("", "Todos"), *BillingDocumentStatusChoices.choices], required=False
    )
    date_from = forms.DateField(
        required=False, widget=forms.DateInput(attrs={"type": "date"})
    )
    date_to = forms.DateField(
        required=False, widget=forms.DateInput(attrs={"type": "date"})
    )

    def __init__(self, *args, business, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["customer"].queryset = Customer.objects.filter(business=business)

    def clean(self):
        cleaned_data = super().clean()
        date_from = cleaned_data.get("date_from")
        date_to = cleaned_data.get("date_to")
        if date_from and date_to and date_from > date_to:
            raise ValidationError("La fecha inicial no puede ser posterior a la final.")
        return cleaned_data


class IssueSaleDocumentForm(forms.Form):
    series = forms.ModelChoiceField(BillingSeries.objects.none())
    idempotency_key = forms.UUIDField(widget=forms.HiddenInput())

    def __init__(self, *args, business, sale, **kwargs):
        super().__init__(*args, **kwargs)
        expected_type = (
            BillingDocumentTypeChoices.F1
            if sale.document_type_requested == RequestedDocumentTypeChoices.INVOICE
            else BillingDocumentTypeChoices.F2
        )
        self.fields["series"].queryset = active_billing_series(
            business=business,
            document_type=expected_type,
            year=timezone.localdate().year,
            store=sale.store,
            cash_register=sale.cash_register,
        )


class SubstituteSimplifiedDocumentForm(forms.Form):
    customer = forms.ModelChoiceField(Customer.objects.none())
    series = forms.ModelChoiceField(BillingSeries.objects.none())
    idempotency_key = forms.UUIDField(widget=forms.HiddenInput())

    def __init__(self, *args, business, sale, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["customer"].queryset = Customer.objects.filter(
            business=business, is_active=True
        )
        self.fields["series"].queryset = active_billing_series(
            business=business,
            document_type=BillingDocumentTypeChoices.F3,
            year=timezone.localdate().year,
            store=sale.store,
            cash_register=sale.cash_register,
        )
        if not self.is_bound and sale.customer_id and sale.customer.is_active:
            self.initial.setdefault("customer", sale.customer_id)


class SaleReturnRectificationForm(forms.Form):
    series = forms.ModelChoiceField(BillingSeries.objects.none())
    companion_f3_series = forms.ModelChoiceField(
        BillingSeries.objects.none(), required=False
    )
    idempotency_key = forms.UUIDField(widget=forms.HiddenInput())

    def __init__(self, *args, business, sale_return, **kwargs):
        super().__init__(*args, **kwargs)
        self._history_error = None
        self._companion_required = False
        sale = sale_return.original_sale
        candidates = []
        if sale_return.original_billing_document_id:
            candidate = issued_billing_document(
                business=business,
                document_id=sale_return.original_billing_document_id,
            )
            if (
                candidate
                and candidate.sale_id == sale.pk
                and candidate.document_type
                in [BillingDocumentTypeChoices.F1, BillingDocumentTypeChoices.F2]
            ):
                candidates = [candidate]
        else:
            candidates = list(
                issued_original_documents_for_sale(business=business, sale=sale).filter(
                    document_type__in=[
                        BillingDocumentTypeChoices.F1,
                        BillingDocumentTypeChoices.F2,
                    ]
                )[:2]
            )
        if len(candidates) != 1:
            self._history_error = (
                "No se puede determinar un único documento fiscal original."
            )
            return
        candidate = candidates[0]
        document_type = (
            BillingDocumentTypeChoices.R1
            if candidate.document_type == BillingDocumentTypeChoices.F1
            else BillingDocumentTypeChoices.R5
        )
        self.fields["series"].queryset = active_billing_series(
            business=business,
            document_type=document_type,
            year=timezone.localdate().year,
            store=sale.store,
            cash_register=sale.cash_register,
        )
        if candidate.document_type == BillingDocumentTypeChoices.F2:
            substitutions = list(
                candidate.incoming_relations.filter(
                    relation_type=BillingDocumentRelationTypeChoices.SUBSTITUTES,
                    source_document__status=BillingDocumentStatusChoices.ISSUED,
                    source_document__document_type=BillingDocumentTypeChoices.F3,
                )[:2]
            )
            if len(substitutions) > 1:
                self._history_error = (
                    "El historial fiscal contiene varias F3 sustitutivas."
                )
                self.fields["series"].queryset = BillingSeries.objects.none()
                return
            self._companion_required = len(substitutions) == 1
            if self._companion_required:
                self.fields["companion_f3_series"].required = True
                self.fields["companion_f3_series"].queryset = active_billing_series(
                    business=business,
                    document_type=BillingDocumentTypeChoices.F3,
                    year=timezone.localdate().year,
                    store=sale.store,
                    cash_register=sale.cash_register,
                )

    def clean(self):
        cleaned_data = super().clean()
        if self._history_error:
            raise ValidationError(self._history_error)
        if not self._companion_required and cleaned_data.get("companion_f3_series"):
            self.add_error(
                "companion_f3_series", "Esta serie complementaria no procede."
            )
        return cleaned_data
