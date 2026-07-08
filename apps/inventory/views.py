"""Views de inventario.

Regla general:
- Las views reciben la intención del usuario.
- Los forms validan entrada.
- Los selectors leen datos.
- Los services modifican datos.
- Las views NO modifican stock directamente.
- Las views NO crean StockMovement directamente.
"""

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.shortcuts import get_object_or_404, redirect, render
from django.views import View

from apps.inventory.forms import (
    InitialStockForm,
    InventoryItemCreateForm,
    InventoryItemFilterForm,
    InventoryItemUpdateForm,
    StockAdjustmentConfirmForm,
    StockAdjustmentCreateForm,
    StockAdjustmentFilterForm,
    StockAdjustmentLineForm,
    StockMovementFilterForm,
)
from apps.inventory.selectors import (
    get_inventory_dashboard_data,
    get_inventory_item_adjustment_lines,
    get_inventory_item_detail,
    get_inventory_item_latest_movements,
    get_inventory_items_for_business,
    get_stock_adjustment_detail,
    get_stock_adjustment_lines,
    get_stock_adjustments_for_business,
    get_stock_movement_detail,
    get_stock_movements_for_business,
)
from apps.inventory.services import (
    add_stock_adjustment_line,
    cancel_stock_adjustment,
    confirm_stock_adjustment,
    create_initial_stock,
    create_inventory_item,
    create_stock_adjustment,
    delete_stock_adjustment_line,
    update_inventory_item_settings,
    update_stock_adjustment_line,
)
from apps.users.mixins import (
    BusinessRequiredMixin,
    ManagerOrOwnerRequiredMixin,
)


# ==========================================================
# Helpers internos
# ==========================================================


def _add_validation_error_message(request, error):
    """Convierte ValidationError en messages.error legibles."""

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


def _add_form_error_messages(request, form):
    """Convierte errores de formulario en messages.error legibles."""

    if not form.errors:
        messages.error(request, "Revisa los datos del formulario.")
        return

    for field, errors in form.errors.items():
        for error in errors:
            if field == "__all__":
                messages.error(request, str(error))
            else:
                field_label = (
                    form.fields.get(field).label if field in form.fields else field
                )
                messages.error(request, f"{field_label}: {error}")


# ==========================================================
# Dashboard
# ==========================================================


class InventoryDashboardView(BusinessRequiredMixin, View):
    """Dashboard principal de inventario para el negocio actual."""

    template_name = "inventory/dashboard.html"
    latest_movements_limit = 10
    latest_adjustments_limit = 10

    def get(self, request):
        """Renderiza el resumen del dashboard de inventario."""

        dashboard_data = get_inventory_dashboard_data(
            request.user.business,
            latest_movements_limit=self.latest_movements_limit,
            latest_adjustments_limit=self.latest_adjustments_limit,
        )

        return render(request, self.template_name, dashboard_data)


# ==========================================================
# Items de inventario
# ==========================================================


class InventoryItemListView(BusinessRequiredMixin, View):
    """Vista de lista de items de inventario para el negocio actual."""

    template_name = "inventory/item_list.html"

    def get(self, request):
        """Renderiza la lista de items de inventario."""

        form = InventoryItemFilterForm(
            request.GET or None,
            business=request.user.business,
        )

        filters = {}

        if form.is_valid():
            filters = form.cleaned_data
        else:
            messages.warning(
                request,
                "Se ignoraron algunos filtros por datos invalidos.",
            )
            _add_form_error_messages(request, form)

        inventory_items = get_inventory_items_for_business(
            business=request.user.business,
            filters=filters,
        )

        context = {
            "form": form,
            "inventory_items": inventory_items,
        }

        return render(request, self.template_name, context)


class InventoryItemDetailView(BusinessRequiredMixin, View):
    """Vista de detalle de un item de inventario."""

    template_name = "inventory/item_detail.html"

    def get(self, request, pk):
        """Renderiza el detalle de un item de inventario."""

        inventory_item = get_inventory_item_detail(
            business=request.user.business,
            pk=pk,
        )

        latest_movements = get_inventory_item_latest_movements(
            business=request.user.business,
            inventory_item=inventory_item,
        )

        adjustment_lines = get_inventory_item_adjustment_lines(
            business=request.user.business,
            inventory_item=inventory_item,
        )

        context = {
            "inventory_item": inventory_item,
            "latest_movements": latest_movements,
            "adjustment_lines": adjustment_lines,
        }

        return render(request, self.template_name, context)


class InventoryItemCreateView(
    ManagerOrOwnerRequiredMixin,
    BusinessRequiredMixin,
    View,
):
    """Vista para crear un nuevo item de inventario."""

    template_name = "inventory/item_form.html"

    def get(self, request):
        """Renderiza el formulario para crear un nuevo item de inventario."""

        form = InventoryItemCreateForm(
            business=request.user.business,
        )

        context = {
            "form": form,
        }

        return render(request, self.template_name, context)

    def post(self, request):
        """Procesa el formulario para crear un nuevo item de inventario."""

        form = InventoryItemCreateForm(
            request.POST,
            business=request.user.business,
        )

        if not form.is_valid():
            _add_form_error_messages(request, form)
            return render(
                request,
                self.template_name,
                {"form": form},
            )

        try:
            inventory_item = create_inventory_item(
                business=request.user.business,
                store=form.cleaned_data["store"],
                product=form.cleaned_data["product"],
                minimum_stock=form.cleaned_data["minimum_stock"],
                maximum_stock=form.cleaned_data["maximum_stock"],
                location=form.cleaned_data["location"],
            )
        except ValidationError as error:
            _add_validation_error_message(request, error)
            return render(
                request,
                self.template_name,
                {"form": form},
            )

        messages.success(
            request,
            "Item de inventario creado correctamente.",
        )

        return redirect(
            "inventory:item_detail",
            pk=inventory_item.pk,
        )


class InventoryItemUpdateView(
    ManagerOrOwnerRequiredMixin,
    BusinessRequiredMixin,
    View,
):
    """Vista para actualizar configuración de un item de inventario.

    IMPORTANTE:
    Esta view NO modifica current_stock.
    """

    template_name = "inventory/item_form.html"

    def get(self, request, pk):
        """Renderiza el formulario para actualizar un item de inventario."""

        inventory_item = get_inventory_item_detail(
            business=request.user.business,
            pk=pk,
        )

        form = InventoryItemUpdateForm(
            instance=inventory_item,
            business=request.user.business,
        )

        context = {
            "inventory_item": inventory_item,
            "form": form,
        }

        return render(request, self.template_name, context)

    def post(self, request, pk):
        """Procesa el formulario para actualizar configuración de inventario."""

        inventory_item = get_inventory_item_detail(
            business=request.user.business,
            pk=pk,
        )

        form = InventoryItemUpdateForm(
            request.POST,
            instance=inventory_item,
            business=request.user.business,
        )

        if not form.is_valid():
            _add_form_error_messages(request, form)
            context = {
                "inventory_item": inventory_item,
                "form": form,
            }
            return render(request, self.template_name, context)

        try:
            inventory_item = update_inventory_item_settings(
                inventory_item=inventory_item,
                business=request.user.business,
                minimum_stock=form.cleaned_data["minimum_stock"],
                maximum_stock=form.cleaned_data["maximum_stock"],
                location=form.cleaned_data["location"],
                is_active=form.cleaned_data["is_active"],
            )
        except ValidationError as error:
            _add_validation_error_message(request, error)
            context = {
                "inventory_item": inventory_item,
                "form": form,
            }
            return render(request, self.template_name, context)

        messages.success(
            request,
            "Item de inventario actualizado correctamente.",
        )

        return redirect(
            "inventory:item_detail",
            pk=inventory_item.pk,
        )


class InventoryInitialStockView(
    ManagerOrOwnerRequiredMixin,
    BusinessRequiredMixin,
    View,
):
    """Vista para cargar stock inicial de un item de inventario."""

    template_name = "inventory/initial_stock_form.html"

    def get(self, request, pk):
        """Renderiza el formulario para inicializar stock."""

        inventory_item = get_inventory_item_detail(
            business=request.user.business,
            pk=pk,
        )

        form = InitialStockForm()

        context = {
            "inventory_item": inventory_item,
            "form": form,
        }

        return render(request, self.template_name, context)

    def post(self, request, pk):
        """Procesa el formulario de stock inicial."""

        inventory_item = get_inventory_item_detail(
            business=request.user.business,
            pk=pk,
        )

        form = InitialStockForm(request.POST)

        if not form.is_valid():
            _add_form_error_messages(request, form)
            context = {
                "inventory_item": inventory_item,
                "form": form,
            }
            return render(request, self.template_name, context)

        try:
            create_initial_stock(
                inventory_item=inventory_item,
                quantity=form.cleaned_data["quantity"],
                unit_cost=form.cleaned_data["unit_cost"],
                reason=form.cleaned_data["reason"],
                notes=form.cleaned_data["notes"],
                user=request.user,
            )
        except ValidationError as error:
            _add_validation_error_message(request, error)
            context = {
                "inventory_item": inventory_item,
                "form": form,
            }
            return render(request, self.template_name, context)

        messages.success(
            request,
            "Stock inicial cargado correctamente.",
        )

        return redirect(
            "inventory:item_detail",
            pk=inventory_item.pk,
        )


# ==========================================================
# Movimientos de stock
# ==========================================================


class StockMovementListView(BusinessRequiredMixin, View):
    """Vista de lista de movimientos de stock para el negocio actual."""

    template_name = "inventory/stock_movement_list.html"

    def get(self, request):
        """Renderiza la lista de movimientos de stock."""

        form = StockMovementFilterForm(
            request.GET or None,
            business=request.user.business,
        )

        filters = {}

        if form.is_valid():
            filters = form.cleaned_data
        else:
            messages.warning(
                request,
                "Se ignoraron algunos filtros por datos invalidos.",
            )
            _add_form_error_messages(request, form)

        stock_movements = get_stock_movements_for_business(
            business=request.user.business,
            filters=filters,
        )

        context = {
            "form": form,
            "stock_movements": stock_movements,
        }

        return render(request, self.template_name, context)


class StockMovementDetailView(BusinessRequiredMixin, View):
    """Vista de detalle de un movimiento de stock.

    Solo lectura.
    """

    template_name = "inventory/stock_movement_detail.html"

    def get(self, request, pk):
        """Renderiza el detalle de un movimiento de stock."""

        stock_movement = get_stock_movement_detail(
            business=request.user.business,
            pk=pk,
        )

        context = {
            "stock_movement": stock_movement,
        }

        return render(request, self.template_name, context)


# ==========================================================
# Ajustes de stock
# ==========================================================


class StockAdjustmentListView(BusinessRequiredMixin, View):
    """Vista de lista de ajustes de stock para el negocio actual."""

    template_name = "inventory/stock_adjustment_list.html"

    def get(self, request):
        """Renderiza la lista de ajustes de stock."""

        form = StockAdjustmentFilterForm(
            request.GET or None,
            business=request.user.business,
        )

        filters = {}

        if form.is_valid():
            filters = form.cleaned_data
        else:
            messages.warning(
                request,
                "Se ignoraron algunos filtros por datos invalidos.",
            )
            _add_form_error_messages(request, form)

        stock_adjustments = get_stock_adjustments_for_business(
            business=request.user.business,
            filters=filters,
        )

        context = {
            "form": form,
            "stock_adjustments": stock_adjustments,
        }

        return render(request, self.template_name, context)


class StockAdjustmentDetailView(BusinessRequiredMixin, View):
    """Vista de detalle de un ajuste de stock."""

    template_name = "inventory/stock_adjustment_detail.html"

    def get(self, request, pk):
        """Renderiza el detalle de un ajuste de stock."""

        stock_adjustment = get_stock_adjustment_detail(
            business=request.user.business,
            pk=pk,
        )

        lines = get_stock_adjustment_lines(
            stock_adjustment=stock_adjustment,
        )

        confirm_form = None

        if stock_adjustment.is_draft:
            confirm_form = StockAdjustmentConfirmForm(
                adjustment=stock_adjustment,
            )

        context = {
            "stock_adjustment": stock_adjustment,
            "lines": lines,
            "confirm_form": confirm_form,
        }

        return render(request, self.template_name, context)


class StockAdjustmentCreateView(
    ManagerOrOwnerRequiredMixin,
    BusinessRequiredMixin,
    View,
):
    """Vista para crear un nuevo ajuste de stock."""

    template_name = "inventory/stock_adjustment_form.html"

    def get(self, request):
        """Renderiza el formulario para crear un nuevo ajuste de stock."""

        form = StockAdjustmentCreateForm(
            business=request.user.business,
            user=request.user,
        )

        return render(
            request,
            self.template_name,
            {"form": form},
        )

    def post(self, request):
        """Procesa el formulario para crear un nuevo ajuste de stock."""

        form = StockAdjustmentCreateForm(
            request.POST,
            business=request.user.business,
            user=request.user,
        )

        if not form.is_valid():
            _add_form_error_messages(request, form)
            return render(
                request,
                self.template_name,
                {"form": form},
            )

        try:
            adjustment = create_stock_adjustment(
                business=request.user.business,
                store=form.cleaned_data["store"],
                reason=form.cleaned_data["reason"],
                notes=form.cleaned_data["notes"],
                user=request.user,
            )
        except ValidationError as error:
            _add_validation_error_message(request, error)
            return render(
                request,
                self.template_name,
                {"form": form},
            )

        messages.success(
            request,
            "Ajuste de stock creado en borrador.",
        )

        return redirect(
            "inventory:stock_adjustment_detail",
            pk=adjustment.pk,
        )


class StockAdjustmentLineCreateView(
    ManagerOrOwnerRequiredMixin,
    BusinessRequiredMixin,
    View,
):
    """Vista para crear una nueva línea de ajuste de stock."""

    template_name = "inventory/stock_adjustment_line_form.html"

    def get(self, request, adjustment_pk):
        """Renderiza el formulario para crear una nueva línea."""

        stock_adjustment = get_stock_adjustment_detail(
            business=request.user.business,
            pk=adjustment_pk,
        )

        form = StockAdjustmentLineForm(
            business=request.user.business,
            adjustment=stock_adjustment,
        )

        context = {
            "stock_adjustment": stock_adjustment,
            "form": form,
        }

        return render(request, self.template_name, context)

    def post(self, request, adjustment_pk):
        """Procesa el formulario para crear una nueva línea."""

        stock_adjustment = get_stock_adjustment_detail(
            business=request.user.business,
            pk=adjustment_pk,
        )

        form = StockAdjustmentLineForm(
            request.POST,
            business=request.user.business,
            adjustment=stock_adjustment,
        )

        if not form.is_valid():
            _add_form_error_messages(request, form)
            context = {
                "stock_adjustment": stock_adjustment,
                "form": form,
            }
            return render(request, self.template_name, context)

        try:
            add_stock_adjustment_line(
                adjustment=stock_adjustment,
                inventory_item=form.cleaned_data["inventory_item"],
                counted_stock=form.cleaned_data["counted_stock"],
                notes=form.cleaned_data["notes"],
            )
        except ValidationError as error:
            _add_validation_error_message(request, error)
            context = {
                "stock_adjustment": stock_adjustment,
                "form": form,
            }
            return render(request, self.template_name, context)

        messages.success(
            request,
            "Línea de ajuste creada correctamente.",
        )

        return redirect(
            "inventory:stock_adjustment_detail",
            pk=stock_adjustment.pk,
        )


class StockAdjustmentLineUpdateView(
    ManagerOrOwnerRequiredMixin,
    BusinessRequiredMixin,
    View,
):
    """Edita una línea existente de ajuste mientras esté en borrador."""

    template_name = "inventory/stock_adjustment_line_form.html"

    def get(self, request, adjustment_pk, line_pk):
        """Renderiza el formulario de edición de una línea."""

        stock_adjustment = get_stock_adjustment_detail(
            business=request.user.business,
            pk=adjustment_pk,
        )

        line = get_object_or_404(
            stock_adjustment.lines.select_related(
                "inventory_item",
                "product",
            ),
            pk=line_pk,
        )

        form = StockAdjustmentLineForm(
            instance=line,
            business=request.user.business,
            adjustment=stock_adjustment,
        )

        context = {
            "stock_adjustment": stock_adjustment,
            "stock_adjustment_line": line,
            "form": form,
        }

        return render(request, self.template_name, context)

    def post(self, request, adjustment_pk, line_pk):
        """Procesa cambios de una línea de ajuste."""

        stock_adjustment = get_stock_adjustment_detail(
            business=request.user.business,
            pk=adjustment_pk,
        )

        line = get_object_or_404(
            stock_adjustment.lines.select_related(
                "inventory_item",
                "product",
            ),
            pk=line_pk,
        )

        form = StockAdjustmentLineForm(
            request.POST,
            instance=line,
            business=request.user.business,
            adjustment=stock_adjustment,
        )

        if not form.is_valid():
            _add_form_error_messages(request, form)
            context = {
                "stock_adjustment": stock_adjustment,
                "stock_adjustment_line": line,
                "form": form,
            }
            return render(request, self.template_name, context)

        try:
            update_stock_adjustment_line(
                line=line,
                inventory_item=form.cleaned_data["inventory_item"],
                counted_stock=form.cleaned_data["counted_stock"],
                notes=form.cleaned_data["notes"],
            )
        except ValidationError as error:
            _add_validation_error_message(request, error)
            context = {
                "stock_adjustment": stock_adjustment,
                "stock_adjustment_line": line,
                "form": form,
            }
            return render(request, self.template_name, context)

        messages.success(
            request,
            "Línea de ajuste actualizada correctamente.",
        )

        return redirect(
            "inventory:stock_adjustment_detail",
            pk=stock_adjustment.pk,
        )


class StockAdjustmentLineDeleteView(
    ManagerOrOwnerRequiredMixin,
    BusinessRequiredMixin,
    View,
):
    """Elimina una línea de ajuste solo si el ajuste está en borrador."""

    def post(self, request, adjustment_pk, line_pk):
        """Elimina la línea y regresa al detalle del ajuste."""

        stock_adjustment = get_stock_adjustment_detail(
            business=request.user.business,
            pk=adjustment_pk,
        )

        line = get_object_or_404(
            stock_adjustment.lines.all(),
            pk=line_pk,
        )

        try:
            delete_stock_adjustment_line(line=line)
        except ValidationError as error:
            _add_validation_error_message(request, error)
            return redirect(
                "inventory:stock_adjustment_detail",
                pk=stock_adjustment.pk,
            )

        messages.success(
            request,
            "Línea de ajuste eliminada correctamente.",
        )

        return redirect(
            "inventory:stock_adjustment_detail",
            pk=stock_adjustment.pk,
        )


class StockAdjustmentConfirmView(
    ManagerOrOwnerRequiredMixin,
    BusinessRequiredMixin,
    View,
):
    """Confirma un ajuste de stock.

    La lógica real vive en services.py.
    """

    def post(self, request, pk):
        """Confirma el ajuste y aplica stock mediante service."""

        adjustment = get_stock_adjustment_detail(
            business=request.user.business,
            pk=pk,
        )

        form = StockAdjustmentConfirmForm(
            request.POST,
            adjustment=adjustment,
        )

        if not form.is_valid():
            messages.error(request, "No se pudo confirmar el ajuste.")
            _add_form_error_messages(request, form)
            return redirect(
                "inventory:stock_adjustment_detail",
                pk=adjustment.pk,
            )

        try:
            confirm_stock_adjustment(
                adjustment=adjustment,
                user=request.user,
            )
        except ValidationError as error:
            _add_validation_error_message(request, error)
            return redirect(
                "inventory:stock_adjustment_detail",
                pk=adjustment.pk,
            )

        messages.success(
            request,
            "Ajuste confirmado correctamente.",
        )

        return redirect(
            "inventory:stock_adjustment_detail",
            pk=adjustment.pk,
        )


class StockAdjustmentCancelView(
    ManagerOrOwnerRequiredMixin,
    BusinessRequiredMixin,
    View,
):
    """Cancela un ajuste de stock en borrador."""

    def post(self, request, pk):
        """Cancela el ajuste mediante service."""

        adjustment = get_stock_adjustment_detail(
            business=request.user.business,
            pk=pk,
        )

        try:
            cancel_stock_adjustment(
                adjustment=adjustment,
                user=request.user,
            )
        except ValidationError as error:
            _add_validation_error_message(request, error)
            return redirect(
                "inventory:stock_adjustment_detail",
                pk=adjustment.pk,
            )

        messages.success(
            request,
            "Ajuste cancelado correctamente.",
        )

        return redirect("inventory:stock_adjustment_detail", pk=adjustment.pk)
