"""HTTP input validation for billing queries and commands."""

from django import forms
from django.core.exceptions import ValidationError
from django.db.models import Q
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


def _configure_single_series(form, field_name="series"):
    field = form.fields[field_name]
    candidates = list(field.queryset[:2])
    if len(candidates) == 1:
        form.initial.setdefault(field_name, candidates[0].pk)
        field.widget = forms.HiddenInput()
        setattr(form, f"single_{field_name}", candidates[0])


class BillingDocumentFilterForm(forms.Form):
    q = forms.CharField(required=False, label="Buscar", max_length=180)
    customer = forms.ModelChoiceField(
        Customer.objects.none(), required=False, label="Cliente"
    )
    document_type = forms.ChoiceField(
        choices=[("", "Todos"), *BillingDocumentTypeChoices.choices],
        required=False,
        label="Tipo de documento",
    )
    status = forms.ChoiceField(
        choices=[("", "Todos"), *BillingDocumentStatusChoices.choices],
        required=False,
        label="Estado",
    )
    date_from = forms.DateField(
        required=False,
        label="Desde",
        widget=forms.DateInput(attrs={"type": "date"}),
    )
    date_to = forms.DateField(
        required=False,
        label="Hasta",
        widget=forms.DateInput(attrs={"type": "date"}),
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


class BillingSeriesFilterForm(forms.Form):
    year = forms.IntegerField(required=False, label="Año", min_value=1)
    document_type = forms.ChoiceField(
        required=False,
        label="Tipo",
        choices=[("", "Todos"), *BillingDocumentTypeChoices.choices],
    )
    status = forms.ChoiceField(
        required=False,
        label="Estado",
        initial="all",
        choices=[("all", "Todas"), ("active", "Activas"), ("inactive", "Inactivas")],
    )


class BillingSeriesForm(forms.Form):
    document_type = forms.ChoiceField(
        label="Tipo de documento", choices=BillingDocumentTypeChoices.choices
    )
    name = forms.CharField(label="Nombre", max_length=150)
    prefix = forms.CharField(label="Prefijo", max_length=50)
    year = forms.IntegerField(label="Año", min_value=1)
    padding = forms.IntegerField(label="Dígitos", min_value=1, max_value=12)
    cash_register = forms.ModelChoiceField(
        queryset=BillingSeries.objects.none(), required=False, label="Caja específica"
    )

    def __init__(self, *args, business, store, instance=None, **kwargs):
        super().__init__(*args, **kwargs)
        from apps.cash_register.models import CashRegister

        queryset = CashRegister.objects.filter(business=business, store=store)
        if instance and instance.cash_register_id:
            queryset = queryset.filter(
                Q(is_active=True) | Q(pk=instance.cash_register_id)
            )
        else:
            queryset = queryset.filter(is_active=True)
        self.fields["cash_register"].queryset = queryset
        self.fields["cash_register"].empty_label = "Ninguna específica"
        if instance:
            for field in self.fields:
                self.initial.setdefault(field, getattr(instance, field))
            if instance.has_issued_documents:
                for field in (
                    "document_type",
                    "prefix",
                    "year",
                    "padding",
                    "cash_register",
                ):
                    self.fields.pop(field)
        else:
            self.initial.setdefault("year", timezone.localdate().year)
            self.initial.setdefault("padding", 6)


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
        self.document_type = expected_type
        self.fields["series"].queryset = active_billing_series(
            business=business,
            document_type=expected_type,
            year=timezone.localdate().year,
            store=sale.store,
            cash_register=sale.cash_register,
        )
        _configure_single_series(self)


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
        originals = list(
            issued_original_documents_for_sale(business=business, sale=sale).filter(
                document_type=BillingDocumentTypeChoices.F2
            )[:2]
        )
        self.original_document = originals[0] if len(originals) == 1 else None
        if not self.is_bound and sale.customer_id and sale.customer.is_active:
            self.initial.setdefault("customer", sale.customer_id)
        _configure_single_series(self)


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
        self.companion_required = False
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
        self.original_document = candidate
        self.document_type = document_type
        self.fields["series"].queryset = active_billing_series(
            business=business,
            document_type=document_type,
            year=timezone.localdate().year,
            store=sale.store,
            cash_register=sale.cash_register,
        )
        series_ids = list(
            self.fields["series"].queryset.values_list("pk", flat=True)[:2]
        )
        if len(series_ids) == 1:
            self.initial.setdefault("series", series_ids[0])
            _configure_single_series(self)
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
            self.companion_required = self._companion_required
            if self._companion_required:
                self.fields["companion_f3_series"].required = True
                self.fields["companion_f3_series"].queryset = active_billing_series(
                    business=business,
                    document_type=BillingDocumentTypeChoices.F3,
                    year=timezone.localdate().year,
                    store=sale.store,
                    cash_register=sale.cash_register,
                )
                companion_ids = list(
                    self.fields["companion_f3_series"].queryset.values_list(
                        "pk", flat=True
                    )[:2]
                )
                if len(companion_ids) == 1:
                    self.initial.setdefault("companion_f3_series", companion_ids[0])
                    _configure_single_series(self, "companion_f3_series")

    def clean(self):
        cleaned_data = super().clean()
        if self._history_error:
            raise ValidationError(self._history_error)
        if not self._companion_required and cleaned_data.get("companion_f3_series"):
            self.add_error(
                "companion_f3_series", "Esta serie complementaria no procede."
            )
        return cleaned_data
