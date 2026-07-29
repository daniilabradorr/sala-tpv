from django.urls import path

from apps.sales import views


app_name = "sales"

urlpatterns = [
    path(
        "stores/<int:store_id>/sales/", views.SaleListView.as_view(), name="sale_list"
    ),
    path(
        "stores/<int:store_id>/sales/open/",
        views.SaleOpenView.as_view(),
        name="sale_open",
    ),
    path(
        "stores/<int:store_id>/sales/<int:sale_pk>/",
        views.SaleDetailView.as_view(),
        name="sale_detail",
    ),
    path(
        "stores/<int:store_id>/sales/<int:sale_pk>/header/",
        views.SaleHeaderUpdateView.as_view(),
        name="sale_header_update",
    ),
    path(
        "stores/<int:store_id>/sales/<int:sale_pk>/lines/add/",
        views.SaleLineAddView.as_view(),
        name="sale_line_add",
    ),
    path(
        "stores/<int:store_id>/sales/<int:sale_pk>/lines/<int:line_pk>/edit/",
        views.SaleLineUpdateView.as_view(),
        name="sale_line_update",
    ),
    path(
        "stores/<int:store_id>/sales/<int:sale_pk>/lines/<int:line_pk>/delete/",
        views.SaleLineDeleteView.as_view(),
        name="sale_line_delete",
    ),
    path(
        "stores/<int:store_id>/sales/<int:sale_pk>/complete/",
        views.SaleCompleteView.as_view(),
        name="sale_complete",
    ),
    path(
        "stores/<int:store_id>/sales/<int:sale_pk>/cancel/",
        views.SaleCancelView.as_view(),
        name="sale_cancel",
    ),
    path(
        "stores/<int:store_id>/returns/",
        views.SaleReturnListView.as_view(),
        name="return_list",
    ),
    path(
        "stores/<int:store_id>/sales/<int:sale_pk>/returns/create/",
        views.SaleReturnCreateView.as_view(),
        name="return_create",
    ),
    path(
        "stores/<int:store_id>/returns/<int:return_pk>/",
        views.SaleReturnDetailView.as_view(),
        name="return_detail",
    ),
    path(
        "stores/<int:store_id>/returns/<int:return_pk>/lines/add/",
        views.SaleReturnLineAddView.as_view(),
        name="return_line_add",
    ),
    path(
        "stores/<int:store_id>/returns/<int:return_pk>/lines/<int:line_pk>/edit/",
        views.SaleReturnLineUpdateView.as_view(),
        name="return_line_update",
    ),
    path(
        "stores/<int:store_id>/returns/<int:return_pk>/lines/<int:line_pk>/delete/",
        views.SaleReturnLineDeleteView.as_view(),
        name="return_line_delete",
    ),
    path(
        "stores/<int:store_id>/returns/<int:return_pk>/complete/",
        views.SaleReturnCompleteView.as_view(),
        name="return_complete",
    ),
    path(
        "stores/<int:store_id>/returns/<int:return_pk>/cancel/",
        views.SaleReturnCancelView.as_view(),
        name="return_cancel",
    ),
]
