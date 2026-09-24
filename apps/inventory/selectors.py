"""Selectors del módulo inventory.

Los selectors contienen consultas reutilizables.

Regla:
- Aquí solo leemos datos.
- No modificamos stock.
- No creamos movimientos.
- Siempre filtramos por business.
"""

from django.db.models import Count, F, Q
from django.shortcuts import get_object_or_404

from apps.inventory.models import (
    InventoryItem,
    StockAdjustment,
    StockMovement,
)
from apps.stores.selectors import (
    get_stores_available_for_user,
    get_stores_for_business,
)
from apps.stores.models import Store


def get_inventory_visible_stores(user, *, only_active=None):
    """Stores visible in Inventory under its owner/manager/cashier contract."""
    if user is None or not user.is_authenticated or not user.is_active:
        return Store.objects.none()
    if user.is_superuser:
        stores = Store.objects.select_related("business")
        if only_active is True:
            stores = stores.filter(is_active=True)
        elif only_active is False:
            stores = stores.filter(is_active=False)
        return stores.order_by("name", "pk")
    if not getattr(user, "business_id", None):
        return get_stores_for_business(business=None)
    if user.role in {"owner", "manager"}:
        return get_stores_for_business(business=user.business, only_active=only_active)
    stores = get_stores_available_for_user(user=user, only_active=False)
    if only_active is True:
        stores = stores.filter(is_active=True)
    elif only_active is False:
        stores = stores.filter(is_active=False)
    return stores


def _scope_to_stores(queryset, stores):
    return queryset if stores is None else queryset.filter(store__in=stores)


# ==========================================================
# Dashboard
# ==========================================================


def get_inventory_dashboard_data(
    business,
    *,
    stores=None,
    latest_movements_limit=10,
    latest_adjustments_limit=10,
):
    """Construye el contexto del dashboard de inventario."""

    if business is None:
        return {
            "controlled_products": 0,
            "total_products_with_stock": 0,
            "low_stock_products": 0,
            "out_of_stock_products": 0,
            "healthy_stock_products": 0,
            "latest_movements": [],
            "latest_adjustments": [],
        }

    inventory_items = InventoryItem.objects.filter(
        business=business,
        is_active=True,
    ).annotate(
        available=F("current_stock") - F("reserved_stock"),
    )
    inventory_items = _scope_to_stores(inventory_items, stores)

    latest_movements = (
        StockMovement.objects.filter(
            business=business,
        )
        .select_related(
            "product",
            "store",
            "created_by",
        )
        .order_by("-occurred_at", "-created_at")
    )
    latest_movements = _scope_to_stores(latest_movements, stores)[
        :latest_movements_limit
    ]

    latest_adjustments = (
        StockAdjustment.objects.filter(
            business=business,
        )
        .select_related(
            "store",
            "created_by",
            "confirmed_by",
        )
        .order_by("-created_at")
    )
    latest_adjustments = _scope_to_stores(latest_adjustments, stores)[
        :latest_adjustments_limit
    ]

    return {
        "controlled_products": inventory_items.count(),
        # Backwards-compatible key for callers predating the workspace.
        "total_products_with_stock": inventory_items.count(),
        "low_stock_products": inventory_items.filter(
            available__gt=0,
            available__lte=F("minimum_stock"),
        ).count(),
        "out_of_stock_products": inventory_items.filter(
            available__lte=0,
        ).count(),
        "healthy_stock_products": inventory_items.filter(
            available__gt=F("minimum_stock"),
        ).count(),
        "latest_movements": latest_movements,
        "latest_adjustments": latest_adjustments,
    }


# ==========================================================
# InventoryItem
# ==========================================================


def get_inventory_items_for_business(business, filters=None, stores=None):
    """Devuelve fichas de inventario de un negocio."""

    if business is None:
        return InventoryItem.objects.none()

    filters = filters or {}

    queryset = (
        InventoryItem.objects.filter(
            business=business,
        )
        .select_related(
            "business",
            "store",
            "product",
            "product__category",
        )
        .annotate(
            available=F("current_stock") - F("reserved_stock"),
        )
        .order_by(
            "store__name",
            "product__name",
        )
    )
    queryset = _scope_to_stores(queryset, stores)

    store = filters.get("store")
    product = filters.get("product")
    is_active = filters.get("is_active")
    low_stock = filters.get("low_stock")
    out_of_stock = filters.get("out_of_stock")
    search = filters.get("search")
    stock_status = filters.get("stock_status")
    category = filters.get("category")
    location = filters.get("location")

    if search:
        queryset = queryset.filter(
            Q(product__name__icontains=search) | Q(product__sku__icontains=search)
        )
    if category:
        queryset = queryset.filter(product__category=category)
    if location:
        queryset = queryset.filter(location__icontains=location)
    if stock_status == "normal":
        queryset = queryset.filter(available__gt=F("minimum_stock"))
    elif stock_status == "low":
        queryset = queryset.filter(available__gt=0, available__lte=F("minimum_stock"))
    elif stock_status == "out":
        queryset = queryset.filter(available__lte=0)

    if store:
        queryset = queryset.filter(store=store)

    if product:
        queryset = queryset.filter(product=product)

    if is_active == "true":
        queryset = queryset.filter(is_active=True)

    if is_active == "false":
        queryset = queryset.filter(is_active=False)

    if low_stock:
        queryset = queryset.filter(
            available__gt=0,
            available__lte=F("minimum_stock"),
        )

    if out_of_stock:
        queryset = queryset.filter(
            available__lte=0,
        )

    return queryset


def get_inventory_item_detail(business, pk, stores=None):
    """Devuelve una ficha de inventario concreta."""

    queryset = InventoryItem.objects.select_related(
        "business",
        "store",
        "product",
    )
    queryset = _scope_to_stores(queryset, stores)
    return get_object_or_404(
        queryset,
        pk=pk,
        business=business,
    )


def get_low_stock_items(business):
    """Devuelve productos con stock bajo."""

    if business is None:
        return InventoryItem.objects.none()

    return (
        InventoryItem.objects.filter(
            business=business,
            is_active=True,
        )
        .annotate(
            available=F("current_stock") - F("reserved_stock"),
        )
        .filter(
            available__gt=0,
            available__lte=F("minimum_stock"),
        )
        .select_related(
            "store",
            "product",
        )
        .order_by(
            "store__name",
            "product__name",
        )
    )


def get_inventory_item_latest_movements(
    *,
    business,
    inventory_item,
    limit=20,
):
    """Devuelve últimos movimientos de una ficha de inventario."""

    return (
        StockMovement.objects.filter(
            business=business,
            inventory_item=inventory_item,
        )
        .select_related(
            "product",
            "store",
            "created_by",
        )
        .order_by("-occurred_at", "-created_at")[:limit]
    )


def get_inventory_item_movements(*, business, inventory_item):
    """Return the complete, optimized movement history for pagination."""

    return (
        StockMovement.objects.filter(
            business=business,
            inventory_item=inventory_item,
        )
        .select_related(
            "product",
            "store",
            "created_by",
            "sale",
            "sale_return",
            "purchase",
            "purchase_receipt",
            "stock_adjustment_line__adjustment",
        )
        .order_by("-occurred_at", "-created_at")
    )


def get_inventory_item_adjustments(*, business, inventory_item):
    """Return adjustment lines for one item without loading unrelated history."""

    return (
        inventory_item.adjustment_lines.filter(adjustment__business=business)
        .select_related("adjustment", "adjustment__created_by", "product")
        .order_by("-created_at")
    )


def get_inventory_item_adjustment_lines(
    *,
    business,
    inventory_item,
    limit=20,
):
    """Devuelve últimas líneas de ajuste relacionadas con una ficha."""

    return (
        inventory_item.adjustment_lines.filter(
            adjustment__business=business,
        )
        .select_related(
            "adjustment",
            "product",
        )
        .order_by("-created_at")[:limit]
    )


# ==========================================================
# StockMovement
# ==========================================================


def get_stock_movements_for_business(business, filters=None, stores=None):
    """Devuelve movimientos de stock de un negocio."""

    if business is None:
        return StockMovement.objects.none()

    filters = filters or {}

    queryset = (
        StockMovement.objects.filter(
            business=business,
        )
        .select_related(
            "business",
            "inventory_item",
            "product",
            "store",
            "created_by",
            "stock_adjustment_line",
            "stock_adjustment_line__adjustment",
            "sale",
            "sale_return",
            "purchase",
            "purchase_receipt",
        )
        .order_by("-occurred_at", "-created_at")
    )
    queryset = _scope_to_stores(queryset, stores)

    store = filters.get("store")
    product = filters.get("product")
    movement_type = filters.get("movement_type")
    reference_type = filters.get("reference_type")
    date_from = filters.get("date_from")
    date_to = filters.get("date_to")

    if store:
        queryset = queryset.filter(store=store)

    if product:
        queryset = queryset.filter(product=product)

    if movement_type:
        queryset = queryset.filter(movement_type=movement_type)

    if reference_type:
        queryset = queryset.filter(reference_type=reference_type)

    if date_from:
        queryset = queryset.filter(occurred_at__date__gte=date_from)

    if date_to:
        queryset = queryset.filter(occurred_at__date__lte=date_to)

    return queryset


def get_stock_movement_detail(business, pk, stores=None):
    """Devuelve un movimiento de stock concreto."""

    queryset = StockMovement.objects.select_related(
        "business",
        "inventory_item",
        "product",
        "store",
        "created_by",
        "stock_adjustment_line",
        "stock_adjustment_line__adjustment",
        "sale",
        "sale_return",
        "purchase",
        "purchase_receipt",
    )
    queryset = _scope_to_stores(queryset, stores)
    return get_object_or_404(
        queryset,
        pk=pk,
        business=business,
    )


# ==========================================================
# StockAdjustment
# ==========================================================


def get_stock_adjustments_for_business(business, filters=None, stores=None):
    """Devuelve ajustes de stock de un negocio."""

    if business is None:
        return StockAdjustment.objects.none()

    filters = filters or {}

    queryset = (
        StockAdjustment.objects.filter(
            business=business,
        )
        .select_related(
            "business",
            "store",
            "created_by",
            "confirmed_by",
        )
        .annotate(line_count=Count("lines"))
        .order_by("-created_at")
    )
    queryset = _scope_to_stores(queryset, stores)

    store = filters.get("store")
    status = filters.get("status")
    reason = filters.get("reason")
    date_from = filters.get("date_from")
    date_to = filters.get("date_to")

    if store:
        queryset = queryset.filter(store=store)

    if status:
        queryset = queryset.filter(status=status)

    if reason:
        queryset = queryset.filter(reason=reason)

    if date_from:
        queryset = queryset.filter(created_at__date__gte=date_from)

    if date_to:
        queryset = queryset.filter(created_at__date__lte=date_to)

    return queryset


def get_stock_adjustment_detail(business, pk, stores=None):
    """Devuelve un ajuste de stock concreto."""

    queryset = StockAdjustment.objects.select_related(
        "business",
        "store",
        "created_by",
        "confirmed_by",
    ).prefetch_related(
        "lines",
    )
    queryset = _scope_to_stores(queryset, stores)
    return get_object_or_404(
        queryset,
        pk=pk,
        business=business,
    )


def get_stock_adjustment_lines(stock_adjustment):
    """Devuelve líneas de un ajuste."""

    return stock_adjustment.lines.select_related(
        "inventory_item",
        "product",
    ).order_by("product__name")
