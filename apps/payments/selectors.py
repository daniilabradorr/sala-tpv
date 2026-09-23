from decimal import Decimal

from django.db.models import Sum
from django.db.models.functions import Coalesce
from django.shortcuts import get_object_or_404

from apps.customers.models import CustomerAccountEntry, EntryTypeChoices
from apps.payments.models import (
    Payment,
    PaymentMethod,
    PaymentStatusChoices,
    PaymentTypeChoices,
)
from apps.sales.models import Sale, SaleReturnStatusChoices


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


def get_sale_return_refund_summary(*, business, sale_return):
    """Read-only monetary capacity shared by the UI and refund command."""
    sale = sale_return.original_sale
    completed = get_sale_payments(business=business, sale_id=sale.pk).filter(
        status=PaymentStatusChoices.COMPLETED
    )
    paid_total = completed.filter(
        payment_type=PaymentTypeChoices.SALE_PAYMENT
    ).aggregate(total=Coalesce(Sum("amount"), Decimal("0.00")))["total"]
    refunded_total = completed.filter(payment_type=PaymentTypeChoices.REFUND).aggregate(
        total=Coalesce(Sum("amount"), Decimal("0.00"))
    )["total"]
    returned_total = sale.returns.filter(
        status=SaleReturnStatusChoices.COMPLETED
    ).aggregate(total=Coalesce(Sum("total_amount"), Decimal("0.00")))["total"]
    return_refunded = completed.filter(
        payment_type=PaymentTypeChoices.REFUND, sale_return=sale_return
    ).aggregate(total=Coalesce(Sum("amount"), Decimal("0.00")))["total"]
    debt_reduction = abs(
        CustomerAccountEntry.objects.filter(
            business=business,
            sale=sale,
            entry_type=EntryTypeChoices.REFUND,
            payment__isnull=True,
            notes=f"Reducción de deuda por devolución #{sale_return.pk}",
        ).aggregate(total=Coalesce(Sum("amount"), Decimal("0.00")))["total"]
    )
    effective_total = max(sale.total_amount - returned_total, Decimal("0.00"))
    net_paid = max(paid_total - refunded_total, Decimal("0.00"))
    monetary_capacity = max(sale_return.total_amount - debt_reduction, Decimal("0.00"))
    remaining = min(
        max(net_paid - effective_total, Decimal("0.00")),
        max(monetary_capacity - return_refunded, Decimal("0.00")),
    )
    return {
        "refunded_total": return_refunded,
        "debt_reduction": debt_reduction,
        "monetary_capacity": monetary_capacity,
        "remaining": remaining,
        "is_complete": remaining == Decimal("0.00"),
        "payments": completed.filter(
            payment_type=PaymentTypeChoices.REFUND, sale_return=sale_return
        ).select_related("method", "processed_by"),
    }
