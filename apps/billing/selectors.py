"""Side-effect-free, tenant-scoped Billing queries."""

import re

from django.db.models import Exists, OuterRef, Prefetch, Q
from django.shortcuts import get_object_or_404

from apps.billing.models import (
    BillingDocument,
    BillingDocumentRelation,
    BillingDocumentStatusChoices,
    BillingDocumentTypeChoices,
    BillingSeries,
)

_UNSET = object()


def _billing_document_base_queryset():
    return BillingDocument.objects.select_related(
        "series", "store", "customer", "issued_by"
    )


def _document_detail_queryset():
    relations = BillingDocumentRelation.objects.select_related(
        "source_document",
        "source_document__series",
        "target_document",
        "target_document__series",
    )
    return (
        _billing_document_base_queryset()
        .select_related(
            "business", "sale", "sale_return", "cash_register", "cash_session"
        )
        .prefetch_related(
            "lines",
            "tax_breakdowns",
            Prefetch("outgoing_relations", queryset=relations),
            Prefetch("incoming_relations", queryset=relations),
        )
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
    q=None,
):
    if business is None:
        return BillingDocument.objects.none()
    queryset = _billing_document_base_queryset().filter(business=business)
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
    if q:
        query = q.strip()
        search = (
            Q(series_text__icontains=query)
            | Q(recipient_name__icontains=query)
            | Q(recipient_legal_name__icontains=query)
            | Q(recipient_tax_identifier__icontains=query)
        )
        if query.isdigit():
            search |= Q(number=int(query))
        full_number = re.match(r"^(?P<series>.+)-(?P<number>\d+)$", query)
        if full_number:
            search |= Q(
                series_text__iexact=full_number.group("series"),
                number=int(full_number.group("number")),
            )
        queryset = queryset.filter(search)
    return queryset


def billing_document_detail(*, business, document_id):
    return get_object_or_404(
        _document_detail_queryset(), business=business, pk=document_id
    )


def issued_billing_document(*, business, document_id):
    """Return one tenant-scoped issued document, or ``None`` when unavailable."""
    if business is None or document_id is None:
        return None
    return (
        _document_detail_queryset()
        .filter(
            business=business,
            pk=document_id,
            status=BillingDocumentStatusChoices.ISSUED,
        )
        .first()
    )


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


def billing_series_list(
    *, business, store, year=None, document_type=None, status="all"
):
    """Return store-scoped administrative series with usage annotated."""
    if business is None or store is None:
        return BillingSeries.objects.none()
    issued = BillingDocument.objects.filter(
        series_id=OuterRef("pk"), status=BillingDocumentStatusChoices.ISSUED
    )
    queryset = (
        BillingSeries.objects.filter(business=business, store=store)
        .select_related("store", "cash_register")
        .annotate(has_issued_documents=Exists(issued))
    )
    if year:
        queryset = queryset.filter(year=year)
    if document_type in BillingDocumentTypeChoices.values:
        queryset = queryset.filter(document_type=document_type)
    if status == "active":
        queryset = queryset.filter(is_active=True)
    elif status == "inactive":
        queryset = queryset.filter(is_active=False)
    return queryset


def billing_series_detail(*, business, store, series_id):
    return get_object_or_404(
        billing_series_list(business=business, store=store), pk=series_id
    )
