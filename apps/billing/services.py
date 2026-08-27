"""Use cases for issuing immutable internal fiscal documents."""

import hashlib
import json
import uuid
from collections import defaultdict
from decimal import Decimal, ROUND_HALF_UP

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.billing.models import (
    BillingDocument,
    BillingDocumentLine,
    BillingDocumentRelation,
    BillingDocumentRelationTypeChoices,
    BillingDocumentStatusChoices,
    BillingDocumentTypeChoices,
    BillingSeries,
    BillingTaxBreakdown,
)
from apps.business_config.models import BusinessProfile
from apps.sales.models import RequestedDocumentTypeChoices, Sale, SaleStatusChoices
from apps.users.helpers import can_sell_in_store

MONEY_STEP = Decimal("0.01")
SUPPORTED_TAX_TYPE = "IVA"
SUPPORTED_REGIME = "01"
SUPPORTED_QUALIFICATION = "S1"


class BillingServiceError(ValidationError):
    """Base error for invalid billing use cases."""


class BillingIdempotencyConflict(BillingServiceError):
    """The attempt identity was previously used for another intention."""


class BillingAlreadyIssued(BillingServiceError):
    """The sale already has the fiscal document allowed by this operation."""


class BillingUnsupportedFiscalCase(BillingServiceError):
    """A sale contains a fiscal treatment not implemented by this MVP."""


def _money(value):
    return Decimal(value).quantize(MONEY_STEP, rounding=ROUND_HALF_UP)


def _normalize_uuid(value):
    try:
        return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))
    except (AttributeError, TypeError, ValueError) as exc:
        raise BillingServiceError(
            {"idempotency_key": "Debe ser un UUID válido."}
        ) from exc


def _fingerprint(payload):
    """Hash the stable semantic intention, not mutable fiscal snapshots."""
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _lock_sale(*, business, sale_id):
    """Locking Sale serializes every fiscal decision concerning that sale."""
    if business is None or not getattr(business, "pk", None):
        raise BillingServiceError({"business": "El negocio no existe."})
    try:
        return (
            Sale.objects.select_for_update()
            .select_related(
                "business", "store", "cash_register", "cash_session", "customer"
            )
            .get(pk=sale_id, business=business)
        )
    except (Sale.DoesNotExist, TypeError, ValueError) as exc:
        raise BillingServiceError(
            {"sale": "La venta no existe en este negocio."}
        ) from exc


def _validate_sale(sale):
    if sale.status != SaleStatusChoices.COMPLETED:
        raise BillingServiceError({"sale": "La venta debe estar completada."})
    if not sale.completed_at:
        raise BillingServiceError({"sale": "La venta completada no tiene fecha."})
    if sale.store.business_id != sale.business_id:
        raise BillingServiceError({"store": "La tienda no pertenece al negocio."})


def _validate_issuer(*, business, sale, issued_by):
    if issued_by is None or not getattr(issued_by, "pk", None):
        raise BillingServiceError({"issued_by": "Debes indicar el usuario emisor."})
    if not getattr(issued_by, "is_authenticated", False):
        raise BillingServiceError({"issued_by": "El usuario debe estar autenticado."})
    if not issued_by.is_active:
        raise BillingServiceError({"issued_by": "El usuario está inactivo."})
    if not issued_by.is_superuser and issued_by.business_id != business.pk:
        raise BillingServiceError({"issued_by": "El usuario no pertenece al negocio."})
    if not can_sell_in_store(issued_by, sale.store):
        raise BillingServiceError({"issued_by": "No puede vender en esta tienda."})


def _document_type_for_sale(sale):
    if sale.document_type_requested == RequestedDocumentTypeChoices.INVOICE:
        return BillingDocumentTypeChoices.F1
    if sale.document_type_requested in {
        RequestedDocumentTypeChoices.NONE,
        RequestedDocumentTypeChoices.TICKET,
    }:
        return BillingDocumentTypeChoices.F2
    raise BillingServiceError({"sale": "La solicitud de documento no es válida."})


def _validate_customer(*, business, customer):
    if customer is None or not getattr(customer, "pk", None):
        raise BillingServiceError({"customer": "Se requiere un cliente fiscal."})
    if customer.business_id != business.pk:
        raise BillingServiceError({"customer": "El cliente no pertenece al negocio."})
    if not customer.is_active:
        raise BillingServiceError({"customer": "El cliente está inactivo."})
    if not customer.has_complete_fiscal_identity:
        raise BillingServiceError({"customer": "La identidad fiscal está incompleta."})


def _issuer_snapshot(business):
    try:
        profile = BusinessProfile.objects.get(business=business)
    except BusinessProfile.DoesNotExist as exc:
        raise BillingServiceError(
            {"business": "El negocio no tiene perfil fiscal."}
        ) from exc
    values = {
        "issuer_legal_name": profile.legal_name,
        "issuer_tax_identifier": profile.tax_identifier,
        "issuer_address_line_1": profile.address_line_1,
        "issuer_address_line_2": profile.address_line_2,
        "issuer_postal_code": profile.postal_code,
        "issuer_city": profile.city,
        "issuer_province": profile.province,
        "issuer_country_code": profile.country_code,
    }
    required = {
        key: value for key, value in values.items() if key != "issuer_address_line_2"
    }
    if any(not str(value or "").strip() for value in required.values()):
        raise BillingServiceError(
            {"business": "El perfil fiscal del emisor está incompleto."}
        )
    return values


def _recipient_snapshot(customer):
    if customer is None:
        return {}
    return {
        "recipient_name": customer.name,
        "recipient_legal_name": customer.fiscal_name,
        "recipient_tax_identifier": customer.tax_identifier,
        "recipient_country_code": customer.country_code,
        "recipient_foreign_id_type": customer.foreign_id_type,
        "recipient_foreign_id": customer.foreign_id,
        "recipient_address_line_1": customer.address_line_1,
        "recipient_postal_code": customer.postal_code,
        "recipient_city": customer.city,
        "recipient_province": customer.province,
    }


def _description(document_type, sale_id):
    labels = {
        BillingDocumentTypeChoices.F1: "Factura completa",
        BillingDocumentTypeChoices.F2: "Factura simplificada",
        BillingDocumentTypeChoices.F3: "Factura sustitutiva de factura simplificada",
    }
    return f"Venta #{sale_id} · {labels[document_type]}"


def _operation_date(sale):
    completed_at = sale.completed_at
    if timezone.is_aware(completed_at):
        return timezone.localtime(completed_at).date()
    return completed_at.date()


def _validate_supported_line(line):
    if (
        line.tax_type != SUPPORTED_TAX_TYPE
        or line.clave_regimen not in (None, "", SUPPORTED_REGIME)
        or line.calificacion_operacion not in (None, "", SUPPORTED_QUALIFICATION)
        or line.operacion_exenta
        or line.has_equivalence_surcharge
    ):
        raise BillingUnsupportedFiscalCase(
            {"sale": "La venta contiene un tratamiento fiscal todavía no soportado."}
        )


def _sale_line_snapshots(sale):
    lines = list(sale.lines.all())
    if not lines:
        raise BillingServiceError({"sale": "La venta no contiene líneas."})
    snapshots = []
    totals = defaultdict(lambda: Decimal("0.00"))
    for line in lines:
        _validate_supported_line(line)
        gross = _money(line.unit_base_price * line.quantity)
        taxable = _money(gross - line.discount_amount)
        expected_tax = _money(taxable * line.tax_rate / Decimal("100.00"))
        expected_total = _money(taxable + expected_tax)
        if line.tax_amount != expected_tax or line.line_total != expected_total:
            raise BillingServiceError(
                {"sale": "Los importes históricos de una línea son incoherentes."}
            )
        data = {
            "product_name": line.product_name,
            "sku": line.sku,
            "quantity": line.quantity,
            "unit": line.unit,
            "unit_base_price": line.unit_base_price,
            "discount_amount": line.discount_amount,
            "gross_base_amount": gross,
            "taxable_base_amount": taxable,
            "tax_rate": line.tax_rate,
            "tax_type": line.tax_type,
            "clave_regimen": line.clave_regimen,
            "calificacion_operacion": line.calificacion_operacion,
            "operacion_exenta": line.operacion_exenta,
            "has_equivalence_surcharge": line.has_equivalence_surcharge,
            "equivalence_surcharge_rate": line.equivalence_surcharge_rate,
            "tax_amount": line.tax_amount,
            "line_total": line.line_total,
        }
        snapshots.append(data)
        totals["subtotal_amount"] += gross
        totals["discount_amount"] += line.discount_amount
        totals["tax_amount"] += line.tax_amount
        totals["total_amount"] += line.line_total
    expected = {
        "subtotal_amount": sale.subtotal_amount,
        "discount_amount": sale.discount_amount,
        "tax_amount": sale.tax_amount,
        "total_amount": sale.total_amount,
    }
    if any(_money(totals[key]) != value for key, value in expected.items()):
        raise BillingServiceError(
            {"sale": "Los totales de la venta no coinciden con sus líneas."}
        )
    return snapshots


def _tax_key(data):
    return (
        data["tax_type"],
        data["tax_rate"],
        data["clave_regimen"],
        data["calificacion_operacion"],
        data["operacion_exenta"],
        data["has_equivalence_surcharge"],
        data["equivalence_surcharge_rate"],
    )


def _create_lines_and_breakdowns(*, document, snapshots):
    grouped = {}
    for data in snapshots:
        BillingDocumentLine(
            business=document.business, billing_document=document, **data
        ).save()
        key = _tax_key(data)
        aggregate = grouped.setdefault(key, [Decimal("0.00"), Decimal("0.00")])
        aggregate[0] += data["taxable_base_amount"]
        aggregate[1] += data["tax_amount"]
    for key in sorted(
        grouped,
        key=lambda item: tuple("" if value is None else str(value) for value in item),
    ):
        base, tax = grouped[key]
        BillingTaxBreakdown(
            business=document.business,
            billing_document=document,
            tax_type=key[0],
            tax_rate=key[1],
            clave_regimen=key[2],
            calificacion_operacion=key[3],
            operacion_exenta=key[4],
            has_equivalence_surcharge=key[5],
            equivalence_surcharge_rate=key[6],
            taxable_base_amount=_money(base),
            tax_amount=_money(tax),
        ).save()


def _copy_children(*, source, target):
    line_fields = [
        field.name
        for field in BillingDocumentLine._meta.fields
        if field.name
        not in {"id", "created_at", "updated_at", "business", "billing_document"}
    ]
    for line in source.lines.all():
        BillingDocumentLine(
            business=target.business,
            billing_document=target,
            **{field: getattr(line, field) for field in line_fields},
        ).save()
    tax_fields = [
        field.name
        for field in BillingTaxBreakdown._meta.fields
        if field.name
        not in {"id", "created_at", "updated_at", "business", "billing_document"}
    ]
    for breakdown in source.tax_breakdowns.all():
        BillingTaxBreakdown(
            business=target.business,
            billing_document=target,
            **{field: getattr(breakdown, field) for field in tax_fields},
        ).save()


def _existing_attempt(*, business, key, fingerprint):
    existing = BillingDocument.objects.filter(
        business=business, idempotency_key=key
    ).first()
    if existing is None:
        return None
    if existing.idempotency_fingerprint != fingerprint:
        raise BillingIdempotencyConflict(
            "La clave de idempotencia pertenece a otra intención."
        )
    if existing.status != BillingDocumentStatusChoices.ISSUED:
        raise BillingServiceError(
            "La clave de idempotencia referencia un borrador inconsistente."
        )
    return existing


def _save_draft(document):
    """A savepoint keeps the outer transaction usable after a UNIQUE race."""
    try:
        with transaction.atomic():
            document.save()
    except IntegrityError:
        existing = _existing_attempt(
            business=document.business,
            key=document.idempotency_key,
            fingerprint=document.idempotency_fingerprint,
        )
        if existing is not None:
            return existing
        raise
    return None


def _validate_series(*, series, business, sale, document_type):
    if series.business_id != business.pk:
        raise BillingServiceError({"series": "La serie no pertenece al negocio."})
    if not series.is_active:
        raise BillingServiceError({"series": "La serie está inactiva."})
    if series.document_type != document_type:
        raise BillingServiceError({"series": "La serie no corresponde al tipo fiscal."})
    if series.store_id and series.store_id != sale.store_id:
        raise BillingServiceError({"series": "La serie no corresponde a la tienda."})
    if series.cash_register_id and series.cash_register_id != sale.cash_register_id:
        raise BillingServiceError({"series": "La serie no corresponde a la caja."})
    if series.year != _operation_date(sale).year:
        raise BillingServiceError(
            {"series": "La serie no corresponde al ejercicio de la operación."}
        )


def _candidate_series(*, series_id, business, sale, document_type):
    try:
        series = BillingSeries.objects.get(pk=series_id)
    except (BillingSeries.DoesNotExist, TypeError, ValueError) as exc:
        raise BillingServiceError({"series": "La serie no existe."}) from exc
    _validate_series(
        series=series, business=business, sale=sale, document_type=document_type
    )
    return series


def _lock_series(*, series_id, business, sale, document_type):
    """Locking BillingSeries serializes the authoritative number allocation."""
    try:
        series = BillingSeries.objects.select_for_update().get(pk=series_id)
    except BillingSeries.DoesNotExist as exc:
        raise BillingServiceError({"series": "La serie no existe."}) from exc
    _validate_series(
        series=series, business=business, sale=sale, document_type=document_type
    )
    return series


def _series_text(series):
    prefix = series.prefix.strip().upper()
    year = str(series.year)
    value = prefix if year in prefix else f"{prefix}-{year}"
    if len(value) > BillingDocument._meta.get_field("series_text").max_length:
        raise BillingServiceError(
            {"series": "La identidad visible de la serie es demasiado larga."}
        )
    return value


def _issue_draft(*, document, business, sale, document_type, issued_by):
    series = _lock_series(
        series_id=document.series_id,
        business=business,
        sale=sale,
        document_type=document_type,
    )
    series.current_number += 1
    series.save(update_fields=["current_number", "updated_at"])
    document.series = series
    document.number = series.current_number
    document.series_text = _series_text(series)
    document.operation_date = _operation_date(sale)
    document.issued_at = timezone.now()
    document.issued_by = issued_by
    document.status = BillingDocumentStatusChoices.ISSUED
    document.save()
    return document


@transaction.atomic
def issue_sale_document(*, business, sale_id, series_id, issued_by, idempotency_key):
    """Atomically create and issue an F1/F2 snapshot from a completed Sale."""
    key = _normalize_uuid(idempotency_key)
    sale = _lock_sale(business=business, sale_id=sale_id)  # lock order: Sale first
    _validate_sale(sale)
    document_type = _document_type_for_sale(sale)
    fingerprint = _fingerprint(
        {
            "version": 1,
            "business_id": business.pk,
            "sale_id": sale.pk,
            "operation": "issue_sale_document",
            "document_type": document_type,
            "series_id": series_id,
        }
    )
    existing = _existing_attempt(business=business, key=key, fingerprint=fingerprint)
    if existing:
        return existing
    _validate_issuer(business=business, sale=sale, issued_by=issued_by)
    if BillingDocument.objects.filter(
        business=business,
        sale=sale,
        status=BillingDocumentStatusChoices.ISSUED,
        document_type__in=[
            BillingDocumentTypeChoices.F1,
            BillingDocumentTypeChoices.F2,
            BillingDocumentTypeChoices.F3,
        ],
    ).exists():
        raise BillingAlreadyIssued("La venta ya tiene un documento fiscal inicial.")
    customer = sale.customer
    if document_type == BillingDocumentTypeChoices.F1 and customer:
        _validate_customer(business=business, customer=customer)
    elif document_type == BillingDocumentTypeChoices.F1:
        _validate_customer(business=business, customer=None)
    series = _candidate_series(
        series_id=series_id, business=business, sale=sale, document_type=document_type
    )
    snapshots = _sale_line_snapshots(sale)
    document = BillingDocument(
        business=business,
        store=sale.store,
        cash_register=sale.cash_register,
        cash_session=sale.cash_session,
        sale=sale,
        customer=customer,
        series=series,
        document_type=document_type,
        description=_description(document_type, sale.pk),
        idempotency_key=key,
        idempotency_fingerprint=fingerprint,
        subtotal_amount=sale.subtotal_amount,
        discount_amount=sale.discount_amount,
        tax_amount=sale.tax_amount,
        total_amount=sale.total_amount,
        **_issuer_snapshot(business),
        **_recipient_snapshot(customer),
    )
    raced = _save_draft(document)
    if raced:
        return raced
    _create_lines_and_breakdowns(document=document, snapshots=snapshots)
    return _issue_draft(
        document=document,
        business=business,
        sale=sale,
        document_type=document_type,
        issued_by=issued_by,
    )


@transaction.atomic
def substitute_simplified_document(
    *, business, sale_id, customer, series_id, issued_by, idempotency_key
):
    """Atomically issue an F3 that substitutes the sale's unique issued F2."""
    key = _normalize_uuid(idempotency_key)
    sale = _lock_sale(business=business, sale_id=sale_id)  # lock order: Sale first
    _validate_sale(sale)
    originals = list(
        BillingDocument.objects.filter(
            business=business,
            sale=sale,
            document_type=BillingDocumentTypeChoices.F2,
            status=BillingDocumentStatusChoices.ISSUED,
        )
    )
    if len(originals) != 1:
        raise BillingServiceError(
            "Debe existir exactamente una F2 emitida para sustituir."
        )
    original = originals[0]
    fingerprint = _fingerprint(
        {
            "version": 1,
            "business_id": business.pk,
            "sale_id": sale.pk,
            "operation": "substitute_simplified_document",
            "document_type": "F3",
            "series_id": series_id,
            "customer_id": customer.pk,
            "target_document_id": original.pk,
        }
    )
    existing = _existing_attempt(business=business, key=key, fingerprint=fingerprint)
    if existing:
        return existing
    _validate_issuer(business=business, sale=sale, issued_by=issued_by)
    _validate_customer(business=business, customer=customer)
    if BillingDocumentRelation.objects.filter(
        business=business,
        target_document=original,
        relation_type=BillingDocumentRelationTypeChoices.SUBSTITUTES,
        source_document__status=BillingDocumentStatusChoices.ISSUED,
    ).exists():
        raise BillingAlreadyIssued("La factura simplificada ya fue sustituida.")
    series = _candidate_series(
        series_id=series_id,
        business=business,
        sale=sale,
        document_type=BillingDocumentTypeChoices.F3,
    )
    document = BillingDocument(
        business=business,
        store=sale.store,
        cash_register=sale.cash_register,
        cash_session=sale.cash_session,
        sale=sale,
        customer=customer,
        series=series,
        document_type=BillingDocumentTypeChoices.F3,
        description=_description(BillingDocumentTypeChoices.F3, sale.pk),
        idempotency_key=key,
        idempotency_fingerprint=fingerprint,
        subtotal_amount=original.subtotal_amount,
        discount_amount=original.discount_amount,
        tax_amount=original.tax_amount,
        total_amount=original.total_amount,
        **_issuer_snapshot(business),
        **_recipient_snapshot(customer),
    )
    raced = _save_draft(document)
    if raced:
        return raced
    _copy_children(source=original, target=document)
    BillingDocumentRelation(
        business=business,
        source_document=document,
        target_document=original,
        relation_type=BillingDocumentRelationTypeChoices.SUBSTITUTES,
    ).save()
    return _issue_draft(
        document=document,
        business=business,
        sale=sale,
        document_type=BillingDocumentTypeChoices.F3,
        issued_by=issued_by,
    )
