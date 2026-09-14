"""Consultas read-only y tenant-scoped del módulo Purchases."""

from django.db.models import Prefetch, Q
from django.shortcuts import get_object_or_404

from apps.purchases.models import Purchase, PurchaseLine, PurchaseReceipt, Supplier
from apps.stores.models import Store
from apps.users.helpers import is_owner


def _positive_pk(value):
    """Normaliza filtros HTTP de PK sin permitir errores ni ampliar resultados."""

    if hasattr(value, "pk"):
        value = value.pk
    try:
        value = int(value)
    except (TypeError, ValueError):
        return None
    return value if value > 0 else None


def get_suppliers_for_business(*, business, query="", status="active"):
    qs = Supplier.objects.filter(business=business)
    if status == "active":
        qs = qs.filter(is_active=True)
    elif status == "inactive":
        qs = qs.filter(is_active=False)
    query = (query or "").strip()
    if query:
        qs = qs.filter(
            Q(name__icontains=query)
            | Q(legal_name__icontains=query)
            | Q(tax_identifier__icontains=query)
            | Q(email__icontains=query)
            | Q(phone__icontains=query)
        )
    return qs.order_by("name", "pk")


def get_supplier_detail(*, business, pk):
    return get_object_or_404(Supplier, business=business, pk=pk)


def get_accessible_purchase_stores(*, business, user, active_only=False):
    qs = Store.objects.filter(business=business)
    if not (user.is_superuser or is_owner(user)):
        qs = qs.filter(user_accesses__user=user, user_accesses__is_active=True)
    if active_only:
        qs = qs.filter(is_active=True)
    return qs.distinct().order_by("name", "pk")


def get_purchases_for_user(
    *, business, user, query="", status="", store=None, supplier=None
):
    qs = Purchase.objects.filter(
        business=business,
        store__in=get_accessible_purchase_stores(business=business, user=user),
    ).select_related("store", "supplier", "created_by")
    valid_statuses = {
        value for value, _label in Purchase._meta.get_field("status").choices
    }
    if status in valid_statuses:
        qs = qs.filter(status=status)
    if store:
        store_id = _positive_pk(store)
        if store_id is None:
            return qs.none()
        qs = qs.filter(store_id=store_id)
    if supplier:
        supplier_id = _positive_pk(supplier)
        if supplier_id is None:
            return qs.none()
        qs = qs.filter(supplier_id=supplier_id)
    query = (query or "").strip()
    if query:
        qs = qs.filter(
            Q(reference__icontains=query)
            | Q(supplier__name__icontains=query)
            | Q(supplier__legal_name__icontains=query)
            | Q(supplier__tax_identifier__icontains=query)
        )
    return qs.order_by("-created_at", "-pk")


def get_purchase_detail(*, business, user, pk):
    receipt_qs = PurchaseReceipt.objects.select_related("received_by").prefetch_related(
        "lines__purchase_line"
    )
    return get_object_or_404(
        get_purchases_for_user(business=business, user=user).prefetch_related(
            Prefetch("lines", queryset=PurchaseLine.objects.select_related("product")),
            Prefetch("receipts", queryset=receipt_qs),
        ),
        pk=pk,
    )


def get_purchase_lines(*, business, purchase):
    return PurchaseLine.objects.filter(
        business=business, purchase=purchase
    ).select_related("product")


def get_purchase_receipts(*, business, purchase):
    return (
        PurchaseReceipt.objects.filter(business=business, purchase=purchase)
        .select_related("received_by")
        .prefetch_related("lines__purchase_line")
    )
