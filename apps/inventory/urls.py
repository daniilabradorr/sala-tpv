from django.urls import path

from apps.inventory.views import (
    InventoryDashboardView,
    InventoryInitialStockView,
    InventoryItemCreateView,
    InventoryItemDetailView,
    InventoryItemListView,
    InventoryItemUpdateView,
    StockAdjustmentCancelView,
    StockAdjustmentConfirmView,
    StockAdjustmentCreateView,
    StockAdjustmentDetailView,
    StockAdjustmentLineCreateView,
    StockAdjustmentLineDeleteView,
    StockAdjustmentLineUpdateView,
    StockAdjustmentListView,
    StockMovementDetailView,
    StockMovementListView,
)


app_name = "inventory"


urlpatterns = [
    path("", InventoryDashboardView.as_view(), name="dashboard"),
    # Items de inventario
    path("items/", InventoryItemListView.as_view(), name="item_list"),
    path("items/create/", InventoryItemCreateView.as_view(), name="item_create"),
    path("items/<int:pk>/", InventoryItemDetailView.as_view(), name="item_detail"),
    path("items/<int:pk>/edit/", InventoryItemUpdateView.as_view(), name="item_update"),
    path(
        "items/<int:pk>/initial-stock/",
        InventoryInitialStockView.as_view(),
        name="item_initial_stock",
    ),
    # Movimientos de stock
    path(
        "movements/",
        StockMovementListView.as_view(),
        name="stock_movement_list",
    ),
    path(
        "movements/<int:pk>/",
        StockMovementDetailView.as_view(),
        name="stock_movement_detail",
    ),
    # Ajustes de stock
    path(
        "adjustments/",
        StockAdjustmentListView.as_view(),
        name="stock_adjustment_list",
    ),
    path(
        "adjustments/create/",
        StockAdjustmentCreateView.as_view(),
        name="stock_adjustment_create",
    ),
    path(
        "adjustments/<int:pk>/",
        StockAdjustmentDetailView.as_view(),
        name="stock_adjustment_detail",
    ),
    # Líneas de ajuste
    path(
        "adjustments/<int:adjustment_pk>/lines/create/",
        StockAdjustmentLineCreateView.as_view(),
        name="stock_adjustment_line_create",
    ),
    path(
        "adjustments/<int:adjustment_pk>/lines/<int:line_pk>/edit/",
        StockAdjustmentLineUpdateView.as_view(),
        name="stock_adjustment_line_update",
    ),
    path(
        "adjustments/<int:adjustment_pk>/lines/<int:line_pk>/delete/",
        StockAdjustmentLineDeleteView.as_view(),
        name="stock_adjustment_line_delete",
    ),
    # Acciones de ajuste
    path(
        "adjustments/<int:pk>/confirm/",
        StockAdjustmentConfirmView.as_view(),
        name="stock_adjustment_confirm",
    ),
    path(
        "adjustments/<int:pk>/cancel/",
        StockAdjustmentCancelView.as_view(),
        name="stock_adjustment_cancel",
    ),
]
