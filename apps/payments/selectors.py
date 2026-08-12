from decimal import Decimal

from django.db.models import Sum
from django.db.models.functions import Coalesce
from django.shortcuts import get_object_or_404

from apps.payments.models import (
    Payment,
    PaymentMethod,
    PaymentStatusChoices,
    PaymentTypeChoices,
)
from apps.sales.models import Sale


def get_payment_detail(*, business, pk):
    return get_object_or_404(
        Payment.objects.select_related(
            "business", "store", "sale", "sale_return", "method", "processed_by"
        ),
        business=business,
        pk=pk,
    )


def get_sale_payments(*, business, sale_id):
    return Payment.objects.filter(business=business, sale_id=sale_id).select_related(
        "method", "sale_return", "processed_by"
    )


def get_active_payment_methods(*, business, for_refund=False):
    queryset = PaymentMethod.objects.filter(business=business, is_active=True)
    if for_refund:
        queryset = queryset.filter(allows_refund=True)
    return queryset.order_by("name", "pk")


def get_sale_payment_summary(*, business, sale_id):
    sale = get_object_or_404(Sale, business=business, pk=sale_id)
    completed = get_sale_payments(business=business, sale_id=sale_id).filter(
        status=PaymentStatusChoices.COMPLETED
    )
    paid = completed.filter(payment_type=PaymentTypeChoices.SALE_PAYMENT).aggregate(
        total=Coalesce(Sum("amount"), Decimal("0.00"))
    )["total"]
    refunded = completed.filter(payment_type=PaymentTypeChoices.REFUND).aggregate(
        total=Coalesce(Sum("amount"), Decimal("0.00"))
    )["total"]
    breakdown = list(
        completed.values("method__code", "method__name", "payment_type")
        .annotate(total=Sum("amount"))
        .order_by("method__code", "payment_type")
    )
    return {
        "total": sale.total_amount,
        "paid_total": paid,
        "refund_total": refunded,
        "pending_amount": sale.pending_amount,
        "payment_status": sale.payment_status,
        "by_method": breakdown,
    }
