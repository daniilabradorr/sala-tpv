from django.urls import path

from apps.payments.views import (
    PaymentCancelView,
    PaymentCreateView,
    PaymentRefundView,
    SaleOnAccountView,
)

app_name = "payments"

urlpatterns = [
    path(
        "stores/<int:store_id>/sales/<int:sale_id>/payments/create/",
        PaymentCreateView.as_view(),
        name="create",
    ),
    path(
        "stores/<int:store_id>/sales/<int:sale_id>/on-account/",
        SaleOnAccountView.as_view(),
        name="sale_on_account",
    ),
    path(
        "stores/<int:store_id>/returns/<int:sale_return_id>/refund/",
        PaymentRefundView.as_view(),
        name="refund",
    ),
    path(
        "stores/<int:store_id>/payments/<int:payment_id>/cancel/",
        PaymentCancelView.as_view(),
        name="cancel",
    ),
]
