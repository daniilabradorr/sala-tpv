from django.urls import path

from apps.billing import views

app_name = "billing"

urlpatterns = [
    path(
        "stores/<int:store_id>/documents/<int:document_pk>/print/",
        views.BillingDocumentPrintView.as_view(),
        name="document_print",
    ),
    path(
        "stores/<int:store_id>/documents/",
        views.BillingDocumentListView.as_view(),
        name="document_list",
    ),
    path(
        "stores/<int:store_id>/series/",
        views.BillingSeriesListView.as_view(),
        name="series_list",
    ),
    path(
        "stores/<int:store_id>/series/new/",
        views.BillingSeriesFormView.as_view(),
        name="series_create",
    ),
    path(
        "stores/<int:store_id>/series/<int:series_pk>/",
        views.BillingSeriesDetailView.as_view(),
        name="series_detail",
    ),
    path(
        "stores/<int:store_id>/series/<int:series_pk>/edit/",
        views.BillingSeriesFormView.as_view(),
        name="series_edit",
    ),
    path(
        "stores/<int:store_id>/series/<int:series_pk>/<str:action>/",
        views.BillingSeriesToggleView.as_view(),
        name="series_toggle",
    ),
    path(
        "stores/<int:store_id>/documents/<int:document_pk>/",
        views.BillingDocumentDetailView.as_view(),
        name="document_detail",
    ),
    path(
        "stores/<int:store_id>/sales/<int:sale_pk>/issue/",
        views.IssueSaleDocumentView.as_view(),
        name="issue_sale_document",
    ),
    path(
        "stores/<int:store_id>/sales/<int:sale_pk>/substitute/",
        views.SubstituteSimplifiedDocumentView.as_view(),
        name="substitute_simplified_document",
    ),
    path(
        "stores/<int:store_id>/returns/<int:return_pk>/rectify/",
        views.IssueSaleReturnRectificationView.as_view(),
        name="issue_sale_return_rectification",
    ),
]
