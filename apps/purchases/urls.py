from django.urls import path

from apps.purchases import views

app_name = "purchases"

urlpatterns = [
    path("suppliers/", views.SupplierListView.as_view(), name="supplier_list"),
    path(
        "suppliers/create/", views.SupplierCreateView.as_view(), name="supplier_create"
    ),
    path(
        "suppliers/<int:pk>/edit/",
        views.SupplierUpdateView.as_view(),
        name="supplier_update",
    ),
    path("", views.PurchaseListView.as_view(), name="purchase_list"),
    path("create/", views.PurchaseCreateView.as_view(), name="purchase_create"),
    path("<int:pk>/", views.PurchaseDetailView.as_view(), name="purchase_detail"),
    path("<int:pk>/edit/", views.PurchaseUpdateView.as_view(), name="purchase_update"),
    path("<int:pk>/order/", views.PurchaseOrderView.as_view(), name="purchase_order"),
    path(
        "<int:pk>/cancel/", views.PurchaseCancelView.as_view(), name="purchase_cancel"
    ),
    path(
        "<int:pk>/receive/",
        views.PurchaseReceiptCreateView.as_view(),
        name="purchase_receive",
    ),
    path(
        "<int:purchase_pk>/lines/create/",
        views.PurchaseLineCreateView.as_view(),
        name="purchase_line_create",
    ),
    path(
        "<int:purchase_pk>/lines/<int:line_pk>/edit/",
        views.PurchaseLineUpdateView.as_view(),
        name="purchase_line_update",
    ),
    path(
        "<int:purchase_pk>/lines/<int:line_pk>/delete/",
        views.PurchaseLineDeleteView.as_view(),
        name="purchase_line_delete",
    ),
]
