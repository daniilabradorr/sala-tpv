"""Side-effect-free, tenant-scoped Billing queries."""

from django.db.models import Prefetch, Q
from django.shortcuts import get_object_or_404

from apps.billing.models import (
    BillingDocument,
    BillingDocumentRelation,
    BillingDocumentStatusChoices,
    BillingDocumentTypeChoices,
    BillingSeries,
)

_UNSET = object()


def _document_queryset():
    relations = BillingDocumentRelation.objects.select_related(
        "source_document", "target_document"
    )
    return BillingDocument.objects.select_related(
        "business", "series", "store", "customer", "sale", "sale_return", "issued_by"
    ).prefetch_related(
        "lines",
        "tax_breakdowns",
        Prefetch("outgoing_relations", queryset=relations),
        Prefetch("incoming_relations", queryset=relations),
    )


def billing_document_list(
    *,
    business,
    store=None,
    customer=None,
    sale=None,
    document_type=None,
    status=None,
    date_from=None,
    date_to=None,
):
    if business is None:
        return BillingDocument.objects.none()
    queryset = _document_queryset().filter(business=business)
    if store is not None:
        queryset = queryset.filter(store=store)
    if customer is not None:
        queryset = queryset.filter(customer=customer)
    if sale is not None:
        queryset = queryset.filter(sale=sale)
    if document_type in BillingDocumentTypeChoices.values:
        queryset = queryset.filter(document_type=document_type)
    if status in BillingDocumentStatusChoices.values:
        queryset = queryset.filter(status=status)
    if date_from is not None:
        queryset = queryset.filter(operation_date__gte=date_from)
    if date_to is not None:
        queryset = queryset.filter(operation_date__lte=date_to)
    return queryset


def billing_document_detail(*, business, document_id):
    return get_object_or_404(_document_queryset(), business=business, pk=document_id)


def billing_documents_for_sale(*, business, sale):
    return billing_document_list(business=business, sale=sale)


def billing_documents_for_customer(*, business, customer):
    return billing_document_list(business=business, customer=customer)


def billing_documents_for_sale_return(*, business, sale_return):
    return billing_document_list(business=business).filter(sale_return=sale_return)


def issued_original_documents_for_sale(*, business, sale):
    return billing_document_list(
        business=business, sale=sale, status=BillingDocumentStatusChoices.ISSUED
    ).filter(
        document_type__in=[
            BillingDocumentTypeChoices.F1,
            BillingDocumentTypeChoices.F2,
            BillingDocumentTypeChoices.F3,
        ]
    )


def active_billing_series(
    *, business, document_type, year, store=_UNSET, cash_register=_UNSET
):
    if business is None:
        return BillingSeries.objects.none()
    queryset = BillingSeries.objects.filter(
        business=business, is_active=True, document_type=document_type, year=year
    ).select_related("store", "cash_register")
    if store is None:
        queryset = queryset.filter(store__isnull=True)
    elif store is not _UNSET:
        queryset = queryset.filter(Q(store__isnull=True) | Q(store=store))
    if cash_register is None:
        queryset = queryset.filter(cash_register__isnull=True)
    elif cash_register is not _UNSET:
        queryset = queryset.filter(
            Q(cash_register__isnull=True) | Q(cash_register=cash_register)
        )
    return queryset
