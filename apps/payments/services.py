from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models import Sum

from apps.business_config.models import POSSettings
from apps.cash_register.models import CashSession
from apps.customers.models import (
    CustomerAccount,
    CustomerAccountEntry,
    EntryTypeChoices,
)
from apps.customers.services import CustomerAccountService
from apps.payments.models import (
    Payment,
    PaymentMethod,
    PaymentStatusChoices,
    PaymentTypeChoices,
)
from apps.sales.models import (
    PaymentStatusChoices as SalePaymentStatusChoices,
    Sale,
    SaleReturn,
    SaleReturnStatusChoices,
    SaleStatusChoices,
)
from apps.users.helpers import can_perform_sensitive_action, can_sell_in_store

ZERO = Decimal("0.00")


def _validate_business(business):
    if business is None or not business.is_active:
        raise ValidationError("El negocio no es válido.")


def _amount(value):
    try:
        value = Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValidationError({"amount": "El importe no es válido."}) from exc
    if value <= ZERO:
        raise ValidationError({"amount": "El importe debe ser mayor que cero."})
    return value


def _settings(business):
    try:
        return POSSettings.objects.get(business=business)
    except POSSettings.DoesNotExist as exc:
        raise ValidationError("El negocio no tiene configuración TPV.") from exc


def _validate_user(*, business, store, user, sensitive=False, pin=None, settings=None):
    if not user or not user.is_authenticated or not user.is_active:
        raise ValidationError({"user": "El usuario no es válido."})
    if not user.is_superuser and user.business_id != business.pk:
        raise ValidationError({"user": "El usuario no pertenece al negocio."})
    if not can_sell_in_store(user, store):
        raise ValidationError({"user": "No tienes permiso para operar en la tienda."})
    if sensitive:
        if not can_perform_sensitive_action(user):
            raise ValidationError({"user": "No puedes realizar esta acción sensible."})
        if settings.require_pin_for_sensitive_actions and (
            not pin or not user.check_pin(pin)
        ):
            raise ValidationError({"pin": "El PIN indicado no es válido."})


def _method(*, business, method_id, refund=False):
    try:
        method = PaymentMethod.objects.get(pk=method_id, business=business)
    except PaymentMethod.DoesNotExist as exc:
        raise ValidationError({"method": "El método no pertenece al negocio."}) from exc
    if not method.is_active:
        raise ValidationError({"method": "El método de pago está inactivo."})
    if refund and not method.allows_refund:
        raise ValidationError({"method": "El método no permite reembolsos."})
    return method


def _cash_context(*, business, store, method, settings, cash_session_id):
    session = None
    if cash_session_id:
        try:
            session = CashSession.objects.select_related("cash_register").get(
                pk=cash_session_id, business=business, store=store
            )
        except CashSession.DoesNotExist as exc:
            raise ValidationError(
                {"cash_session": "La sesión no pertenece al negocio y tienda actuales."}
            ) from exc
        if not session.is_open or not session.cash_register.is_active:
            raise ValidationError(
                {"cash_session": "La sesión de caja seleccionada no está operativa."}
            )
        if (
            session.cash_register.business_id != business.pk
            or session.cash_register.store_id != store.pk
        ):
            raise ValidationError(
                {"cash_session": "La caja de la sesión no es válida."}
            )
    if (
        session is None
        and method.affects_cash_register
        and settings.require_open_cash_register
    ):
        raise ValidationError(
            {"cash_session": "Se requiere una sesión de caja abierta."}
        )
    return session


def _existing(*, business, key, sale, method, payment_type, amount, sale_return=None):
    payment = Payment.objects.filter(business=business, idempotency_key=key).first()
    if not payment:
        return None
    compatible = (
        payment.sale_id == sale.pk
        and payment.method_id == method.pk
        and payment.payment_type == payment_type
        and payment.amount == amount
        and payment.sale_return_id == getattr(sale_return, "pk", None)
    )
    if not compatible:
        raise ValidationError(
            {"idempotency_key": "La clave ya se usó con otros datos."}
        )
    return payment


def _get_sale_payment_balance(sale):
    """Devuelve un único balance económico persistido de la venta."""
    values = (
        Payment.objects.filter(sale=sale, status=PaymentStatusChoices.COMPLETED)
        .values("payment_type")
        .annotate(total=Sum("amount"))
    )
    totals = {row["payment_type"]: row["total"] for row in values}
    paid_total = totals.get(PaymentTypeChoices.SALE_PAYMENT, ZERO)
    refunded_total = totals.get(PaymentTypeChoices.REFUND, ZERO)
    returned_total = (
        sale.returns.filter(status=SaleReturnStatusChoices.COMPLETED).aggregate(
            total=Sum("total_amount")
        )["total"]
        or ZERO
    )
    gross_total = sale.total_amount
    effective_total = max(gross_total - returned_total, ZERO)
    net_paid = max(paid_total - refunded_total, ZERO)
    return {
        "gross_total": gross_total,
        "returned_total": returned_total,
        "effective_total": effective_total,
        "paid_total": paid_total,
        "refunded_total": refunded_total,
        "net_paid": net_paid,
        "pending_amount": max(effective_total - net_paid, ZERO),
    }


def _recalculate_sale_payment_state(locked_sale):
    balance = _get_sale_payment_balance(locked_sale)
    debt_reduction = abs(
        CustomerAccountEntry.objects.filter(
            business=locked_sale.business,
            sale=locked_sale,
            entry_type=EntryTypeChoices.REFUND,
            payment__isnull=True,
        ).aggregate(total=Sum("amount"))["total"]
        or ZERO
    )
    monetary_return_required = min(
        balance["paid_total"],
        max(balance["returned_total"] - debt_reduction, ZERO),
    )
    if (
        balance["paid_total"] > ZERO
        and balance["returned_total"] >= balance["gross_total"]
        and balance["refunded_total"] >= monetary_return_required
    ):
        status = SalePaymentStatusChoices.REFUNDED
    elif balance["paid_total"] == ZERO:
        status = SalePaymentStatusChoices.UNPAID
    elif balance["pending_amount"] == ZERO:
        status = SalePaymentStatusChoices.PAID
    else:
        status = SalePaymentStatusChoices.PARTIAL
    locked_sale.pending_amount = balance["pending_amount"]
    locked_sale.payment_status = status
    locked_sale.save(update_fields=["pending_amount", "payment_status", "updated_at"])
    return balance


def _apply_customer_debt_payment(*, business, sale, payment, user):
    if payment.status != PaymentStatusChoices.COMPLETED:
        return None
    charge = (
        CustomerAccountEntry.objects.filter(
            business=business, sale=sale, entry_type=EntryTypeChoices.CHARGE
        )
        .select_related("account")
        .first()
    )
    if not charge:
        return None
    existing = CustomerAccountEntry.objects.filter(payment=payment).first()
    if existing:
        return existing
    sale_debt = (
        CustomerAccountEntry.objects.filter(
            business=business, account=charge.account, sale=sale
        ).aggregate(total=Sum("amount"))["total"]
        or ZERO
    )
    amount = min(payment.amount, max(sale_debt, ZERO))
    if amount == ZERO:
        return None
    return CustomerAccountService.register_payment(
        business=business,
        account=charge.account,
        amount=amount,
        user=user,
        sale=sale,
        payment=payment,
        notes=f"Cobro de venta #{sale.pk}",
    )[1]


@transaction.atomic
def register_sale_payment(
    *,
    business,
    sale_id,
    method_id,
    amount,
    user,
    idempotency_key,
    cash_session_id=None,
    external_reference="",
    notes="",
):
    _validate_business(business)
    try:
        sale = (
            Sale.objects.select_for_update()
            .select_related("store", "cash_session")
            .get(pk=sale_id, business=business)
        )
    except Sale.DoesNotExist as exc:
        raise ValidationError({"sale": "La venta no pertenece al negocio."}) from exc
    settings = _settings(business)
    _validate_user(business=business, store=sale.store, user=user)
    if sale.status != SaleStatusChoices.COMPLETED:
        raise ValidationError({"sale": "Solo se pueden cobrar ventas completadas."})
    method = _method(business=business, method_id=method_id)
    amount = _amount(amount)
    existing = _existing(
        business=business,
        key=idempotency_key,
        sale=sale,
        method=method,
        payment_type=PaymentTypeChoices.SALE_PAYMENT,
        amount=amount,
    )
    if existing:
        if existing.status == PaymentStatusChoices.COMPLETED:
            _apply_customer_debt_payment(
                business=business, sale=sale, payment=existing, user=user
            )
        return existing
    session = _cash_context(
        business=business,
        store=sale.store,
        method=method,
        settings=settings,
        cash_session_id=cash_session_id,
    )
    balance = _get_sale_payment_balance(sale)
    if amount > balance["pending_amount"]:
        raise ValidationError({"amount": "El importe supera lo pendiente de cobro."})
    used_methods = set(
        Payment.objects.filter(
            sale=sale,
            status=PaymentStatusChoices.COMPLETED,
            payment_type=PaymentTypeChoices.SALE_PAYMENT,
        ).values_list("method_id", flat=True)
    )
    if (
        used_methods
        and method.pk not in used_methods
        and not settings.allow_split_payments
    ):
        raise ValidationError(
            {"method": "La configuración no permite dividir entre métodos."}
        )
    try:
        with transaction.atomic():
            payment = Payment.objects.create(
                business=business,
                store=sale.store,
                sale=sale,
                method=method,
                cash_session=session,
                payment_type=PaymentTypeChoices.SALE_PAYMENT,
                amount=amount,
                status=PaymentStatusChoices.COMPLETED,
                processed_by=user,
                idempotency_key=idempotency_key,
                external_reference=external_reference,
                notes=notes,
            )
    except IntegrityError:
        payment = _existing(
            business=business,
            key=idempotency_key,
            sale=sale,
            method=method,
            payment_type=PaymentTypeChoices.SALE_PAYMENT,
            amount=amount,
        )
        if payment is None:
            raise
    _recalculate_sale_payment_state(sale)
    _apply_customer_debt_payment(
        business=business, sale=sale, payment=payment, user=user
    )
    return payment


@transaction.atomic
def register_refund(
    *,
    business,
    sale_return_id,
    method_id,
    amount,
    user,
    idempotency_key,
    cash_session_id=None,
    pin=None,
    external_reference="",
    notes="",
):
    _validate_business(business)
    try:
        returned = (
            SaleReturn.objects.select_for_update()
            .select_related("store")
            .get(pk=sale_return_id, business=business)
        )
    except SaleReturn.DoesNotExist as exc:
        raise ValidationError(
            {"sale_return": "La devolución no pertenece al negocio."}
        ) from exc
    sale = (
        Sale.objects.select_for_update()
        .select_related("cash_session")
        .get(pk=returned.original_sale_id, business=business)
    )
    settings = _settings(business)
    _validate_user(
        business=business,
        store=returned.store,
        user=user,
        sensitive=True,
        pin=pin,
        settings=settings,
    )
    if returned.status != SaleReturnStatusChoices.COMPLETED:
        raise ValidationError({"sale_return": "La devolución debe estar completada."})
    method = _method(business=business, method_id=method_id, refund=True)
    amount = _amount(amount)
    existing = _existing(
        business=business,
        key=idempotency_key,
        sale=sale,
        method=method,
        payment_type=PaymentTypeChoices.REFUND,
        amount=amount,
        sale_return=returned,
    )
    if existing:
        return existing
    session = _cash_context(
        business=business,
        store=sale.store,
        method=method,
        settings=settings,
        cash_session_id=cash_session_id,
    )
    balance = _get_sale_payment_balance(sale)
    return_refunded = (
        Payment.objects.filter(
            sale_return=returned,
            status=PaymentStatusChoices.COMPLETED,
            payment_type=PaymentTypeChoices.REFUND,
        ).aggregate(total=Sum("amount"))["total"]
        or ZERO
    )
    debt_reduction = (
        CustomerAccountEntry.objects.filter(
            business=business,
            sale=sale,
            entry_type=EntryTypeChoices.REFUND,
            payment__isnull=True,
            notes=f"Reducción de deuda por devolución #{returned.pk}",
        ).aggregate(total=Sum("amount"))["total"]
        or ZERO
    )
    monetary_capacity = returned.total_amount - abs(debt_reduction)
    if return_refunded + amount > monetary_capacity:
        raise ValidationError(
            {"amount": "El importe supera la parte monetaria de la devolución."}
        )
    if balance["refunded_total"] + amount > balance["paid_total"]:
        raise ValidationError(
            {"amount": "No se puede devolver más dinero del cobrado."}
        )
    try:
        with transaction.atomic():
            payment = Payment.objects.create(
                business=business,
                store=sale.store,
                sale=sale,
                method=method,
                cash_session=session,
                sale_return=returned,
                payment_type=PaymentTypeChoices.REFUND,
                amount=amount,
                status=PaymentStatusChoices.COMPLETED,
                processed_by=user,
                idempotency_key=idempotency_key,
                external_reference=external_reference,
                notes=notes,
            )
    except IntegrityError:
        payment = _existing(
            business=business,
            key=idempotency_key,
            sale=sale,
            method=method,
            payment_type=PaymentTypeChoices.REFUND,
            amount=amount,
            sale_return=returned,
        )
        if payment is None:
            raise
    _recalculate_sale_payment_state(sale)
    return payment


@transaction.atomic
def register_sale_on_account(*, business, sale_id, user):
    """Registra explícitamente como deuda el pendiente actual de una Sale."""
    _validate_business(business)
    try:
        sale = (
            Sale.objects.select_for_update()
            .select_related("store", "customer")
            .get(pk=sale_id, business=business)
        )
    except Sale.DoesNotExist as exc:
        raise ValidationError({"sale": "La venta no pertenece al negocio."}) from exc
    _validate_user(business=business, store=sale.store, user=user)
    if sale.status != SaleStatusChoices.COMPLETED:
        raise ValidationError(
            {"sale": "Solo una venta completada puede pasar a cuenta."}
        )
    if sale.customer_id is None:
        raise ValidationError({"sale": "La venta debe tener un cliente."})
    existing = CustomerAccountEntry.objects.filter(
        business=business,
        sale=sale,
        entry_type=EntryTypeChoices.CHARGE,
    ).first()
    if existing:
        return existing
    try:
        account = CustomerAccount.objects.get(
            business=business, customer_id=sale.customer_id
        )
    except CustomerAccount.DoesNotExist as exc:
        raise ValidationError(
            {"sale": "El cliente no tiene cuenta corriente."}
        ) from exc
    _recalculate_sale_payment_state(sale)
    if sale.pending_amount <= ZERO:
        raise ValidationError({"sale": "La venta no tiene importe pendiente."})
    return CustomerAccountService.create_charge(
        business=business,
        account=account,
        amount=sale.pending_amount,
        user=user,
        sale=sale,
        notes=f"Venta #{sale.pk} pasada a cuenta",
    )[1]


@transaction.atomic
def cancel_payment(*, business, payment_id, user, pin=None):
    _validate_business(business)
    try:
        payment = (
            Payment.objects.select_for_update()
            .select_related("store")
            .get(pk=payment_id, business=business)
        )
    except Payment.DoesNotExist as exc:
        raise ValidationError({"payment": "El pago no pertenece al negocio."}) from exc
    settings = _settings(business)
    _validate_user(
        business=business,
        store=payment.store,
        user=user,
        sensitive=True,
        pin=pin,
        settings=settings,
    )
    if payment.status == PaymentStatusChoices.CANCELLED:
        return payment
    if payment.status != PaymentStatusChoices.PENDING:
        raise ValidationError({"payment": "Solo se pueden cancelar pagos pendientes."})
    payment.status = PaymentStatusChoices.CANCELLED
    payment.save(update_fields=["status", "updated_at"])
    return payment
