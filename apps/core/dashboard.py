"""Read-only presentation composition for the operational home dashboard."""

from datetime import timedelta
from decimal import Decimal

from django.db.models import Q
from django.utils import formats, timezone

from apps.audit.selectors import get_audit_events
from apps.cash_register.selectors import get_cash_registers_for_store
from apps.inventory.selectors import get_inventory_items_for_business
from apps.purchases.models import PurchaseStatusChoices
from apps.purchases.selectors import get_purchases_for_user
from apps.reports.periods import report_period_for_day, report_period_from_dates
from apps.reports.selectors import dashboard_summary
from apps.users.helpers import is_owner_or_manager

PERIOD_OPTIONS = {
    "today": ("Hoy", 1),
    "7d": ("Últimos 7 días", 7),
    "30d": ("Últimos 30 días", 30),
}


def resolve_dashboard_period(value, *, today=None, tz=None):
    """Resolve a public period key to an aware Reports period."""

    key = value if value in PERIOD_OPTIONS else "today"
    today = today or timezone.localdate(timezone=tz)
    days = PERIOD_OPTIONS[key][1]
    if days == 1:
        period = report_period_for_day(day=today, tz=tz)
    else:
        period = report_period_from_dates(
            date_from=today - timedelta(days=days - 1), date_to=today, tz=tz
        )
    return key, period


def _money(value):
    return f"{formats.number_format(value, decimal_pos=2, use_l10n=True)} €"


def _trend_rows(*, summary, today):
    reported = {row["day"]: row["net_sales"] for row in summary["sales_timeseries"]}
    rows = []
    for offset in range(6, -1, -1):
        day = today - timedelta(days=offset)
        amount = reported.get(day, Decimal("0.00"))
        rows.append(
            {
                "date": day.isoformat(),
                "label": formats.date_format(day, "D j M"),
                "amount": str(amount),
                "formatted_amount": _money(amount),
            }
        )
    return rows


def _cash_status(*, business, store):
    registers = list(
        get_cash_registers_for_store(business=business, store=store)
        .filter(is_active=True)
        .order_by("name", "pk")
    )
    sessions = [session for register in registers for session in register.open_sessions]
    return {
        "register_count": len(registers),
        "open_count": len(sessions),
        "open_sessions": sessions,
    }


def _critical_stock(*, business, store, limit=5):
    base = {"is_active": "true", "store": store}
    out = list(
        get_inventory_items_for_business(
            business, filters={**base, "out_of_stock": True}, stores=[store]
        )[:limit]
    )
    low = list(
        get_inventory_items_for_business(
            business, filters={**base, "low_stock": True}, stores=[store]
        )[: max(0, limit - len(out))]
    )
    return [
        {
            "item": item,
            "status": "Sin stock" if item.available <= 0 else "Stock bajo",
            "status_code": "out" if item.available <= 0 else "low",
        }
        for item in (*out, *low)
    ]


def build_dashboard_context(*, business, store, user, period_key, today=None):
    """Compose tenant/store-scoped dashboard data without changing domain state."""

    today = today or timezone.localdate()
    period_key, period = resolve_dashboard_period(period_key, today=today)
    trend_period = report_period_from_dates(
        date_from=today - timedelta(days=6), date_to=today
    )
    summary = dashboard_summary(
        business=business, period=period, store=store, trend_period=trend_period
    )
    inventory = summary["inventory"]
    can_view_management = user.is_superuser or is_owner_or_manager(user)
    purchases = []
    activity = []
    if can_view_management:
        purchases = list(
            get_purchases_for_user(business=business, user=user, store=store).filter(
                status__in=(
                    PurchaseStatusChoices.ORDERED,
                    PurchaseStatusChoices.PARTIALLY_RECEIVED,
                )
            )[:5]
        )
        activity = list(
            get_audit_events(business=business).filter(
                Q(store=store) | Q(store__isnull=True)
            )[:4]
        )
    trend = _trend_rows(summary=summary, today=today)
    return {
        "dashboard": summary,
        "period_key": period_key,
        "period_label": PERIOD_OPTIONS[period_key][0],
        "period_options": tuple(
            {"key": key, "label": label}
            for key, (label, _days) in PERIOD_OPTIONS.items()
        ),
        "today": today,
        "sales": {
            "net_sales": _money(summary["sales"]["net_sales"]),
            "ticket_count": summary["sales"]["ticket_count"],
            "average_ticket": _money(summary["sales"]["average_ticket"]),
        },
        "stock_attention": inventory["out_of_stock_count"]
        + inventory["low_stock_count"],
        "trend": trend,
        "trend_has_sales": any(Decimal(row["amount"]) != 0 for row in trend),
        "cash_status": _cash_status(business=business, store=store),
        "critical_stock": _critical_stock(business=business, store=store),
        "pending_purchases": purchases,
        "show_management_blocks": can_view_management,
        "recent_activity": activity,
    }
