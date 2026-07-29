"""Views del módulo sales.

Arquitectura:

- Las views reciben la intención del usuario.
- Los forms validan la entrada.
- Los selectors consultan la base de datos.
- Los services ejecutan las operaciones de negocio.
- Las views no calculan importes.
- Las views no modifican stock.
- Las views no cambian estados directamente.
- Las views no crean movimientos de inventario.
"""

from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import Http404
from django.shortcuts import redirect, render
from django.views import View

from apps.sales.forms import (
    SaleCancelForm,
    SaleFilterForm,
    SaleHeaderUpdateForm,
    SaleLineCreateForm,
    SaleLineUpdateForm,
    SaleOpenForm,
    SaleReturnCancelForm,
    SaleReturnCreateForm,
    SaleReturnFilterForm,
    SaleReturnLineCreateForm,
    SaleReturnLineUpdateForm,
    SaleReturnCompleteForm,
)
from apps.sales.selectors import (
    get_returnable_sale_lines,
    get_sale_detail,
    get_sale_line_detail,
    get_sale_return_detail,
    get_sale_return_line_detail,
    get_sale_returns_for_business,
    get_sales_for_business,
)
from apps.sales.services import (
    add_sale_line,
    add_sale_return_line,
    cancel_sale,
    cancel_sale_return,
    complete_sale,
    complete_sale_return,
    create_sale_return,
    delete_sale_line,
    delete_sale_return_line,
    open_sale,
    update_sale_header,
    update_sale_line,
    update_sale_return_line,
)
from apps.users.mixins import (
    BusinessRequiredMixin,
    CanSellInStoreMixin,
    StoreAccessRequiredMixin,
)


# ==========================================================
# Helpers de errores
# ==========================================================


def _get_business(request):
    """
    Devuelve el negocio del usuario autenticado.

    La interfaz de ventas siempre necesita trabajar dentro
    del contexto de un negocio concreto.
    """

    business = getattr(request.user, "business", None)

    if business is None:
        raise PermissionDenied("La interfaz de ventas requiere un negocio asociado.")

    return business


def _add_validation_error_messages(request, error):
    """
    Convierte un ValidationError del service en mensajes legibles.
    """

    if hasattr(error, "message_dict"):
        for field_errors in error.message_dict.values():
            for message in field_errors:
                messages.error(request, message)

        return

    if hasattr(error, "messages"):
        for message in error.messages:
            messages.error(request, message)

        return

    messages.error(request, str(error))


def _add_service_errors_to_form(form, error):
    """
    Añade los errores procedentes de un service al formulario.

    Los errores asociados a un campo se añaden a ese campo.
    Los demás se muestran como errores generales.
    """

    if hasattr(error, "message_dict"):
        for field, field_errors in error.message_dict.items():
            target_field = field if field in form.fields else None

            for message in field_errors:
                form.add_error(target_field, message)

        return

    if hasattr(error, "messages"):
        for message in error.messages:
            form.add_error(None, message)

        return

    form.add_error(None, str(error))


def _add_invalid_form_messages(request, form):
    """Añade mensajes para los errores de un formulario inválido."""

    if not form.errors:
        messages.error(
            request,
            "Revisa los datos introducidos.",
        )
        return

    for field, errors in form.errors.items():
        for error in errors:
            if field == "__all__":
                messages.error(request, str(error))
                continue

            field_label = form.fields[field].label if field in form.fields else field

            messages.error(
                request,
                f"{field_label}: {error}",
            )


def _ensure_sale_editable(sale):
    """
    Impide modificar una venta completada,
    cancelada o devuelta.
    """

    if not sale.is_editable:
        raise PermissionDenied("Esta venta ya no puede modificarse.")


def _ensure_return_editable(return_doc):
    """
    Impide modificar una devolución
    completada o cancelada.
    """

    if not return_doc.is_editable:
        raise PermissionDenied("Esta devolución ya no puede modificarse.")


# ==========================================================
# Mixins internos de sales
# ==========================================================


class SalesStoreContextMixin:
    """
    Recupera el negocio y la tienda resuelta por el mixin de permisos.

    StoreAccessRequiredMixin y CanSellInStoreMixin dejan la tienda
    disponible en self.store.
    """

    def get_business_and_store(self):
        business = _get_business(self.request)
        store = self.store

        if store.business_id != business.id:
            raise Http404("La tienda no pertenece al negocio actual.")

        return business, store


class SaleObjectMixin(SalesStoreContextMixin):
    """
    Recupera una venta aislada por negocio y tienda.
    """

    sale_kwarg = "sale_pk"

    def get_sale(self):
        business, store = self.get_business_and_store()

        sale = get_sale_detail(
            business=business,
            pk=self.kwargs[self.sale_kwarg],
        )

        if sale.store_id != store.id:
            raise Http404("La venta no pertenece a esta tienda.")

        return sale


class SaleReturnObjectMixin(SalesStoreContextMixin):
    """
    Recupera una devolución aislada por negocio y tienda.
    """

    return_kwarg = "return_pk"

    def get_sale_return(self):
        business, store = self.get_business_and_store()

        return_doc = get_sale_return_detail(
            business=business,
            pk=self.kwargs[self.return_kwarg],
        )

        if return_doc.store_id != store.id:
            raise Http404("La devolución no pertenece a esta tienda.")

        return return_doc


# ==========================================================
# Listado de ventas
# ==========================================================


class SaleListView(
    SalesStoreContextMixin,
    StoreAccessRequiredMixin,
    BusinessRequiredMixin,
    View,
):
    """
    Lista las ventas de una tienda.

    Esta vista solo consulta información.
    """

    template_name = "sales/sale_list.html"

    def get(self, request, store_id):
        business, store = self.get_business_and_store()

        form = SaleFilterForm(
            request.GET or None,
            business=business,
            store=store,
        )

        filters = {
            "store": store,
        }

        if form.is_valid():
            filters.update(form.cleaned_data)
            filters["store"] = store
        else:
            _add_invalid_form_messages(request, form)

        sales = get_sales_for_business(
            business=business,
            filters=filters,
        )

        context = {
            "store": store,
            "form": form,
            "sales": sales,
        }

        return render(
            request,
            self.template_name,
            context,
        )


# ==========================================================
# Detalle de venta
# ==========================================================


class SaleDetailView(
    SaleObjectMixin,
    StoreAccessRequiredMixin,
    BusinessRequiredMixin,
    View,
):
    """
    Muestra una venta con sus líneas y devoluciones.
    """

    template_name = "sales/sale_detail.html"

    def get(self, request, store_id, sale_pk):
        sale = self.get_sale()

        returnable_lines = sale.lines.none()

        if sale.is_completed:
            returnable_lines = get_returnable_sale_lines(
                business=_get_business(request),
                sale=sale,
            )

        context = {
            "store": self.store,
            "sale": sale,
            "lines": sale.lines.all(),
            "returns": sale.returns.all(),
            "returnable_lines": returnable_lines,
            "is_editable": sale.is_editable,
            "is_completed": sale.is_completed,
            "is_cancelled": sale.is_cancelled,
            "is_returned": sale.is_returned,
        }

        return render(
            request,
            self.template_name,
            context,
        )


# ==========================================================
# Apertura de venta
# ==========================================================


class SaleOpenView(
    SalesStoreContextMixin,
    CanSellInStoreMixin,
    BusinessRequiredMixin,
    View,
):
    """
    Abre una nueva venta en la tienda actual.

    La venta nace directamente en estado open.
    """

    template_name = "sales/sale_open.html"

    def get(self, request, store_id):
        business, store = self.get_business_and_store()

        form = SaleOpenForm(
            business=business,
            store=store,
            user=request.user,
        )

        return render(
            request,
            self.template_name,
            {
                "store": store,
                "form": form,
            },
        )

    def post(self, request, store_id):
        business, store = self.get_business_and_store()

        form = SaleOpenForm(
            request.POST,
            business=business,
            store=store,
            user=request.user,
        )

        if not form.is_valid():
            _add_invalid_form_messages(request, form)

            return render(
                request,
                self.template_name,
                {
                    "store": store,
                    "form": form,
                },
            )

        try:
            sale = open_sale(
                business=business,
                store=store,
                opened_by=request.user,
                customer=form.cleaned_data.get("customer"),
                document_type_requested=(form.cleaned_data["document_type_requested"]),
                cash_register=form.cleaned_data.get("cash_register"),
                cash_session=form.cleaned_data.get("cash_session"),
            )
        except ValidationError as error:
            _add_service_errors_to_form(form, error)

            return render(
                request,
                self.template_name,
                {
                    "store": store,
                    "form": form,
                },
            )

        messages.success(
            request,
            "Venta abierta correctamente.",
        )

        return redirect(
            "sales:sale_detail",
            store_id=store.pk,
            sale_pk=sale.pk,
        )


# ==========================================================
# Actualización de cabecera
# ==========================================================


class SaleHeaderUpdateView(
    SaleObjectMixin,
    CanSellInStoreMixin,
    BusinessRequiredMixin,
    View,
):
    """
    Actualiza únicamente los datos editables de la cabecera.

    Campos modificables:

    - customer
    - document_type_requested
    """

    template_name = "sales/sale_header_form.html"

    def get(self, request, store_id, sale_pk):
        business, store = self.get_business_and_store()
        sale = self.get_sale()

        _ensure_sale_editable(sale)

        form = SaleHeaderUpdateForm(
            business=business,
            store=store,
            sale=sale,
            initial={
                "customer": sale.customer,
                "document_type_requested": (sale.document_type_requested),
            },
        )

        return render(
            request,
            self.template_name,
            {
                "store": store,
                "sale": sale,
                "form": form,
            },
        )

    def post(self, request, store_id, sale_pk):
        business, store = self.get_business_and_store()
        sale = self.get_sale()

        _ensure_sale_editable(sale)

        form = SaleHeaderUpdateForm(
            request.POST,
            business=business,
            store=store,
            sale=sale,
        )

        if not form.is_valid():
            _add_invalid_form_messages(request, form)

            return render(
                request,
                self.template_name,
                {
                    "store": store,
                    "sale": sale,
                    "form": form,
                },
            )

        try:
            sale = update_sale_header(
                business=business,
                sale=sale,
                customer=form.cleaned_data.get("customer"),
                document_type_requested=(form.cleaned_data["document_type_requested"]),
                updated_by=request.user,
            )
        except ValidationError as error:
            _add_service_errors_to_form(form, error)

            return render(
                request,
                self.template_name,
                {
                    "store": store,
                    "sale": sale,
                    "form": form,
                },
            )

        messages.success(
            request,
            "Cabecera de la venta actualizada correctamente.",
        )

        return redirect(
            "sales:sale_detail",
            store_id=store.pk,
            sale_pk=sale.pk,
        )


# ==========================================================
# Añadir línea
# ==========================================================


class SaleLineAddView(
    SaleObjectMixin,
    CanSellInStoreMixin,
    BusinessRequiredMixin,
    View,
):
    """Añade un producto o servicio a una venta editable."""

    template_name = "sales/sale_line_form.html"

    def get(self, request, store_id, sale_pk):
        business, store = self.get_business_and_store()
        sale = self.get_sale()

        _ensure_sale_editable(sale)

        form = SaleLineCreateForm(
            business=business,
            store=store,
            sale=sale,
            user=request.user,
        )

        return render(
            request,
            self.template_name,
            {
                "store": store,
                "sale": sale,
                "form": form,
                "is_create": True,
            },
        )

    def post(self, request, store_id, sale_pk):
        business, store = self.get_business_and_store()
        sale = self.get_sale()

        _ensure_sale_editable(sale)

        form = SaleLineCreateForm(
            request.POST,
            business=business,
            store=store,
            sale=sale,
            user=request.user,
        )

        if not form.is_valid():
            _add_invalid_form_messages(request, form)

            return render(
                request,
                self.template_name,
                {
                    "store": store,
                    "sale": sale,
                    "form": form,
                    "is_create": True,
                },
            )

        try:
            add_sale_line(
                business=business,
                sale=sale,
                product=form.cleaned_data["product"],
                quantity=form.cleaned_data["quantity"],
                unit_base_price=form.cleaned_data.get("unit_base_price"),
                discount_amount=form.cleaned_data.get("discount_amount"),
                user=request.user,
            )
        except ValidationError as error:
            _add_service_errors_to_form(form, error)

            return render(
                request,
                self.template_name,
                {
                    "store": store,
                    "sale": sale,
                    "form": form,
                    "is_create": True,
                },
            )

        messages.success(
            request,
            "Producto añadido a la venta.",
        )

        return redirect(
            "sales:sale_detail",
            store_id=store.pk,
            sale_pk=sale.pk,
        )


# ==========================================================
# Actualizar línea
# ==========================================================


class SaleLineUpdateView(
    SaleObjectMixin,
    CanSellInStoreMixin,
    BusinessRequiredMixin,
    View,
):
    """Actualiza cantidad, precio permitido o descuento."""

    template_name = "sales/sale_line_form.html"

    def get_line(self, *, business, sale):
        return get_sale_line_detail(
            business=business,
            pk=self.kwargs["line_pk"],
            sale=sale,
        )

    def get(self, request, store_id, sale_pk, line_pk):
        business, store = self.get_business_and_store()
        sale = self.get_sale()

        _ensure_sale_editable(sale)
        line = self.get_line(
            business=business,
            sale=sale,
        )

        form = SaleLineUpdateForm(
            business=business,
            store=store,
            sale=sale,
            line=line,
            user=request.user,
            initial={
                "quantity": line.quantity,
                "unit_base_price": line.unit_base_price,
                "discount_amount": line.discount_amount,
            },
        )

        return render(
            request,
            self.template_name,
            {
                "store": store,
                "sale": sale,
                "line": line,
                "form": form,
                "is_create": False,
            },
        )

    def post(self, request, store_id, sale_pk, line_pk):
        business, store = self.get_business_and_store()
        sale = self.get_sale()

        _ensure_sale_editable(sale)
        line = self.get_line(
            business=business,
            sale=sale,
        )

        form = SaleLineUpdateForm(
            request.POST,
            business=business,
            store=store,
            sale=sale,
            line=line,
            user=request.user,
        )

        if not form.is_valid():
            _add_invalid_form_messages(request, form)

            return render(
                request,
                self.template_name,
                {
                    "store": store,
                    "sale": sale,
                    "line": line,
                    "form": form,
                    "is_create": False,
                },
            )

        try:
            update_sale_line(
                business=business,
                sale=sale,
                line=line,
                quantity=form.cleaned_data["quantity"],
                unit_base_price=form.cleaned_data.get("unit_base_price"),
                discount_amount=form.cleaned_data.get("discount_amount"),
                user=request.user,
            )
        except ValidationError as error:
            _add_service_errors_to_form(form, error)

            return render(
                request,
                self.template_name,
                {
                    "store": store,
                    "sale": sale,
                    "line": line,
                    "form": form,
                    "is_create": False,
                },
            )

        messages.success(
            request,
            "Línea actualizada correctamente.",
        )

        return redirect(
            "sales:sale_detail",
            store_id=store.pk,
            sale_pk=sale.pk,
        )


# ==========================================================
# Eliminar línea
# ==========================================================


class SaleLineDeleteView(
    SaleObjectMixin,
    CanSellInStoreMixin,
    BusinessRequiredMixin,
    View,
):
    """Retira una línea de una venta editable."""

    http_method_names = ["post"]

    def post(self, request, store_id, sale_pk, line_pk):
        business, store = self.get_business_and_store()
        sale = self.get_sale()

        _ensure_sale_editable(sale)

        line = get_sale_line_detail(
            business=business,
            pk=line_pk,
            sale=sale,
        )

        try:
            delete_sale_line(
                business=business,
                sale=sale,
                line=line,
                user=request.user,
            )
        except ValidationError as error:
            _add_validation_error_messages(
                request,
                error,
            )
        else:
            messages.success(
                request,
                "Línea retirada de la venta.",
            )

        return redirect(
            "sales:sale_detail",
            store_id=store.pk,
            sale_pk=sale.pk,
        )


# ==========================================================
# Completar venta
# ==========================================================


class SaleCompleteView(
    SaleObjectMixin,
    CanSellInStoreMixin,
    BusinessRequiredMixin,
    View,
):
    """
    Completa comercialmente una venta.

    El service debe:

    - bloquear la venta;
    - validar las líneas;
    - comprobar stock;
    - generar movimientos;
    - marcar la venta como completed;
    - impedir cierres duplicados.
    """

    http_method_names = ["post"]

    def post(self, request, store_id, sale_pk):
        business, store = self.get_business_and_store()
        sale = self.get_sale()

        try:
            sale = complete_sale(
                business=business,
                sale=sale,
                closed_by=request.user,
            )
        except ValidationError as error:
            _add_validation_error_messages(
                request,
                error,
            )
        else:
            messages.success(
                request,
                "Venta completada correctamente.",
            )

        return redirect(
            "sales:sale_detail",
            store_id=store.pk,
            sale_pk=sale.pk,
        )


# ==========================================================
# Cancelar venta
# ==========================================================


class SaleCancelView(
    SaleObjectMixin,
    CanSellInStoreMixin,
    BusinessRequiredMixin,
    View,
):
    """Cancela una venta que todavía no se ha completado."""

    template_name = "sales/sale_cancel_confirm.html"

    def get(self, request, store_id, sale_pk):
        sale = self.get_sale()

        _ensure_sale_editable(sale)

        form = SaleCancelForm(
            sale=sale,
            user=request.user,
        )

        return render(
            request,
            self.template_name,
            {
                "store": self.store,
                "sale": sale,
                "form": form,
            },
        )

    def post(self, request, store_id, sale_pk):
        business, store = self.get_business_and_store()
        sale = self.get_sale()

        _ensure_sale_editable(sale)

        form = SaleCancelForm(
            request.POST,
            sale=sale,
            user=request.user,
        )

        if not form.is_valid():
            _add_invalid_form_messages(request, form)

            return render(
                request,
                self.template_name,
                {
                    "store": store,
                    "sale": sale,
                    "form": form,
                },
            )

        try:
            sale = cancel_sale(
                business=business,
                sale=sale,
                cancelled_by=request.user,
                pin=form.cleaned_data.get("pin"),
            )
        except ValidationError as error:
            _add_service_errors_to_form(form, error)

            return render(
                request,
                self.template_name,
                {
                    "store": store,
                    "sale": sale,
                    "form": form,
                },
            )

        messages.success(
            request,
            "Venta cancelada correctamente.",
        )

        return redirect(
            "sales:sale_detail",
            store_id=store.pk,
            sale_pk=sale.pk,
        )


# ==========================================================
# Listado de devoluciones
# ==========================================================


class SaleReturnListView(
    SalesStoreContextMixin,
    StoreAccessRequiredMixin,
    BusinessRequiredMixin,
    View,
):
    """Lista las devoluciones de una tienda."""

    template_name = "sales/return_list.html"

    def get(self, request, store_id):
        business, store = self.get_business_and_store()

        form = SaleReturnFilterForm(
            request.GET or None,
            business=business,
            store=store,
        )

        filters = {
            "store": store,
        }

        if form.is_valid():
            filters.update(form.cleaned_data)
            filters["store"] = store
        else:
            _add_invalid_form_messages(request, form)

        returns = get_sale_returns_for_business(
            business=business,
            filters=filters,
        )

        return render(
            request,
            self.template_name,
            {
                "store": store,
                "form": form,
                "returns": returns,
            },
        )


# ==========================================================
# Detalle de devolución
# ==========================================================


class SaleReturnDetailView(
    SaleReturnObjectMixin,
    StoreAccessRequiredMixin,
    BusinessRequiredMixin,
    View,
):
    """Muestra una devolución y sus líneas."""

    template_name = "sales/return_detail.html"

    def get(self, request, store_id, return_pk):
        return_doc = self.get_sale_return()

        return render(
            request,
            self.template_name,
            {
                "store": self.store,
                "return_doc": return_doc,
                "lines": return_doc.lines.all(),
                "sale": return_doc.original_sale,
                "is_editable": return_doc.is_editable,
                "is_completed": return_doc.is_completed,
                "is_cancelled": return_doc.is_cancelled,
            },
        )


# ==========================================================
# Crear devolución
# ==========================================================


class SaleReturnCreateView(
    SaleObjectMixin,
    CanSellInStoreMixin,
    BusinessRequiredMixin,
    View,
):
    """Abre una devolución en borrador para una venta."""

    template_name = "sales/return_form.html"

    def get(self, request, store_id, sale_pk):
        business, store = self.get_business_and_store()
        sale = self.get_sale()

        if not sale.is_completed:
            raise PermissionDenied("Solo pueden devolverse ventas completadas.")

        form = SaleReturnCreateForm(
            business=business,
            sale=sale,
            user=request.user,
        )

        return render(
            request,
            self.template_name,
            {
                "store": store,
                "sale": sale,
                "form": form,
            },
        )

    def post(self, request, store_id, sale_pk):
        business, store = self.get_business_and_store()
        sale = self.get_sale()

        if not sale.is_completed:
            raise PermissionDenied("Solo pueden devolverse ventas completadas.")

        form = SaleReturnCreateForm(
            request.POST,
            business=business,
            sale=sale,
            user=request.user,
        )

        if not form.is_valid():
            _add_invalid_form_messages(request, form)

            return render(
                request,
                self.template_name,
                {
                    "store": store,
                    "sale": sale,
                    "form": form,
                },
            )

        try:
            return_doc = create_sale_return(
                business=business,
                store=store,
                original_sale=sale,
                created_by=request.user,
                reason=form.cleaned_data["reason"],
            )
        except ValidationError as error:
            _add_service_errors_to_form(form, error)

            return render(
                request,
                self.template_name,
                {
                    "store": store,
                    "sale": sale,
                    "form": form,
                },
            )

        messages.success(
            request,
            "Devolución abierta correctamente.",
        )

        return redirect(
            "sales:return_detail",
            store_id=store.pk,
            return_pk=return_doc.pk,
        )


# ==========================================================
# Añadir línea de devolución
# ==========================================================


class SaleReturnLineAddView(
    SaleReturnObjectMixin,
    CanSellInStoreMixin,
    BusinessRequiredMixin,
    View,
):
    """Añade una línea a una devolución en borrador."""

    template_name = "sales/return_line_form.html"

    def get(self, request, store_id, return_pk):
        business, store = self.get_business_and_store()
        return_doc = self.get_sale_return()

        _ensure_return_editable(return_doc)

        returnable_lines = get_returnable_sale_lines(
            business=business,
            sale=return_doc.original_sale,
        )

        form = SaleReturnLineCreateForm(
            business=business,
            return_doc=return_doc,
            returnable_lines=returnable_lines,
        )

        return render(
            request,
            self.template_name,
            {
                "store": store,
                "return_doc": return_doc,
                "returnable_lines": returnable_lines,
                "form": form,
                "is_create": True,
            },
        )

    def post(self, request, store_id, return_pk):
        business, store = self.get_business_and_store()
        return_doc = self.get_sale_return()

        _ensure_return_editable(return_doc)

        returnable_lines = get_returnable_sale_lines(
            business=business,
            sale=return_doc.original_sale,
        )

        form = SaleReturnLineCreateForm(
            request.POST,
            business=business,
            return_doc=return_doc,
            returnable_lines=returnable_lines,
        )

        if not form.is_valid():
            _add_invalid_form_messages(request, form)

            return render(
                request,
                self.template_name,
                {
                    "store": store,
                    "return_doc": return_doc,
                    "returnable_lines": returnable_lines,
                    "form": form,
                    "is_create": True,
                },
            )

        try:
            add_sale_return_line(
                business=business,
                return_doc=return_doc,
                original_line=form.cleaned_data["original_line"],
                quantity=form.cleaned_data["quantity"],
                restock=form.cleaned_data["restock"],
                user=request.user,
            )
        except ValidationError as error:
            _add_service_errors_to_form(form, error)

            return render(
                request,
                self.template_name,
                {
                    "store": store,
                    "return_doc": return_doc,
                    "returnable_lines": returnable_lines,
                    "form": form,
                    "is_create": True,
                },
            )

        messages.success(
            request,
            "Línea añadida a la devolución.",
        )

        return redirect(
            "sales:return_detail",
            store_id=store.pk,
            return_pk=return_doc.pk,
        )


# ==========================================================
# Actualizar línea de devolución
# ==========================================================


class SaleReturnLineUpdateView(
    SaleReturnObjectMixin,
    CanSellInStoreMixin,
    BusinessRequiredMixin,
    View,
):
    """Actualiza la cantidad de una línea de devolución."""

    template_name = "sales/return_line_form.html"

    def get_line(self, *, business, return_doc):
        return get_sale_return_line_detail(
            business=business,
            pk=self.kwargs["line_pk"],
            return_doc=return_doc,
        )

    def get(self, request, store_id, return_pk, line_pk):
        business, store = self.get_business_and_store()
        return_doc = self.get_sale_return()

        _ensure_return_editable(return_doc)

        line = self.get_line(
            business=business,
            return_doc=return_doc,
        )

        form = SaleReturnLineUpdateForm(
            business=business,
            return_doc=return_doc,
            line=line,
            initial={
                "quantity": line.quantity,
                "restock": line.restock,
            },
        )

        return render(
            request,
            self.template_name,
            {
                "store": store,
                "return_doc": return_doc,
                "line": line,
                "form": form,
                "is_create": False,
            },
        )

    def post(self, request, store_id, return_pk, line_pk):
        business, store = self.get_business_and_store()
        return_doc = self.get_sale_return()

        _ensure_return_editable(return_doc)

        line = self.get_line(
            business=business,
            return_doc=return_doc,
        )

        form = SaleReturnLineUpdateForm(
            request.POST,
            business=business,
            return_doc=return_doc,
            line=line,
        )

        if not form.is_valid():
            _add_invalid_form_messages(request, form)

            return render(
                request,
                self.template_name,
                {
                    "store": store,
                    "return_doc": return_doc,
                    "line": line,
                    "form": form,
                    "is_create": False,
                },
            )

        try:
            update_sale_return_line(
                business=business,
                return_doc=return_doc,
                line=line,
                quantity=form.cleaned_data["quantity"],
                restock=form.cleaned_data["restock"],
                user=request.user,
            )
        except ValidationError as error:
            _add_service_errors_to_form(form, error)

            return render(
                request,
                self.template_name,
                {
                    "store": store,
                    "return_doc": return_doc,
                    "line": line,
                    "form": form,
                    "is_create": False,
                },
            )

        messages.success(
            request,
            "Línea de devolución actualizada.",
        )

        return redirect(
            "sales:return_detail",
            store_id=store.pk,
            return_pk=return_doc.pk,
        )


# ==========================================================
# Eliminar línea de devolución
# ==========================================================


class SaleReturnLineDeleteView(
    SaleReturnObjectMixin,
    CanSellInStoreMixin,
    BusinessRequiredMixin,
    View,
):
    """Elimina una línea de una devolución en borrador."""

    http_method_names = ["post"]

    def post(self, request, store_id, return_pk, line_pk):
        business, store = self.get_business_and_store()
        return_doc = self.get_sale_return()

        _ensure_return_editable(return_doc)

        line = get_sale_return_line_detail(
            business=business,
            pk=line_pk,
            return_doc=return_doc,
        )

        try:
            delete_sale_return_line(
                business=business,
                return_doc=return_doc,
                line=line,
                user=request.user,
            )
        except ValidationError as error:
            _add_validation_error_messages(
                request,
                error,
            )
        else:
            messages.success(
                request,
                "Línea retirada de la devolución.",
            )

        return redirect(
            "sales:return_detail",
            store_id=store.pk,
            return_pk=return_doc.pk,
        )


# ==========================================================
# Completar devolución
# ==========================================================


class SaleReturnCompleteView(
    SaleReturnObjectMixin,
    CanSellInStoreMixin,
    BusinessRequiredMixin,
    View,
):
    """
    Completa una devolución.

    El service debe validar cantidades de forma transaccional,
    devolver stock y actualizar el estado correspondiente.
    """

    http_method_names = ["post"]

    def post(self, request, store_id, return_pk):
        business, store = self.get_business_and_store()
        return_doc = self.get_sale_return()

        form = SaleReturnCompleteForm(
            request.POST,
            return_doc=return_doc,
            user=request.user,
        )

        if not form.is_valid():
            _add_invalid_form_messages(request, form)

            return redirect(
                "sales:return_detail",
                store_id=store.pk,
                return_pk=return_doc.pk,
            )

        try:
            return_doc = complete_sale_return(
                business=business,
                return_doc=return_doc,
                completed_by=request.user,
                pin=form.cleaned_data.get("pin"),
            )
        except ValidationError as error:
            _add_validation_error_messages(request, error)
        else:
            messages.success(
                request,
                "Devolución completada correctamente.",
            )

        return redirect(
            "sales:return_detail",
            store_id=store.pk,
            return_pk=return_doc.pk,
        )


# ==========================================================
# Cancelar devolución
# ==========================================================


class SaleReturnCancelView(
    SaleReturnObjectMixin,
    CanSellInStoreMixin,
    BusinessRequiredMixin,
    View,
):
    """Cancela una devolución que permanece en borrador."""

    template_name = "sales/return_cancel_confirm.html"

    def get(self, request, store_id, return_pk):
        return_doc = self.get_sale_return()

        _ensure_return_editable(return_doc)

        form = SaleReturnCancelForm(
            return_doc=return_doc,
            user=request.user,
        )

        return render(
            request,
            self.template_name,
            {
                "store": self.store,
                "return_doc": return_doc,
                "form": form,
            },
        )

    def post(self, request, store_id, return_pk):
        business, store = self.get_business_and_store()
        return_doc = self.get_sale_return()

        _ensure_return_editable(return_doc)

        form = SaleReturnCancelForm(
            request.POST,
            return_doc=return_doc,
            user=request.user,
        )

        if not form.is_valid():
            _add_invalid_form_messages(request, form)

            return render(
                request,
                self.template_name,
                {
                    "store": store,
                    "return_doc": return_doc,
                    "form": form,
                },
            )

        try:
            return_doc = cancel_sale_return(
                business=business,
                return_doc=return_doc,
                cancelled_by=request.user,
                pin=form.cleaned_data.get("pin"),
            )
        except ValidationError as error:
            _add_service_errors_to_form(form, error)

            return render(
                request,
                self.template_name,
                {
                    "store": store,
                    "return_doc": return_doc,
                    "form": form,
                },
            )

        messages.success(
            request,
            "Devolución cancelada correctamente.",
        )

        return redirect(
            "sales:return_detail",
            store_id=store.pk,
            return_pk=return_doc.pk,
        )
