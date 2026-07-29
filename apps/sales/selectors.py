"""Selectors del módulo sales.

Los selectors contienen consultas reutilizables del dominio de ventas.

Reglas:
- Aquí solo se leen datos.
- No se crean ni modifican ventas.
- No se recalculan importes.
- No se modifican existencias.
- No se completan ni cancelan operaciones.
- Todas las consultas deben quedar aisladas por business.
"""

from decimal import Decimal

from django.db.models import (
    DecimalField,
    ExpressionWrapper,
    F,
    Prefetch,
    Q,
    Sum,
    Value,
)
from django.db.models.functions import Coalesce
from django.shortcuts import get_object_or_404

from apps.sales.models import (
    PaymentStatusChoices,
    RequestedDocumentTypeChoices,
    Sale,
    SaleLine,
    SaleReturn,
    SaleReturnLine,
    SaleReturnStatusChoices,
    SaleStatusChoices,
)


# ==========================================================
# Helpers internos
# ==========================================================


def _sale_base_queryset():
    """
    QuerySet base de ventas con sus relaciones principales.

    Se utiliza internamente para evitar repetir select_related
    en los distintos selectors.
    """

    return Sale.objects.select_related(
        "business",
        "store",
        "cash_register",
        "cash_session",
        "customer",
        "opened_by",
        "closed_by",
    )


def _sale_line_base_queryset():
    """QuerySet base de líneas de venta."""

    return SaleLine.objects.select_related(
        "business",
        "sale",
        "sale__store",
        "product",
    )


def _sale_return_base_queryset():
    """QuerySet base de devoluciones."""

    return SaleReturn.objects.select_related(
        "business",
        "store",
        "original_sale",
        "original_sale__store",
        "original_sale__customer",
        "created_by",
    )


def _sale_return_line_base_queryset():
    """QuerySet base de líneas de devolución."""

    return SaleReturnLine.objects.select_related(
        "business",
        "return_doc",
        "return_doc__original_sale",
        "original_line",
        "original_line__sale",
        "original_line__product",
    )


# ==========================================================
# Sale
# ==========================================================


def get_sales_for_business(*, business, filters=None):
    """
    Devuelve las ventas pertenecientes a un negocio.

    Filtros admitidos:
    - store
    - customer
    - opened_by
    - status
    - payment_status
    - document_type_requested
    - date_from
    - date_to
    - query

    `date_from` y `date_to` deben ser objetos date válidos,
    normalmente procedentes de un formulario ya validado.
    """

    if business is None:
        return Sale.objects.none()

    filters = filters or {}

    queryset = _sale_base_queryset().filter(
        business=business,
    )

    store = filters.get("store")
    customer = filters.get("customer")
    opened_by = filters.get("opened_by")
    status = filters.get("status")
    payment_status = filters.get("payment_status")
    document_type_requested = filters.get("document_type_requested")
    date_from = filters.get("date_from")
    date_to = filters.get("date_to")
    query = (filters.get("query") or "").strip()

    if store:
        queryset = queryset.filter(store=store)

    if customer:
        queryset = queryset.filter(customer=customer)

    if opened_by:
        queryset = queryset.filter(opened_by=opened_by)

    if status in SaleStatusChoices.values:
        queryset = queryset.filter(status=status)

    if payment_status in PaymentStatusChoices.values:
        queryset = queryset.filter(
            payment_status=payment_status,
        )

    if document_type_requested in RequestedDocumentTypeChoices.values:
        queryset = queryset.filter(
            document_type_requested=document_type_requested,
        )

    if date_from:
        queryset = queryset.filter(
            created_at__date__gte=date_from,
        )

    if date_to:
        queryset = queryset.filter(
            created_at__date__lte=date_to,
        )

    if query:
        search_condition = (
            Q(store__name__icontains=query)
            | Q(store__code__icontains=query)
            | Q(customer__name__icontains=query)
            | Q(customer__legal_name__icontains=query)
            | Q(customer__tax_identifier__icontains=query)
            | Q(opened_by__email__icontains=query)
            | Q(opened_by__first_name__icontains=query)
            | Q(opened_by__last_name__icontains=query)
            | Q(closed_by__email__icontains=query)
            | Q(closed_by__first_name__icontains=query)
            | Q(closed_by__last_name__icontains=query)
        )

        if query.isdigit():
            search_condition |= Q(pk=int(query))

        queryset = queryset.filter(search_condition)

    return queryset.order_by(
        "-created_at",
        "-pk",
    )


def get_sale_detail(*, business, pk):
    """
    Devuelve una venta concreta con sus líneas y devoluciones.

    La búsqueda incluye business para impedir que un usuario
    acceda a ventas de otra empresa modificando la URL.
    """

    sale_lines_queryset = (
        _sale_line_base_queryset()
        .select_related(
            "product__tax",
            "product__category",
        )
        .order_by(
            "created_at",
            "pk",
        )
    )

    return_lines_queryset = (
        _sale_return_line_base_queryset()
        .select_related(
            "original_line__product",
        )
        .order_by(
            "created_at",
            "pk",
        )
    )

    returns_queryset = (
        _sale_return_base_queryset()
        .prefetch_related(
            Prefetch(
                "lines",
                queryset=return_lines_queryset,
            ),
        )
        .order_by(
            "-created_at",
            "-pk",
        )
    )

    queryset = (
        _sale_base_queryset()
        .filter(
            business=business,
        )
        .prefetch_related(
            Prefetch(
                "lines",
                queryset=sale_lines_queryset,
            ),
            Prefetch(
                "returns",
                queryset=returns_queryset,
            ),
        )
    )

    return get_object_or_404(
        queryset,
        pk=pk,
    )


def get_editable_sales_for_store(
    *,
    business,
    store,
    opened_by=None,
):
    """
    Devuelve ventas modificables de una tienda.

    Una venta se considera modificable cuando permanece:
    - en borrador;
    - abierta.

    Puede limitarse opcionalmente al usuario que la abrió.
    """

    if business is None or store is None:
        return Sale.objects.none()

    queryset = _sale_base_queryset().filter(
        business=business,
        store=store,
        status__in=[
            SaleStatusChoices.DRAFT,
            SaleStatusChoices.OPEN,
        ],
    )

    if opened_by:
        queryset = queryset.filter(
            opened_by=opened_by,
        )

    return queryset.order_by(
        "-created_at",
        "-pk",
    )


def get_returnable_sales_for_business(
    *,
    business,
    store=None,
    customer=None,
    query="",
):
    """
    Devuelve ventas que pueden ser origen de una devolución.

    Una venta completamente devuelta debería tener estado returned,
    por lo que aquí se seleccionan ventas todavía completed.

    La validación definitiva se realizará en services.py porque
    pueden existir devoluciones parciales anteriores.
    """

    if business is None:
        return Sale.objects.none()

    queryset = (
        _sale_base_queryset()
        .filter(
            business=business,
            status=SaleStatusChoices.COMPLETED,
            lines__isnull=False,
        )
        .distinct()
    )

    if store:
        queryset = queryset.filter(
            store=store,
        )

    if customer:
        queryset = queryset.filter(
            customer=customer,
        )

    query = (query or "").strip()

    if query:
        search_condition = (
            Q(store__name__icontains=query)
            | Q(store__code__icontains=query)
            | Q(customer__name__icontains=query)
            | Q(customer__legal_name__icontains=query)
            | Q(customer__tax_identifier__icontains=query)
        )

        if query.isdigit():
            search_condition |= Q(pk=int(query))

        queryset = queryset.filter(search_condition)

    return queryset.order_by(
        "-completed_at",
        "-pk",
    )


def get_latest_sales_for_business(
    *,
    business,
    store=None,
    limit=10,
):
    """Devuelve las últimas ventas de un negocio o tienda."""

    if business is None:
        return Sale.objects.none()

    queryset = _sale_base_queryset().filter(
        business=business,
    )

    if store:
        queryset = queryset.filter(
            store=store,
        )

    return queryset.order_by(
        "-created_at",
        "-pk",
    )[:limit]


# ==========================================================
# SaleLine
# ==========================================================


def get_sale_lines(*, business, sale):
    """
    Devuelve las líneas de una venta concreta.

    Se filtra también por business para mantener el aislamiento
    multiempresa aunque ya se haya recibido la venta.
    """

    if business is None or sale is None:
        return SaleLine.objects.none()

    return (
        _sale_line_base_queryset()
        .filter(
            business=business,
            sale=sale,
        )
        .select_related(
            "product__tax",
            "product__category",
        )
        .order_by(
            "created_at",
            "pk",
        )
    )


def get_sale_line_detail(
    *,
    business,
    pk,
    sale=None,
):
    """
    Devuelve una línea de venta concreta.

    Si se recibe `sale`, también comprueba que la línea pertenece
    a esa venta.
    """

    queryset = _sale_line_base_queryset().filter(
        business=business,
    )

    if sale is not None:
        queryset = queryset.filter(
            sale=sale,
        )

    return get_object_or_404(
        queryset,
        pk=pk,
    )


def get_returnable_sale_lines(*, business, sale):
    """
    Devuelve las líneas de una venta que todavía admiten devolución.

    Añade dos valores calculados:

    - returned_quantity:
      cantidad ya devuelta mediante devoluciones completadas.

    - returnable_quantity:
      cantidad que todavía podría devolverse.

    Las devoluciones en borrador o canceladas no reducen la cantidad
    disponible. El service volverá a comprobarlo transaccionalmente
    antes de completar la devolución.
    """

    if business is None or sale is None:
        return SaleLine.objects.none()

    quantity_field = DecimalField(
        max_digits=14,
        decimal_places=3,
    )

    return (
        _sale_line_base_queryset()
        .filter(
            business=business,
            sale=sale,
        )
        .annotate(
            returned_quantity=Coalesce(
                Sum(
                    "return_lines__quantity",
                    filter=Q(
                        return_lines__return_doc__status=(
                            SaleReturnStatusChoices.COMPLETED
                        ),
                    ),
                ),
                Value(Decimal("0.000")),
                output_field=quantity_field,
            ),
        )
        .annotate(
            returnable_quantity=ExpressionWrapper(
                F("quantity") - F("returned_quantity"),
                output_field=quantity_field,
            ),
        )
        .filter(
            returnable_quantity__gt=Decimal("0.000"),
        )
        .order_by(
            "created_at",
            "pk",
        )
    )


def get_completed_returned_quantity_for_line(
    *,
    business,
    original_line,
):
    """
    Devuelve la cantidad total ya devuelta de una línea.

    Solo cuenta devoluciones completadas.
    """

    if business is None or original_line is None:
        return Decimal("0.000")

    quantity_field = DecimalField(
        max_digits=14,
        decimal_places=3,
    )

    result = SaleReturnLine.objects.filter(
        business=business,
        original_line=original_line,
        return_doc__status=SaleReturnStatusChoices.COMPLETED,
    ).aggregate(
        total=Coalesce(
            Sum("quantity"),
            Value(Decimal("0.000")),
            output_field=quantity_field,
        ),
    )

    return result["total"]


# ==========================================================
# SaleReturn
# ==========================================================


def get_sale_returns_for_business(*, business, filters=None):
    """
    Devuelve las devoluciones pertenecientes a un negocio.

    Filtros admitidos:
    - store
    - original_sale
    - created_by
    - status
    - date_from
    - date_to
    - query
    """

    if business is None:
        return SaleReturn.objects.none()

    filters = filters or {}

    queryset = _sale_return_base_queryset().filter(
        business=business,
    )

    store = filters.get("store")
    original_sale = filters.get("original_sale")
    created_by = filters.get("created_by")
    status = filters.get("status")
    date_from = filters.get("date_from")
    date_to = filters.get("date_to")
    query = (filters.get("query") or "").strip()

    if store:
        queryset = queryset.filter(
            store=store,
        )

    if original_sale:
        queryset = queryset.filter(
            original_sale=original_sale,
        )

    if created_by:
        queryset = queryset.filter(
            created_by=created_by,
        )

    if status in SaleReturnStatusChoices.values:
        queryset = queryset.filter(
            status=status,
        )

    if date_from:
        queryset = queryset.filter(
            created_at__date__gte=date_from,
        )

    if date_to:
        queryset = queryset.filter(
            created_at__date__lte=date_to,
        )

    if query:
        search_condition = (
            Q(reason__icontains=query)
            | Q(store__name__icontains=query)
            | Q(store__code__icontains=query)
            | Q(original_sale__customer__name__icontains=query)
            | Q(original_sale__customer__legal_name__icontains=query)
            | Q(created_by__email__icontains=query)
            | Q(created_by__first_name__icontains=query)
            | Q(created_by__last_name__icontains=query)
        )

        if query.isdigit():
            search_condition |= Q(pk=int(query)) | Q(original_sale_id=int(query))

        queryset = queryset.filter(search_condition)

    return queryset.order_by(
        "-created_at",
        "-pk",
    )


def get_sale_return_detail(*, business, pk):
    """
    Devuelve una devolución concreta con todas sus líneas.

    La consulta queda restringida al negocio recibido.
    """

    return_lines_queryset = (
        _sale_return_line_base_queryset()
        .filter(
            business=business,
        )
        .select_related(
            "original_line__product",
            "original_line__sale",
        )
        .order_by(
            "created_at",
            "pk",
        )
    )

    queryset = (
        _sale_return_base_queryset()
        .filter(
            business=business,
        )
        .prefetch_related(
            Prefetch(
                "lines",
                queryset=return_lines_queryset,
            ),
        )
    )

    return get_object_or_404(
        queryset,
        pk=pk,
    )


def get_sale_returns_for_sale(*, business, sale):
    """Devuelve las devoluciones asociadas a una venta."""

    if business is None or sale is None:
        return SaleReturn.objects.none()

    return (
        _sale_return_base_queryset()
        .filter(
            business=business,
            original_sale=sale,
        )
        .prefetch_related(
            Prefetch(
                "lines",
                queryset=_sale_return_line_base_queryset().order_by(
                    "created_at",
                    "pk",
                ),
            ),
        )
        .order_by(
            "-created_at",
            "-pk",
        )
    )


def get_editable_returns_for_sale(*, business, sale):
    """
    Devuelve devoluciones en borrador relacionadas con una venta.

    Las devoluciones completadas o canceladas no son editables.
    """

    if business is None or sale is None:
        return SaleReturn.objects.none()

    return (
        _sale_return_base_queryset()
        .filter(
            business=business,
            original_sale=sale,
            status=SaleReturnStatusChoices.DRAFT,
        )
        .order_by(
            "-created_at",
            "-pk",
        )
    )


# ==========================================================
# SaleReturnLine
# ==========================================================


def get_sale_return_lines(*, business, return_doc):
    """Devuelve las líneas de una devolución concreta."""

    if business is None or return_doc is None:
        return SaleReturnLine.objects.none()

    return (
        _sale_return_line_base_queryset()
        .filter(
            business=business,
            return_doc=return_doc,
        )
        .order_by(
            "created_at",
            "pk",
        )
    )


def get_sale_return_line_detail(
    *,
    business,
    pk,
    return_doc=None,
):
    """
    Devuelve una línea de devolución concreta.

    Si se recibe `return_doc`, comprueba que la línea pertenece
    a esa devolución.
    """

    queryset = _sale_return_line_base_queryset().filter(
        business=business,
    )

    if return_doc is not None:
        queryset = queryset.filter(
            return_doc=return_doc,
        )

    return get_object_or_404(
        queryset,
        pk=pk,
    )
