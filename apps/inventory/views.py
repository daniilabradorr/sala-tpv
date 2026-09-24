"""Views de inventario.

Regla general:
- Las views reciben la intención del usuario.
- Los forms validan entrada.
- Los selectors leen datos.
- Los services modifican datos.
- Las views NO modifican stock directamente.
- Las views NO crean StockMovement directamente.
"""

from decimal import Decimal

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.vary import vary_on_headers
from django.utils.decorators import method_decorator
from django.views import View

from apps.core.htmx import add_hx_trigger
from apps.core.shell import resolve_active_store

from apps.inventory.forms import (
    InitialStockForm,
    InventoryItemCreateForm,
    InventoryItemFilterForm,
    InventoryItemUpdateForm,
    QuickStockAdjustmentForm,
    StockAdjustmentConfirmForm,
    StockAdjustmentCreateForm,
    StockAdjustmentFilterForm,
    StockAdjustmentLineForm,
    StockMovementFilterForm,
)
from apps.inventory.selectors import (
    get_inventory_dashboard_data,
    get_inventory_item_adjustments,
    get_inventory_item_detail,
    get_inventory_item_movements,
    get_inventory_items_for_business,
    get_inventory_visible_stores,
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
    prepare_quick_stock_adjustment,
    update_inventory_item_settings,
    update_stock_adjustment_line,
)
from apps.users.mixins import (
    BusinessRequiredMixin,
    ManagerOrOwnerRequiredMixin,
)
from apps.users.helpers import is_owner_or_manager


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


@method_decorator(vary_on_headers("HX-Request"), name="dispatch")
class InventoryDashboardView(BusinessRequiredMixin, View):
    """Dashboard principal de inventario para el negocio actual."""

    template_name = "inventory/dashboard.html"
    latest_movements_limit = 10
    latest_adjustments_limit = 10

    def get(self, request):
        """Renderiza el resumen del dashboard de inventario."""

        visible_stores = get_inventory_visible_stores(request.user)
        _shell_stores, active_store = resolve_active_store(request, user=request.user)
        requested_store = request.GET.get("store")
        can_all = request.user.is_superuser or is_owner_or_manager(request.user)
        is_all_stores = requested_store == "all" and can_all
        if requested_store and requested_store != "all":
            selected_store = (
                visible_stores.filter(pk=requested_store).first()
                if requested_store.isdecimal()
                else None
            )
            if selected_store is None:
                raise Http404("Tienda no disponible")
        elif is_all_stores:
            selected_store = None
        else:
            selected_store = (
                visible_stores.filter(pk=active_store.pk).first()
                if active_store
                else visible_stores.first()
            )
        scoped_stores = (
            visible_stores
            if is_all_stores
            else visible_stores.filter(pk=selected_store.pk)
            if selected_store
            else visible_stores.none()
        )
        tab = request.GET.get("tab", "stock")
        if tab not in {"stock", "movements", "adjustments"}:
            tab = "stock"

        dashboard_data = get_inventory_dashboard_data(
            request.user.business,
            stores=scoped_stores,
            latest_movements_limit=self.latest_movements_limit,
            latest_adjustments_limit=self.latest_adjustments_limit,
        )

        dashboard_data["can_manage_inventory"] = request.user.is_superuser or (
            is_owner_or_manager(request.user)
        )
        dashboard_data.update(
            {
                "visible_stores": visible_stores,
                "selected_store": selected_store,
                "is_all_stores": is_all_stores,
                "can_all_stores": can_all,
                "tab": tab,
            }
        )
        if tab == "stock":
            filter_data = request.GET.copy()
            for workspace_key in ("tab", "store", "page"):
                filter_data.pop(workspace_key, None)
            form = InventoryItemFilterForm(
                filter_data or None,
                business=request.user.business,
                stores=scoped_stores,
            )
            filters = form.cleaned_data if form.is_valid() else {}
            page = Paginator(
                get_inventory_items_for_business(
                    request.user.business, filters=filters, stores=scoped_stores
                ),
                25,
            ).get_page(request.GET.get("page"))
            dashboard_data.update(
                {"form": form, "page_obj": page, "inventory_items": page}
            )
        elif tab == "movements":
            filter_data = request.GET.copy()
            for workspace_key in ("tab", "store", "page"):
                filter_data.pop(workspace_key, None)
            form = StockMovementFilterForm(
                filter_data or None,
                business=request.user.business,
                stores=scoped_stores,
            )
            filters = form.cleaned_data if form.is_valid() else {}
            page = Paginator(
                get_stock_movements_for_business(
                    request.user.business, filters=filters, stores=scoped_stores
                ),
                25,
            ).get_page(request.GET.get("page"))
            dashboard_data.update(
                {"form": form, "page_obj": page, "stock_movements": page}
            )
        else:
            filter_data = request.GET.copy()
            for workspace_key in ("tab", "store", "page"):
                filter_data.pop(workspace_key, None)
            form = StockAdjustmentFilterForm(
                filter_data or None,
                business=request.user.business,
                stores=scoped_stores,
            )
            filters = form.cleaned_data if form.is_valid() else {}
            page = Paginator(
                get_stock_adjustments_for_business(
                    request.user.business, filters=filters, stores=scoped_stores
                ),
                25,
            ).get_page(request.GET.get("page"))
            dashboard_data.update(
                {"form": form, "page_obj": page, "stock_adjustments": page}
            )
        query = request.GET.copy()
        query.pop("page", None)
        dashboard_data["query_string"] = query.urlencode()
        template = (
            "inventory/partials/_workspace.html" if request.htmx else self.template_name
        )
        return render(request, template, dashboard_data)


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
            stores=get_inventory_visible_stores(request.user),
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
            stores=get_inventory_visible_stores(request.user),
        )

        context = {
            "form": form,
            "inventory_items": inventory_items,
            "can_manage_inventory": request.user.is_superuser
            or is_owner_or_manager(request.user),
        }

        return render(request, self.template_name, context)


@method_decorator(vary_on_headers("HX-Request"), name="dispatch")
class InventoryItemDetailView(BusinessRequiredMixin, View):
    """Vista de detalle de un item de inventario."""

    template_name = "inventory/item_detail.html"

    def get(self, request, pk):
        """Renderiza el detalle de un item de inventario."""

        inventory_item = get_inventory_item_detail(
            business=request.user.business,
            pk=pk,
            stores=get_inventory_visible_stores(request.user),
        )

        tab = request.GET.get("tab", "summary")
        if tab not in {"summary", "movements", "adjustments"}:
            tab = "summary"

        context = {
            "inventory_item": inventory_item,
            "tab": tab,
            "can_manage_inventory": request.user.is_superuser
            or request.user.role in {"owner", "manager"},
            "can_load_initial_stock": (
                inventory_item.is_active
                and inventory_item.current_stock == 0
                and not inventory_item.movements.exists()
                and (
                    request.user.is_superuser
                    or request.user.role in {"owner", "manager"}
                )
            ),
        }
        if tab == "movements":
            context["page_obj"] = Paginator(
                get_inventory_item_movements(
                    business=request.user.business, inventory_item=inventory_item
                ),
                20,
            ).get_page(request.GET.get("page"))
        elif tab == "adjustments":
            context["page_obj"] = Paginator(
                get_inventory_item_adjustments(
                    business=request.user.business, inventory_item=inventory_item
                ),
                20,
            ).get_page(request.GET.get("page"))
        template = (
            "inventory/partials/_item_tab.html" if request.htmx else self.template_name
        )
        return render(request, template, context)


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


class InventoryQuickAdjustmentView(
    ManagerOrOwnerRequiredMixin, BusinessRequiredMixin, View
):
    """Prepare a one-line draft; preparation intentionally never changes stock."""

    template_name = "inventory/quick_adjustment_form.html"

    def get(self, request, pk):
        item = get_inventory_item_detail(
            request.user.business, pk, stores=get_inventory_visible_stores(request.user)
        )
        return render(
            request,
            self.template_name,
            {"inventory_item": item, "form": QuickStockAdjustmentForm()},
        )

    def post(self, request, pk):
        item = get_inventory_item_detail(
            request.user.business, pk, stores=get_inventory_visible_stores(request.user)
        )
        form = QuickStockAdjustmentForm(request.POST)
        if not form.is_valid():
            return render(
                request,
                self.template_name,
                {"inventory_item": item, "form": form},
                status=422 if request.htmx else 200,
            )
        adjustment = prepare_quick_stock_adjustment(
            inventory_item=item,
            counted_stock=form.cleaned_data["counted_stock"],
            notes=form.cleaned_data["notes"],
            user=request.user,
        )
        messages.success(request, "Ajuste preparado. El stock todavía no ha cambiado.")
        return redirect("inventory:stock_adjustment_review", pk=adjustment.pk)


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
            stores=get_inventory_visible_stores(request.user),
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
            stores=get_inventory_visible_stores(request.user),
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
            stores=get_inventory_visible_stores(request.user),
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
            stores=get_inventory_visible_stores(request.user),
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
            stores=get_inventory_visible_stores(request.user),
        )

        context = {
            "form": form,
            "stock_adjustments": stock_adjustments,
            "can_manage_inventory": request.user.is_superuser
            or is_owner_or_manager(request.user),
        }

        return render(request, self.template_name, context)


@method_decorator(vary_on_headers("HX-Request"), name="dispatch")
class StockAdjustmentDetailView(BusinessRequiredMixin, View):
    """Vista de detalle de un ajuste de stock."""

    template_name = "inventory/stock_adjustment_detail.html"

    def get(self, request, pk):
        """Renderiza el detalle de un ajuste de stock."""

        stock_adjustment = get_stock_adjustment_detail(
            business=request.user.business,
            pk=pk,
            stores=get_inventory_visible_stores(request.user),
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
            "can_manage_inventory": request.user.is_superuser
            or request.user.role in {"owner", "manager"},
        }

        template = (
            "inventory/partials/_adjustment_lines.html"
            if request.htmx and request.GET.get("fragment") == "lines"
            else self.template_name
        )
        return render(request, template, context)


class StockAdjustmentReviewView(
    ManagerOrOwnerRequiredMixin, BusinessRequiredMixin, View
):
    """Read-only review step before the critical confirmation."""

    template_name = "inventory/stock_adjustment_review.html"

    def get(self, request, pk):
        adjustment = get_stock_adjustment_detail(
            business=request.user.business,
            pk=pk,
            stores=get_inventory_visible_stores(request.user),
        )
        if not adjustment.is_draft:
            return redirect("inventory:stock_adjustment_detail", pk=adjustment.pk)
        lines = list(get_stock_adjustment_lines(stock_adjustment=adjustment))
        context = {
            "stock_adjustment": adjustment,
            "lines": lines,
            "line_count": len(lines),
            "changed_count": sum(line.difference != 0 for line in lines),
            "incoming": sum(
                (line.difference for line in lines if line.difference > 0),
                Decimal("0.000"),
            ),
            "outgoing": abs(
                sum(
                    (line.difference for line in lines if line.difference < 0),
                    Decimal("0.000"),
                )
            ),
            "confirm_form": StockAdjustmentConfirmForm(adjustment=adjustment),
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


@method_decorator(vary_on_headers("HX-Request"), name="dispatch")
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
        if not stock_adjustment.is_draft:
            raise Http404("El ajuste ya no se puede editar")

        form = StockAdjustmentLineForm(
            business=request.user.business,
            adjustment=stock_adjustment,
        )

        context = {
            "stock_adjustment": stock_adjustment,
            "form": form,
        }

        template = (
            "inventory/partials/_adjustment_line_form.html"
            if request.htmx
            else self.template_name
        )
        return render(request, template, context)

    def post(self, request, adjustment_pk):
        """Procesa el formulario para crear una nueva línea."""

        stock_adjustment = get_stock_adjustment_detail(
            business=request.user.business,
            pk=adjustment_pk,
        )
        if not stock_adjustment.is_draft:
            raise Http404("El ajuste ya no se puede editar")

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
            template = (
                "inventory/partials/_adjustment_line_form.html"
                if request.htmx
                else self.template_name
            )
            return render(
                request,
                template,
                context,
                status=422 if request.htmx else 200,
            )

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
            template = (
                "inventory/partials/_adjustment_line_form.html"
                if request.htmx
                else self.template_name
            )
            return render(
                request,
                template,
                context,
                status=422 if request.htmx else 200,
            )

        messages.success(
            request,
            "Línea de ajuste creada correctamente.",
        )

        if request.htmx:
            return add_hx_trigger(
                HttpResponse(status=204),
                {
                    "nx:close-modal": {"id": "inventory-line-dialog"},
                    "nx:refresh-region": {"selector": "#adjustment-lines"},
                },
            )
        return redirect(
            "inventory:stock_adjustment_detail",
            pk=stock_adjustment.pk,
        )


@method_decorator(vary_on_headers("HX-Request"), name="dispatch")
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
        if not stock_adjustment.is_draft:
            raise Http404("El ajuste ya no se puede editar")

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

        template = (
            "inventory/partials/_adjustment_line_form.html"
            if request.htmx
            else self.template_name
        )
        return render(request, template, context)

    def post(self, request, adjustment_pk, line_pk):
        """Procesa cambios de una línea de ajuste."""

        stock_adjustment = get_stock_adjustment_detail(
            business=request.user.business,
            pk=adjustment_pk,
        )
        if not stock_adjustment.is_draft:
            raise Http404("El ajuste ya no se puede editar")

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
            template = (
                "inventory/partials/_adjustment_line_form.html"
                if request.htmx
                else self.template_name
            )
            return render(
                request,
                template,
                context,
                status=422 if request.htmx else 200,
            )

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
            template = (
                "inventory/partials/_adjustment_line_form.html"
                if request.htmx
                else self.template_name
            )
            return render(
                request,
                template,
                context,
                status=422 if request.htmx else 200,
            )

        messages.success(
            request,
            "Línea de ajuste actualizada correctamente.",
        )

        if request.htmx:
            return add_hx_trigger(
                HttpResponse(status=204),
                {
                    "nx:close-modal": {"id": "inventory-line-dialog"},
                    "nx:refresh-region": {"selector": "#adjustment-lines"},
                },
            )
        return redirect(
            "inventory:stock_adjustment_detail",
            pk=stock_adjustment.pk,
        )


@method_decorator(vary_on_headers("HX-Request"), name="dispatch")
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

        if request.htmx:
            return add_hx_trigger(
                HttpResponse(status=204),
                {"nx:refresh-region": {"selector": "#adjustment-lines"}},
            )
        return redirect(
            "inventory:stock_adjustment_detail",
            pk=stock_adjustment.pk,
        )


@method_decorator(vary_on_headers("HX-Request"), name="dispatch")
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
            if any("stock ha cambiado" in message for message in error.messages):
                adjustment.refresh_from_db()
                conflict_lines = [
                    line
                    for line in get_stock_adjustment_lines(adjustment)
                    if line.inventory_item.current_stock != line.system_stock
                ]
                template = (
                    "inventory/partials/_adjustment_conflict.html"
                    if request.htmx
                    else "inventory/stock_adjustment_conflict.html"
                )
                response = render(
                    request,
                    template,
                    {"stock_adjustment": adjustment, "conflict_lines": conflict_lines},
                    status=409,
                )
                if request.htmx:
                    response["X-Netxodo-Allow-Error-Swap"] = "true"
                return response
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
