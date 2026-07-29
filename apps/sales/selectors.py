from django.db.models import Q

from .models import Sale, SaleReturn


def sale_list(*, business, store, filters=None):
    queryset = Sale.objects.filter(business=business, store=store).select_related(
        "customer", "created_by"
    )
    filters = filters or {}
    if filters.get("status"):
        queryset = queryset.filter(status=filters["status"])
    if filters.get("query"):
        queryset = queryset.filter(
            Q(notes__icontains=filters["query"])
            | Q(customer__name__icontains=filters["query"])
        )
    return queryset.order_by("-created_at")


def sale_get(*, business, store, sale_pk):
    return (
        Sale.objects.filter(business=business, store=store)
        .select_related("customer", "cash_register", "cash_session")
        .prefetch_related("lines__product")
        .get(pk=sale_pk)
    )


def sale_return_list(*, business, store, filters=None):
    queryset = SaleReturn.objects.filter(business=business, store=store).select_related(
        "sale", "created_by"
    )
    if filters and filters.get("status"):
        queryset = queryset.filter(status=filters["status"])
    return queryset.order_by("-created_at")


def sale_return_get(*, business, store, return_pk):
    return (
        SaleReturn.objects.filter(business=business, store=store)
        .select_related("sale")
        .prefetch_related("lines__sale_line")
        .get(pk=return_pk)
    )
