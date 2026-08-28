from django.urls import path

from apps.billing import views

app_name = "billing"

urlpatterns = [
    path(
        "stores/<int:store_id>/documents/",
        views.BillingDocumentListView.as_view(),
        name="document_list",
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
