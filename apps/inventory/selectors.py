"""Selectors del módulo inventory.

Los selectors contienen consultas reutilizables.

Regla:
- Aquí solo leemos datos.
- No modificamos stock.
- No creamos movimientos.
- Siempre filtramos por business.
"""

from django.db.models import F
from django.shortcuts import get_object_or_404

from apps.inventory.models import (
    InventoryItem,
    StockAdjustment,
    StockMovement,
)


# ==========================================================
# Dashboard
# ==========================================================


def get_inventory_dashboard_data(
    business,
    *,
    latest_movements_limit=10,
    latest_adjustments_limit=10,
):
    """Construye el contexto del dashboard de inventario."""

    if business is None:
        return {
            "total_products_with_stock": 0,
            "low_stock_products": 0,
            "out_of_stock_products": 0,
            "latest_movements": [],
            "latest_adjustments": [],
        }

    inventory_items = InventoryItem.objects.filter(
        business=business,
        is_active=True,
    ).annotate(
        available=F("current_stock") - F("reserved_stock"),
    )

    latest_movements = (
        StockMovement.objects.filter(
            business=business,
        )
        .select_related(
            "product",
            "store",
            "created_by",
        )
        .order_by("-occurred_at", "-created_at")[:latest_movements_limit]
    )

    latest_adjustments = (
        StockAdjustment.objects.filter(
            business=business,
        )
        .select_related(
            "store",
            "created_by",
            "confirmed_by",
        )
        .order_by("-created_at")[:latest_adjustments_limit]
    )

    return {
        "total_products_with_stock": inventory_items.filter(
            available__gt=0,
        ).count(),
        "low_stock_products": inventory_items.filter(
            available__gt=0,
            available__lte=F("minimum_stock"),
        ).count(),
        "out_of_stock_products": inventory_items.filter(
            available__lte=0,
        ).count(),
        "latest_movements": latest_movements,
        "latest_adjustments": latest_adjustments,
    }


# ==========================================================
# InventoryItem
# ==========================================================


def get_inventory_items_for_business(business, filters=None):
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
        )
        .annotate(
            available=F("current_stock") - F("reserved_stock"),
        )
        .order_by(
            "store__name",
            "product__name",
        )
    )

    store = filters.get("store")
    product = filters.get("product")
    is_active = filters.get("is_active")
    low_stock = filters.get("low_stock")
    out_of_stock = filters.get("out_of_stock")

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


def get_inventory_item_detail(business, pk):
    """Devuelve una ficha de inventario concreta."""

    return get_object_or_404(
        InventoryItem.objects.select_related(
            "business",
            "store",
            "product",
        ),
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


def get_stock_movements_for_business(business, filters=None):
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
        )
        .order_by("-occurred_at", "-created_at")
    )

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


def get_stock_movement_detail(business, pk):
    """Devuelve un movimiento de stock concreto."""

    return get_object_or_404(
        StockMovement.objects.select_related(
            "business",
            "inventory_item",
            "product",
            "store",
            "created_by",
            "stock_adjustment_line",
        ),
        pk=pk,
        business=business,
    )


# ==========================================================
# StockAdjustment
# ==========================================================


def get_stock_adjustments_for_business(business, filters=None):
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
        .order_by("-created_at")
    )

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


def get_stock_adjustment_detail(business, pk):
    """Devuelve un ajuste de stock concreto."""

    return get_object_or_404(
        StockAdjustment.objects.select_related(
            "business",
            "store",
            "created_by",
            "confirmed_by",
        ).prefetch_related(
            "lines",
        ),
        pk=pk,
        business=business,
    )


def get_stock_adjustment_lines(stock_adjustment):
    """Devuelve líneas de un ajuste."""

    return stock_adjustment.lines.select_related(
        "inventory_item",
        "product",
    ).order_by("product__name")
