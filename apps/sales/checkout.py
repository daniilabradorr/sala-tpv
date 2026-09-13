"""Durable application orchestration for the TPV checkout.

Domain mutations deliberately remain in Sales, Payments and Billing services.  This
module only derives the next step from persisted state and coordinates those calls.
"""

from dataclasses import dataclass
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.utils import timezone

from apps.billing.models import BillingDocumentStatusChoices, BillingDocumentTypeChoices
from apps.billing.selectors import active_billing_series, billing_documents_for_sale
from apps.billing.services import issue_sale_document
from apps.cash_register.models import CashSession
from apps.payments.models import Payment, PaymentStatusChoices as PaymentRecordStatus
from apps.payments.selectors import get_active_payment_methods, get_sale_payments
from apps.payments.services import register_sale_payment
from apps.sales.models import (
    PaymentStatusChoices,
    RequestedDocumentTypeChoices,
    SaleStatusChoices,
)
from apps.sales.services import complete_sale


@dataclass(frozen=True)
class PaymentIntent:
    method_id: int
    amount: Decimal
    idempotency_key: object
    cash_received: Decimal | None = None
    external_reference: str = ""


def initial_document(sale, business):
    return (
        billing_documents_for_sale(business=business, sale=sale)
        .filter(
            status=BillingDocumentStatusChoices.ISSUED,
            document_type__in=(
                BillingDocumentTypeChoices.F1,
                BillingDocumentTypeChoices.F2,
            ),
        )
        .first()
    )


def checkout_state(*, business, sale):
    sale.refresh_from_db()
    document = initial_document(sale, business)
    payments = get_sale_payments(business=business, sale_id=sale.pk).filter(
        status=PaymentRecordStatus.COMPLETED
    )
    complete = (
        sale.status == SaleStatusChoices.COMPLETED
        and sale.payment_status == PaymentStatusChoices.PAID
        and sale.pending_amount == Decimal("0.00")
        and document is not None
    )
    return {
        "sale": sale,
        "document": document,
        "payments": payments,
        "complete": complete,
    }


def checkout_options(*, business, sale):
    document_type = {
        RequestedDocumentTypeChoices.TICKET: BillingDocumentTypeChoices.F2,
        RequestedDocumentTypeChoices.INVOICE: BillingDocumentTypeChoices.F1,
    }.get(sale.document_type_requested)
    series = (
        active_billing_series(
            business=business,
            document_type=document_type,
            year=timezone.localdate().year,
            store=sale.store,
            cash_register=sale.cash_register,
        )
        if document_type
        else []
    )
    return {
        "methods": get_active_payment_methods(business=business),
        "series": series,
        "document_type": document_type,
    }


def _preflight(*, business, sale, intents, series_id, allow_split):
    if sale.status not in (SaleStatusChoices.OPEN, SaleStatusChoices.COMPLETED):
        raise ValidationError("La venta no se puede procesar desde su estado actual.")
    if sale.status == SaleStatusChoices.OPEN and not sale.lines.exists():
        raise ValidationError("No se puede cobrar una venta sin líneas.")
    if sale.document_type_requested not in (
        RequestedDocumentTypeChoices.TICKET,
        RequestedDocumentTypeChoices.INVOICE,
    ):
        raise ValidationError("Selecciona Ticket o Factura antes de cobrar.")
    if (
        sale.document_type_requested == RequestedDocumentTypeChoices.INVOICE
        and not sale.customer_id
    ):
        raise ValidationError("La factura requiere un cliente válido.")
    if (sale.status == SaleStatusChoices.OPEN or sale.pending_amount > 0) and (
        not sale.cash_session_id or sale.cash_session.status != CashSession.Status.OPEN
    ):
        raise ValidationError("La sesión de caja está cerrada o no existe.")

    options = checkout_options(business=business, sale=sale)
    candidates = list(options["series"])
    if not candidates:
        raise ValidationError(
            "No existe una serie de facturación válida para este tipo de documento, tienda y caja."
        )
    if series_id is None and len(candidates) != 1:
        raise ValidationError("Selecciona una serie de facturación.")
    chosen_id = candidates[0].pk if series_id is None else int(series_id)
    if chosen_id not in {candidate.pk for candidate in candidates}:
        raise ValidationError(
            {"series": "La serie seleccionada no es válida para esta venta."}
        )

    if sale.pending_amount > 0:
        if not intents:
            raise ValidationError("Selecciona un método de pago.")
        if len(intents) > 1 and not allow_split:
            raise ValidationError("No se permiten pagos divididos.")
        active_ids = {method.pk for method in options["methods"]}
        if any(intent.method_id not in active_ids for intent in intents):
            raise ValidationError(
                {"method": "El método está inactivo o pertenece a otro negocio."}
            )
        if len({intent.method_id for intent in intents}) != len(intents):
            raise ValidationError("No repitas el mismo método en un pago mixto.")
        if any(intent.amount <= 0 for intent in intents):
            raise ValidationError("Todos los importes deben ser mayores que cero.")
        existing = Payment.objects.filter(
            business=business,
            sale=sale,
            idempotency_key__in=[intent.idempotency_key for intent in intents],
            status=PaymentRecordStatus.COMPLETED,
        )
        expected = sale.pending_amount + sum(
            (payment.amount for payment in existing), Decimal("0.00")
        )
        if sum((intent.amount for intent in intents), Decimal("0.00")) != expected:
            raise ValidationError(
                "La suma de los pagos debe coincidir con el importe pendiente."
            )
        methods = {method.pk: method for method in options["methods"]}
        for intent in intents:
            if methods[intent.method_id].code == "cash":
                if intent.cash_received is None or intent.cash_received < intent.amount:
                    raise ValidationError(
                        "El importe de efectivo entregado es insuficiente."
                    )
    return chosen_id


def run_checkout(*, business, sale, user, intents, series_id, billing_key, allow_split):
    """Advance durable steps; an exception never rolls earlier modules back."""
    state = checkout_state(business=business, sale=sale)
    if state["complete"]:
        return state
    chosen_series = _preflight(
        business=business,
        sale=sale,
        intents=intents,
        series_id=series_id,
        allow_split=allow_split,
    )
    if sale.status == SaleStatusChoices.OPEN:
        sale = complete_sale(business=business, sale=sale, closed_by=user)
        sale.refresh_from_db()
    for intent in intents:
        if sale.pending_amount <= 0:
            break
        register_sale_payment(
            business=business,
            sale_id=sale.pk,
            method_id=intent.method_id,
            amount=intent.amount,
            user=user,
            idempotency_key=intent.idempotency_key,
            cash_session_id=sale.cash_session_id,
            external_reference=intent.external_reference,
        )
        sale.refresh_from_db()
    if sale.pending_amount == 0 and initial_document(sale, business) is None:
        issue_sale_document(
            business=business,
            sale_id=sale.pk,
            series_id=chosen_series,
            issued_by=user,
            idempotency_key=billing_key,
        )
    return checkout_state(business=business, sale=sale)
