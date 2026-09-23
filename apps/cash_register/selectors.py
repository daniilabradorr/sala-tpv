from decimal import Decimal

from django.db.models import Case, DecimalField, F, Prefetch, Q, Sum, Value, When
from django.db.models.functions import Coalesce

from apps.cash_register.models import CashCount, CashMovement, CashRegister, CashSession
from apps.payments.models import Payment, PaymentStatusChoices, PaymentTypeChoices
from apps.sales.models import Sale


def get_cash_register(*, business, store, cash_register_id):
    return CashRegister.objects.get(pk=cash_register_id, business=business, store=store)


def get_cash_registers_for_store(*, business, store):
    open_sessions = CashSession.objects.filter(
        business=business,
        store=store,
        status=CashSession.Status.OPEN,
        closed_at__isnull=True,
    ).select_related("opened_by")
    latest_closed_session = (
        CashSession.objects.filter(
            business=business, store=store, status=CashSession.Status.CLOSED
        )
        .select_related("closed_by")
        .order_by("-closed_at", "-pk")[:1]
    )
    registers = CashRegister.objects.filter(
        business=business, store=store
    ).prefetch_related(
        Prefetch("sessions", queryset=open_sessions, to_attr="open_sessions"),
        Prefetch(
            "sessions", queryset=latest_closed_session, to_attr="latest_closed_sessions"
        ),
    )
    for register in registers:
        register.open_session = (
            register.open_sessions[0] if register.open_sessions else None
        )
        register.latest_closed_session = (
            register.latest_closed_sessions[0]
            if register.latest_closed_sessions
            else None
        )
    return registers


def get_open_cash_session(*, business, store, cash_register):
    return CashSession.objects.filter(
        business=business,
        store=store,
        cash_register=cash_register,
        status=CashSession.Status.OPEN,
    ).first()


def get_cash_session_detail(*, business, store, cash_session_id):
    return CashSession.objects.select_related(
        "cash_register", "opened_by", "closed_by"
    ).get(pk=cash_session_id, business=business, store=store)


def get_cash_session_movements(*, business, store, cash_session):
    return CashMovement.objects.filter(
        business=business, store=store, cash_session=cash_session
    ).select_related("created_by", "sale", "payment")


def get_sales_for_cash_session(*, business, store, cash_session):
    """Return every sale explicitly isolated to the session's tenant and store."""
    return Sale.objects.filter(
        business=business,
        store=store,
        cash_session=cash_session,
    ).select_related("opened_by", "customer")


def get_cash_session_counts(*, business, store, cash_session):
    return CashCount.objects.filter(
        business=business, store=store, cash_session=cash_session
    ).select_related("counted_by")


def get_cash_session_expected_cash(*, business, store, cash_session_id):
    return CashSession.objects.values_list("expected_cash_amount", flat=True).get(
        pk=cash_session_id, business=business, store=store
    )


def get_closed_cash_sessions(*, business, store):
    return CashSession.objects.filter(
        business=business, store=store, status=CashSession.Status.CLOSED
    ).select_related("cash_register", "opened_by", "closed_by")


def get_cash_sessions_for_history(
    *,
    business,
    store,
    cash_register_id=None,
    user_id=None,
    date_from=None,
    date_to=None,
):
    sessions = CashSession.objects.filter(
        business=business, store=store
    ).select_related("cash_register", "opened_by", "closed_by")
    if cash_register_id:
        sessions = sessions.filter(cash_register_id=cash_register_id)
    if user_id:
        sessions = sessions.filter(opened_by_id=user_id)
    if date_from:
        sessions = sessions.filter(opened_at__date__gte=date_from)
    if date_to:
        sessions = sessions.filter(opened_at__date__lte=date_to)
    return sessions.order_by("-opened_at", "-pk")


def get_cash_session_physical_summary(*, business, store, cash_session):
    zero = Value(Decimal("0.00"), output_field=DecimalField())
    return CashMovement.objects.filter(
        business=business, store=store, cash_session=cash_session
    ).aggregate(
        cash_in=Coalesce(
            Sum("amount", filter=Q(movement_type=CashMovement.MovementType.CASH_IN)),
            zero,
        ),
        cash_out=Coalesce(
            Sum("amount", filter=Q(movement_type=CashMovement.MovementType.CASH_OUT)),
            zero,
        ),
    )


def get_cash_session_payment_summary(*, business, store, cash_session):
    zero = Value(Decimal("0.00"), output_field=DecimalField())
    rows = (
        Payment.objects.filter(
            business=business,
            store=store,
            cash_session=cash_session,
            status=PaymentStatusChoices.COMPLETED,
        )
        .values(
            "method_id",
            "method__code",
            "method__name",
            "method__affects_cash_register",
        )
        .annotate(
            payments=Coalesce(
                Sum(
                    Case(
                        When(
                            payment_type=PaymentTypeChoices.SALE_PAYMENT,
                            then=F("amount"),
                        ),
                        default=zero,
                    )
                ),
                zero,
            ),
            refunds=Coalesce(
                Sum(
                    Case(
                        When(payment_type=PaymentTypeChoices.REFUND, then=F("amount")),
                        default=zero,
                    )
                ),
                zero,
            ),
        )
        .order_by("method__name")
    )
    return [{**row, "net": row["payments"] - row["refunds"]} for row in rows]
