import re
from decimal import Decimal, InvalidOperation

from django.urls import NoReverseMatch, reverse
from django.utils import formats, timezone

from apps.audit.constants import AuditEventType, AuditModule
from apps.audit.sanitizers import REDACTED, _is_secret_key
from apps.users.helpers import can_access_store, can_manage_business_settings

MODULE_LABELS = {
    AuditModule.SALES: "Ventas",
    AuditModule.PAYMENTS: "Pagos",
    AuditModule.CASH_REGISTER: "Caja",
    AuditModule.INVENTORY: "Inventario",
    AuditModule.PURCHASES: "Compras",
    AuditModule.BILLING: "Facturación",
    AuditModule.BUSINESS_CONFIG: "Configuración",
}

EVENT_LABELS = {
    AuditEventType.SALE_COMPLETED: "Venta completada",
    AuditEventType.SALE_CANCELLED: "Venta cancelada",
    AuditEventType.SALE_RETURN_COMPLETED: "Devolución completada",
    AuditEventType.SALE_RETURN_CANCELLED: "Devolución cancelada",
    AuditEventType.PAYMENT_COMPLETED: "Pago completado",
    AuditEventType.PAYMENT_REFUNDED: "Pago reembolsado",
    AuditEventType.PAYMENT_CANCELLED: "Pago cancelado",
    AuditEventType.SALE_ON_ACCOUNT_REGISTERED: "Venta a cuenta registrada",
    AuditEventType.CASH_SESSION_OPENED: "Sesión de caja abierta",
    AuditEventType.CASH_IN: "Entrada de caja",
    AuditEventType.CASH_OUT: "Salida de caja",
    AuditEventType.CASH_ADJUSTED: "Caja ajustada",
    AuditEventType.CASH_COUNTED: "Caja contada",
    AuditEventType.CASH_SESSION_CLOSED: "Sesión de caja cerrada",
    AuditEventType.STOCK_INITIALIZED: "Stock inicializado",
    AuditEventType.STOCK_ADJUSTED: "Stock ajustado",
    AuditEventType.STOCK_ADJUSTMENT_CANCELLED: "Ajuste de stock cancelado",
    AuditEventType.PURCHASE_CREATED: "Compra creada",
    AuditEventType.PURCHASE_ORDERED: "Compra pedida",
    AuditEventType.PURCHASE_RECEIVED: "Compra recibida",
    AuditEventType.PURCHASE_CANCELLED: "Compra cancelada",
    AuditEventType.BILLING_DOCUMENT_ISSUED: "Documento fiscal emitido",
    AuditEventType.BILLING_DOCUMENT_SUBSTITUTED: "Documento fiscal sustituido",
    AuditEventType.BILLING_DOCUMENT_RECTIFIED: "Documento fiscal rectificado",
    AuditEventType.BUSINESS_CONFIG_CHANGED: "Configuración modificada",
}

ENTITY_LABELS = {
    "sales.sale": "Venta",
    "sales.salereturn": "Devolución",
    "payments.payment": "Pago",
    "cash_register.cashsession": "Sesión de caja",
    "cash_register.cashmovement": "Movimiento de caja",
    "cash_register.cashcount": "Recuento de caja",
    "inventory.stockmovement": "Movimiento de stock",
    "inventory.stockadjustment": "Ajuste de stock",
    "purchases.purchase": "Compra",
    "purchases.purchasereceipt": "Recepción de compra",
    "billing.billingdocument": "Documento fiscal",
    "business_config.businessprofile": "Perfil del negocio",
    "business_config.possettings": "Ajustes del TPV",
}

_CTA_LABELS = {
    "sales.sale": "Ver venta",
    "sales.salereturn": "Ver devolución",
    "cash_register.cashsession": "Ver sesión de caja",
    "inventory.stockmovement": "Ver movimiento",
    "inventory.stockadjustment": "Ver ajuste",
    "purchases.purchase": "Ver compra",
    "billing.billingdocument": "Ver documento",
    "business_config.businessprofile": "Ver perfil del negocio",
    "business_config.possettings": "Ver ajustes del TPV",
    "cash_register.cashmovement": "Ver sesión de caja",
    "cash_register.cashcount": "Ver sesión de caja",
    "purchases.purchasereceipt": "Ver compra",
}


def actor_display(event):
    return str(event.user) if event.user_id else "Sistema"


def _integer(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def entity_link(event, *, user):
    """Return a URL only from a closed, explicit route mapping."""
    entity_id = _integer(event.entity_id)
    if event.entity_type in {
        "business_config.businessprofile",
        "business_config.possettings",
    }:
        if not can_manage_business_settings(user):
            return None
        name = (
            "business_config:profile"
            if event.entity_type.endswith("businessprofile")
            else "business_config:pos"
        )
        return {"url": reverse(name), "label": _CTA_LABELS[event.entity_type]}
    if entity_id is None:
        return None
    if event.store_id and not can_access_store(user, event.store):
        return None
    metadata = event.metadata if isinstance(event.metadata, dict) else {}
    if event.entity_type in {"cash_register.cashmovement", "cash_register.cashcount"}:
        session_id = _integer(metadata.get("cash_session_id"))
        if session_id is None:
            return None
        from apps.cash_register.models import CashSession

        if not CashSession.objects.filter(
            pk=session_id,
            business_id=event.business_id,
            store_id=event.store_id,
        ).exists():
            return None
        return {
            "url": reverse(
                "cash_register:session_detail",
                kwargs={"store_id": event.store_id, "session_id": session_id},
            ),
            "label": _CTA_LABELS[event.entity_type],
        }
    if event.entity_type == "purchases.purchasereceipt":
        purchase_id = _integer(metadata.get("purchase_id"))
        if purchase_id is None:
            return None
        from apps.purchases.models import Purchase

        if not Purchase.objects.filter(
            pk=purchase_id,
            business_id=event.business_id,
            store_id=event.store_id,
        ).exists():
            return None
        return {
            "url": reverse("purchases:purchase_detail", kwargs={"pk": purchase_id}),
            "label": _CTA_LABELS[event.entity_type],
        }
    routes = {
        "sales.sale": (
            "sales:sale_detail",
            {"store_id": event.store_id, "sale_pk": entity_id},
        ),
        "sales.salereturn": (
            "sales:return_detail",
            {"store_id": event.store_id, "return_pk": entity_id},
        ),
        "cash_register.cashsession": (
            "cash_register:session_detail",
            {"store_id": event.store_id, "session_id": entity_id},
        ),
        "inventory.stockmovement": (
            "inventory:stock_movement_detail",
            {"pk": entity_id},
        ),
        "inventory.stockadjustment": (
            "inventory:stock_adjustment_detail",
            {"pk": entity_id},
        ),
        "purchases.purchase": ("purchases:purchase_detail", {"pk": entity_id}),
        "billing.billingdocument": (
            "billing:document_detail",
            {"store_id": event.store_id, "document_pk": entity_id},
        ),
    }
    route = routes.get(event.entity_type)
    if route is None or None in route[1].values():
        return None
    if not _entity_exists(event.entity_type, entity_id, event):
        return None
    try:
        url = reverse(route[0], kwargs=route[1])
    except NoReverseMatch:
        return None
    return {"url": url, "label": _CTA_LABELS[event.entity_type]}


def _entity_exists(entity_type, entity_id, event):
    """Validate an explicit destination without dynamically resolving models."""
    if entity_type == "sales.sale":
        from apps.sales.models import Sale

        queryset = Sale.objects.filter(pk=entity_id, business_id=event.business_id)
    elif entity_type == "sales.salereturn":
        from apps.sales.models import SaleReturn

        queryset = SaleReturn.objects.filter(
            pk=entity_id, business_id=event.business_id
        )
    elif entity_type == "cash_register.cashsession":
        from apps.cash_register.models import CashSession

        queryset = CashSession.objects.filter(
            pk=entity_id, business_id=event.business_id
        )
    elif entity_type == "inventory.stockmovement":
        from apps.inventory.models import StockMovement

        queryset = StockMovement.objects.filter(
            pk=entity_id, business_id=event.business_id
        )
    elif entity_type == "inventory.stockadjustment":
        from apps.inventory.models import StockAdjustment

        queryset = StockAdjustment.objects.filter(
            pk=entity_id, business_id=event.business_id
        )
    elif entity_type == "purchases.purchase":
        from apps.purchases.models import Purchase

        queryset = Purchase.objects.filter(pk=entity_id, business_id=event.business_id)
    elif entity_type == "billing.billingdocument":
        from apps.billing.models import BillingDocument

        queryset = BillingDocument.objects.filter(
            pk=entity_id, business_id=event.business_id
        )
    else:
        return False
    if event.store_id:
        queryset = queryset.filter(store_id=event.store_id)
    return queryset.exists()


def _field_label(key):
    return str(key).replace("_", " ").replace(".", " · ").strip().capitalize()


def _safe_value(key, value):
    if _is_secret_key(str(key)) or value == REDACTED:
        return "Dato protegido"
    if value is None:
        return "—"
    if isinstance(value, bool):
        return "Activado" if value else "Desactivado"
    if isinstance(value, dict):
        parts = [f"{_field_label(k)}: {_safe_value(k, v)}" for k, v in value.items()]
        return "; ".join(parts) or "—"
    if isinstance(value, (list, tuple)):
        return ", ".join(_safe_value(key, item) for item in value) or "—"
    if isinstance(value, float):
        return formats.number_format(Decimal(str(value)), use_l10n=True)
    if isinstance(value, str) and re.search(
        r"(?:amount|total|price|importe)", str(key), re.I
    ):
        try:
            number = Decimal(value)
        except InvalidOperation:
            pass
        else:
            return f"{formats.number_format(number, decimal_pos=2, use_l10n=True)} €"
    return str(value)


def payload_diff(event):
    old = event.old_payload or {}
    new = event.new_payload or {}
    rows = []
    for key in sorted(set(old) | set(new)):
        before, after = old.get(key), new.get(key)
        if before == after:
            continue
        rows.append(
            {
                "field": _field_label(key),
                "before": _safe_value(key, before),
                "after": _safe_value(key, after),
            }
        )
    return rows


def metadata_items(event):
    metadata = event.metadata if isinstance(event.metadata, dict) else {}
    return [
        {"field": _field_label(key), "value": _safe_value(key, value)}
        for key, value in sorted(metadata.items())
    ]


def present_event(event, *, user, detail=False):
    local_created = timezone.localtime(event.created_at)
    result = {
        "event": event,
        "actor": actor_display(event),
        "module_label": MODULE_LABELS.get(event.module, "Actividad"),
        "event_label": EVENT_LABELS.get(event.event_type, "Actividad registrada"),
        "entity_label": ENTITY_LABELS.get(event.entity_type, "Entidad"),
        "created_at": local_created,
    }
    if detail:
        result.update(
            changes=payload_diff(event),
            entity_link=entity_link(event, user=user),
            metadata=metadata_items(event) if user.role == "owner" else [],
        )
    return result
