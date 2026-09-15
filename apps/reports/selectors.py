"""Tenant-scoped, read-only analytics over the authoritative domain models."""

from decimal import Decimal

from django.db.models import Count, Q, Sum
from django.db.models.functions import TruncDay

from apps.cash_register.models import CashMovement, CashSession
from apps.payments.models import Payment, PaymentStatusChoices, PaymentTypeChoices
from apps.sales.models import (
    Sale,
    SaleLine,
    SaleReturn,
    SaleReturnLine,
    SaleReturnStatusChoices,
    SaleStatusChoices,
)


ZERO_MONEY = Decimal("0.00")
ZERO_QUANTITY = Decimal("0.000")
SALE_STATUSES = (SaleStatusChoices.COMPLETED, SaleStatusChoices.RETURNED)


def _validate_scope(*, business, period=None, store=None, temporal=True):
    if business is None:
        raise ValueError("business is required.")
    if temporal and period is None:
        raise ValueError("period is required.")
    if store is not None and store.business_id != business.pk:
        raise ValueError("store must belong to business.")


def _store_filter(store):
    return {"store_id": store.pk} if store is not None else {}


def _sales(*, business, period, store):
    return Sale.objects.filter(
        business=business,
        status__in=SALE_STATUSES,
        completed_at__gte=period.start,
        completed_at__lt=period.end,
        **_store_filter(store),
    )


def _returns(*, business, period, store):
    return SaleReturn.objects.filter(
        business=business,
        status=SaleReturnStatusChoices.COMPLETED,
        completed_at__gte=period.start,
        completed_at__lt=period.end,
        **_store_filter(store),
    )


def _sum(queryset, field, zero):
    return queryset.aggregate(value=Sum(field))["value"] or zero


def sales_summary(*, business, period, store=None):
    """Return commercial totals for facts occurring inside ``[start, end)``."""
    _validate_scope(business=business, period=period, store=store)
    sales = _sales(business=business, period=period, store=store)
    returns = _returns(business=business, period=period, store=store)
    sale_totals = sales.aggregate(
        gross_sales=Sum("total_amount"), ticket_count=Count("pk")
    )
    gross_sales = sale_totals["gross_sales"] or ZERO_MONEY
    ticket_count = sale_totals["ticket_count"]
    returns_amount = _sum(returns, "total_amount", ZERO_MONEY)
    units_sold = _sum(
        SaleLine.objects.filter(sale__in=sales), "quantity", ZERO_QUANTITY
    )
    units_returned = _sum(
        SaleReturnLine.objects.filter(return_doc__in=returns), "quantity", ZERO_QUANTITY
    )
    return {
        "gross_sales": gross_sales,
        "returns_amount": returns_amount,
        "net_sales": gross_sales - returns_amount,
        "ticket_count": ticket_count,
        "average_ticket": gross_sales / ticket_count if ticket_count else ZERO_MONEY,
        "units_sold": units_sold,
        "units_returned": units_returned,
    }


def sales_timeseries(*, business, period, store=None, interval="day"):
    """Return active local-calendar-day buckets, ordered by day ascending."""
    _validate_scope(business=business, period=period, store=store)
    if interval != "day":
        raise ValueError("Only the 'day' interval is supported.")
    tz = period.start.tzinfo
    sales = _sales(business=business, period=period, store=store)
    returns = _returns(business=business, period=period, store=store)
    buckets = {}
    for row in (
        sales.annotate(bucket=TruncDay("completed_at", tzinfo=tz))
        .values("bucket")
        .annotate(gross_sales=Sum("total_amount"), ticket_count=Count("pk"))
    ):
        day = row["bucket"].date()
        buckets[day] = {
            "day": day,
            "gross_sales": row["gross_sales"],
            "returns_amount": ZERO_MONEY,
            "ticket_count": row["ticket_count"],
            "units_sold": ZERO_QUANTITY,
            "units_returned": ZERO_QUANTITY,
        }
    for row in (
        SaleLine.objects.filter(sale__in=sales)
        .annotate(bucket=TruncDay("sale__completed_at", tzinfo=tz))
        .values("bucket")
        .annotate(total=Sum("quantity"))
    ):
        buckets[row["bucket"].date()]["units_sold"] = row["total"]
    for row in (
        returns.annotate(bucket=TruncDay("completed_at", tzinfo=tz))
        .values("bucket")
        .annotate(returns_amount=Sum("total_amount"))
    ):
        day = row["bucket"].date()
        buckets.setdefault(day, _empty_sales_bucket(day))["returns_amount"] = row[
            "returns_amount"
        ]
    for row in (
        SaleReturnLine.objects.filter(return_doc__in=returns)
        .annotate(bucket=TruncDay("return_doc__completed_at", tzinfo=tz))
        .values("bucket")
        .annotate(total=Sum("quantity"))
    ):
        buckets.setdefault(
            row["bucket"].date(), _empty_sales_bucket(row["bucket"].date())
        )["units_returned"] = row["total"]
    result = []
    for day in sorted(buckets):
        row = buckets[day]
        row["net_sales"] = row["gross_sales"] - row["returns_amount"]
        result.append(row)
    return result


def _empty_sales_bucket(day):
    return {
        "day": day,
        "gross_sales": ZERO_MONEY,
        "returns_amount": ZERO_MONEY,
        "ticket_count": 0,
        "units_sold": ZERO_QUANTITY,
        "units_returned": ZERO_QUANTITY,
    }


def sales_by_store(*, business, period, store=None):
    _validate_scope(business=business, period=period, store=store)
    sales = _sales(business=business, period=period, store=store)
    returns = _returns(business=business, period=period, store=store)
    rows = {}
    for row in sales.values("store_id", "store__name").annotate(
        gross_sales=Sum("total_amount"), ticket_count=Count("pk")
    ):
        rows[row["store_id"]] = _store_row(row)
        rows[row["store_id"]]["gross_sales"] = row["gross_sales"]
        rows[row["store_id"]]["ticket_count"] = row["ticket_count"]
    _merge_store(
        rows,
        returns.values("store_id", "store__name").annotate(total=Sum("total_amount")),
        "returns_amount",
    )
    _merge_store(
        rows,
        SaleLine.objects.filter(sale__in=sales)
        .values("sale__store_id", "sale__store__name")
        .annotate(total=Sum("quantity")),
        "units_sold",
        sale=True,
    )
    _merge_store(
        rows,
        SaleReturnLine.objects.filter(return_doc__in=returns)
        .values("return_doc__store_id", "return_doc__store__name")
        .annotate(total=Sum("quantity")),
        "units_returned",
        returned=True,
    )
    for row in rows.values():
        row["net_sales"] = row["gross_sales"] - row["returns_amount"]
    return sorted(rows.values(), key=lambda row: (-row["net_sales"], row["store_id"]))


def _store_row(row, *, sale=False, returned=False):
    prefix = "sale__" if sale else "return_doc__" if returned else ""
    return {
        "store_id": row[f"{prefix}store_id"],
        "store_name": row[f"{prefix}store__name"],
        "gross_sales": ZERO_MONEY,
        "returns_amount": ZERO_MONEY,
        "ticket_count": 0,
        "units_sold": ZERO_QUANTITY,
        "units_returned": ZERO_QUANTITY,
    }


def _merge_store(rows, queryset, metric, *, sale=False, returned=False):
    prefix = "sale__" if sale else "return_doc__" if returned else ""
    for item in queryset:
        key = item[f"{prefix}store_id"]
        rows.setdefault(key, _store_row(item, sale=sale, returned=returned))[metric] = (
            item["total"]
        )


def _sales_line_breakdown(*, business, period, store, dimensions):
    sales = _sales(business=business, period=period, store=store)
    returns = _returns(business=business, period=period, store=store)
    rows = {}
    for item in (
        SaleLine.objects.filter(sale__in=sales)
        .values(*dimensions)
        .annotate(gross_sales=Sum("line_total"), units_sold=Sum("quantity"))
    ):
        key = tuple(item[field] for field in dimensions)
        rows[key] = {
            **{field: item[field] for field in dimensions},
            "gross_sales": item["gross_sales"],
            "returns_amount": ZERO_MONEY,
            "units_sold": item["units_sold"],
            "units_returned": ZERO_QUANTITY,
        }
    return_dimensions = tuple(f"original_line__{field}" for field in dimensions)
    for item in (
        SaleReturnLine.objects.filter(return_doc__in=returns)
        .values(*return_dimensions)
        .annotate(returns_amount=Sum("amount"), units_returned=Sum("quantity"))
    ):
        key = tuple(item[field] for field in return_dimensions)
        row = rows.setdefault(
            key,
            {
                **dict(zip(dimensions, key, strict=True)),
                "gross_sales": ZERO_MONEY,
                "returns_amount": ZERO_MONEY,
                "units_sold": ZERO_QUANTITY,
                "units_returned": ZERO_QUANTITY,
            },
        )
        row["returns_amount"] = item["returns_amount"]
        row["units_returned"] = item["units_returned"]
    for row in rows.values():
        row["net_sales"] = row["gross_sales"] - row["returns_amount"]
    return rows.values()


def sales_by_product(*, business, period, store=None):
    _validate_scope(business=business, period=period, store=store)
    rows = _sales_line_breakdown(
        business=business,
        period=period,
        store=store,
        dimensions=("sku", "product_name"),
    )
    return sorted(
        rows, key=lambda row: (-row["net_sales"], row["sku"], row["product_name"])
    )


def sales_by_category(*, business, period, store=None):
    _validate_scope(business=business, period=period, store=store)
    rows = _sales_line_breakdown(
        business=business,
        period=period,
        store=store,
        dimensions=("category_source_id", "category_name", "category_slug"),
    )
    return sorted(
        rows,
        key=lambda row: (-row["net_sales"], row["category_slug"], row["category_name"]),
    )


def _payments(*, business, period, store):
    return Payment.objects.filter(
        business=business,
        status=PaymentStatusChoices.COMPLETED,
        created_at__gte=period.start,
        created_at__lt=period.end,
        **_store_filter(store),
    )


def payment_summary(*, business, period, store=None):
    _validate_scope(business=business, period=period, store=store)
    payments = _payments(business=business, period=period, store=store)
    data = payments.aggregate(
        collected_amount=Sum(
            "amount", filter=Q(payment_type=PaymentTypeChoices.SALE_PAYMENT)
        ),
        refunded_amount=Sum("amount", filter=Q(payment_type=PaymentTypeChoices.REFUND)),
        payment_count=Count(
            "pk", filter=Q(payment_type=PaymentTypeChoices.SALE_PAYMENT)
        ),
        refund_count=Count("pk", filter=Q(payment_type=PaymentTypeChoices.REFUND)),
    )
    data["collected_amount"] = data["collected_amount"] or ZERO_MONEY
    data["refunded_amount"] = data["refunded_amount"] or ZERO_MONEY
    data["net_amount"] = data["collected_amount"] - data["refunded_amount"]
    return data


def payments_by_method(*, business, period, store=None):
    _validate_scope(business=business, period=period, store=store)
    result = []
    for row in (
        _payments(business=business, period=period, store=store)
        .values("method_id", "method__code", "method__name")
        .annotate(
            collected_amount=Sum(
                "amount", filter=Q(payment_type=PaymentTypeChoices.SALE_PAYMENT)
            ),
            refunded_amount=Sum(
                "amount", filter=Q(payment_type=PaymentTypeChoices.REFUND)
            ),
            payment_count=Count(
                "pk", filter=Q(payment_type=PaymentTypeChoices.SALE_PAYMENT)
            ),
            refund_count=Count("pk", filter=Q(payment_type=PaymentTypeChoices.REFUND)),
        )
        .order_by("method__code")
    ):
        collected = row.pop("collected_amount") or ZERO_MONEY
        refunded = row.pop("refunded_amount") or ZERO_MONEY
        result.append(
            {
                "method_id": row["method_id"],
                "method_code": row["method__code"],
                "method_name": row["method__name"],
                "collected_amount": collected,
                "refunded_amount": refunded,
                "net_amount": collected - refunded,
                "payment_count": row["payment_count"],
                "refund_count": row["refund_count"],
            }
        )
    return result


def _movement_totals(queryset):
    values = queryset.aggregate(
        cash_sales=Sum(
            "amount", filter=Q(movement_type=CashMovement.MovementType.SALE_CASH)
        ),
        cash_refunds=Sum(
            "amount", filter=Q(movement_type=CashMovement.MovementType.REFUND_CASH)
        ),
        manual_cash_in=Sum(
            "amount", filter=Q(movement_type=CashMovement.MovementType.CASH_IN)
        ),
        manual_cash_out=Sum(
            "amount", filter=Q(movement_type=CashMovement.MovementType.CASH_OUT)
        ),
        adjustment_in=Sum(
            "amount",
            filter=Q(
                movement_type=CashMovement.MovementType.ADJUSTMENT,
                adjustment_direction=CashMovement.AdjustmentDirection.IN,
            ),
        ),
        adjustment_out=Sum(
            "amount",
            filter=Q(
                movement_type=CashMovement.MovementType.ADJUSTMENT,
                adjustment_direction=CashMovement.AdjustmentDirection.OUT,
            ),
        ),
    )
    return {key: value or ZERO_MONEY for key, value in values.items()}


def _net(values):
    return (
        values["cash_sales"]
        + values["manual_cash_in"]
        + values["adjustment_in"]
        - values["cash_refunds"]
        - values["manual_cash_out"]
        - values["adjustment_out"]
    )


def _session_row(session, totals):
    return {
        "session_id": session.pk,
        "cash_register_id": session.cash_register_id,
        "cash_register_name": session.cash_register.name,
        "cash_register_code": session.cash_register.code,
        "store_id": session.store_id,
        "store_name": session.store.name,
        "status": session.status,
        "opened_at": session.opened_at,
        "closed_at": session.closed_at,
        "opening_amount": session.opening_amount,
        **totals,
        "net_physical_movement": _net(totals),
        "expected_cash": session.expected_cash_amount,
        "counted_cash": session.counted_cash_amount,
        "difference": session.difference_amount,
    }


def cash_session_summary(*, business, cash_session_id, store=None):
    """Describe one complete session; movement totals are not period-limited."""
    _validate_scope(business=business, store=store, temporal=False)
    session = CashSession.objects.select_related("cash_register", "store").get(
        pk=cash_session_id, business=business, **_store_filter(store)
    )
    totals = _movement_totals(
        CashMovement.objects.filter(business=business, cash_session=session)
    )
    return _session_row(session, totals)


def cash_summary(*, business, period, store=None):
    """Summarize events in a period; closed totals are not current cash on hand."""
    _validate_scope(business=business, period=period, store=store)
    scope = {"business": business, **_store_filter(store)}
    opened = CashSession.objects.filter(
        **scope, opened_at__gte=period.start, opened_at__lt=period.end
    )
    closed = CashSession.objects.filter(
        **scope,
        status=CashSession.Status.CLOSED,
        closed_at__gte=period.start,
        closed_at__lt=period.end,
    )
    totals = _movement_totals(
        CashMovement.objects.filter(
            **scope, created_at__gte=period.start, created_at__lt=period.end
        )
    )
    result = {
        "sessions_opened_count": opened.count(),
        "sessions_closed_count": closed.count(),
        "opening_amount": _sum(opened, "opening_amount", ZERO_MONEY),
        **totals,
        "net_physical_movement": _net(totals),
        "closed_expected_cash": _sum(closed, "expected_cash_amount", ZERO_MONEY),
        "closed_counted_cash": _sum(closed, "counted_cash_amount", ZERO_MONEY),
        "closed_difference": _sum(closed, "difference_amount", ZERO_MONEY),
    }
    return result


def cash_sessions_summary(*, business, period, store=None):
    """List sessions intersecting the period, with each complete session's movements."""
    _validate_scope(business=business, period=period, store=store)
    sessions = list(
        CashSession.objects.filter(
            business=business, opened_at__lt=period.end, **_store_filter(store)
        )
        .filter(Q(closed_at__isnull=True) | Q(closed_at__gte=period.start))
        .select_related("cash_register", "store")
        .order_by("-opened_at", "-pk")
    )
    totals = {
        session.pk: {
            "cash_sales": ZERO_MONEY,
            "cash_refunds": ZERO_MONEY,
            "manual_cash_in": ZERO_MONEY,
            "manual_cash_out": ZERO_MONEY,
            "adjustment_in": ZERO_MONEY,
            "adjustment_out": ZERO_MONEY,
        }
        for session in sessions
    }
    if totals:
        annotations = {
            "cash_sales": Sum(
                "amount", filter=Q(movement_type=CashMovement.MovementType.SALE_CASH)
            ),
            "cash_refunds": Sum(
                "amount", filter=Q(movement_type=CashMovement.MovementType.REFUND_CASH)
            ),
            "manual_cash_in": Sum(
                "amount", filter=Q(movement_type=CashMovement.MovementType.CASH_IN)
            ),
            "manual_cash_out": Sum(
                "amount", filter=Q(movement_type=CashMovement.MovementType.CASH_OUT)
            ),
            "adjustment_in": Sum(
                "amount",
                filter=Q(
                    movement_type=CashMovement.MovementType.ADJUSTMENT,
                    adjustment_direction=CashMovement.AdjustmentDirection.IN,
                ),
            ),
            "adjustment_out": Sum(
                "amount",
                filter=Q(
                    movement_type=CashMovement.MovementType.ADJUSTMENT,
                    adjustment_direction=CashMovement.AdjustmentDirection.OUT,
                ),
            ),
        }
        for row in (
            CashMovement.objects.filter(business=business, cash_session_id__in=totals)
            .values("cash_session_id")
            .annotate(**annotations)
        ):
            totals[row["cash_session_id"]].update(
                {key: row[key] or ZERO_MONEY for key in annotations}
            )
    return [_session_row(session, totals[session.pk]) for session in sessions]
