"""Views del módulo customers.

Regla general:

- Las views reciben la intención del usuario.
- Los forms validan los datos de entrada.
- Los services realizan escrituras y lógica de negocio.
- Las views no modifican balances directamente.
- Las views no crean CustomerAccountEntry directamente.
- Todas las consultas quedan aisladas por Business.
"""

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.views import View

from apps.customers.forms import (
    CustomerCreateForm,
    CustomerUpdateForm,
)
from apps.customers.models import (
    Customer,
    CustomerTypeChoices,
)
from apps.customers.services import CustomerService
from apps.users.mixins import (
    BusinessRequiredMixin,
    ManagerOrOwnerRequiredMixin,
)


# ==========================================================
# Helpers internos
# ==========================================================


def _customer_queryset(*, business):
    """Queryset base de clientes del negocio.

    En una siguiente revisión puede moverse a selectors.py.
    """

    return (
        Customer.objects.filter(
            business=business,
        )
        .select_related(
            "business",
            "account",
        )
        .order_by(
            "name",
            "pk",
        )
    )


def _add_validation_error_to_form(form, error):
    """Añade un ValidationError de servicio al formulario."""

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


# ==========================================================
# Listado
# ==========================================================


class CustomerListView(BusinessRequiredMixin, View):
    """Lista clientes del negocio actual."""

    template_name = "customers/customer_list.html"
    paginate_by = 25

    def get(self, request):
        """Muestra clientes con búsqueda y filtros básicos."""

        customers = _customer_queryset(
            business=request.user.business,
        )

        query = request.GET.get("q", "").strip()
        status = request.GET.get("status", "active").strip()
        customer_type = request.GET.get(
            "customer_type",
            "",
        ).strip()

        if query:
            customers = customers.filter(
                Q(name__icontains=query)
                | Q(legal_name__icontains=query)
                | Q(tax_identifier__icontains=query)
                | Q(foreign_id__icontains=query)
                | Q(phone__icontains=query)
                | Q(email__icontains=query)
            )

        if status == "inactive":
            customers = customers.filter(is_active=False)

        elif status == "all":
            pass

        else:
            status = "active"
            customers = customers.filter(is_active=True)

        valid_customer_types = {value for value, _label in CustomerTypeChoices.choices}

        if customer_type in valid_customer_types:
            customers = customers.filter(
                customer_type=customer_type,
            )
        else:
            customer_type = ""

        paginator = Paginator(
            customers,
            self.paginate_by,
        )

        page_obj = paginator.get_page(
            request.GET.get("page"),
        )

        context = {
            "customers": page_obj.object_list,
            "page_obj": page_obj,
            "paginator": paginator,
            "is_paginated": page_obj.has_other_pages(),
            "query": query,
            "status": status,
            "customer_type": customer_type,
            "customer_type_choices": CustomerTypeChoices.choices,
        }

        return render(
            request,
            self.template_name,
            context,
        )


# ==========================================================
# Detalle
# ==========================================================


class CustomerDetailView(BusinessRequiredMixin, View):
    """Muestra la ficha, cuenta y movimientos de un cliente."""

    template_name = "customers/customer_detail.html"
    latest_entries_limit = 20

    def get(self, request, pk):
        """Renderiza el detalle del cliente."""

        customer = get_object_or_404(
            _customer_queryset(
                business=request.user.business,
            ),
            pk=pk,
        )

        account = getattr(
            customer,
            "account",
            None,
        )

        account_entries = []

        if account:
            account_entries = account.entries.select_related(
                "created_by",
            ).order_by(
                "-created_at",
                "-pk",
            )[: self.latest_entries_limit]

        context = {
            "customer": customer,
            "account": account,
            "account_entries": account_entries,
        }

        return render(
            request,
            self.template_name,
            context,
        )


# ==========================================================
# Creación
# ==========================================================


class CustomerCreateView(BusinessRequiredMixin, View):
    """Crea un cliente y su cuenta en una sola operación."""

    template_name = "customers/customer_form.html"

    def get(self, request):
        """Muestra el formulario de creación."""

        form = CustomerCreateForm(
            business=request.user.business,
        )

        context = {
            "form": form,
            "is_create": True,
        }

        return render(
            request,
            self.template_name,
            context,
        )

    def post(self, request):
        """Procesa la creación del cliente."""

        form = CustomerCreateForm(
            request.POST,
            business=request.user.business,
        )

        if not form.is_valid():
            return render(
                request,
                self.template_name,
                {
                    "form": form,
                    "is_create": True,
                },
            )

        try:
            customer, _account = CustomerService.create_customer(
                business=request.user.business,
                customer_data=form.cleaned_data,
                credit_limit=form.cleaned_data["credit_limit"],
                is_blocked=form.cleaned_data["is_blocked"],
            )

        except ValidationError as error:
            _add_validation_error_to_form(
                form,
                error,
            )

            return render(
                request,
                self.template_name,
                {
                    "form": form,
                    "is_create": True,
                },
            )

        messages.success(
            request,
            "Cliente creado correctamente.",
        )

        return redirect(
            "customers:customer_detail",
            pk=customer.pk,
        )


# ==========================================================
# Edición
# ==========================================================


class CustomerUpdateView(
    ManagerOrOwnerRequiredMixin,
    BusinessRequiredMixin,
    View,
):
    """Actualiza la ficha de un cliente.

    En esta primera versión, únicamente owner y manager pueden
    modificar la ficha completa.
    """

    template_name = "customers/customer_form.html"

    def get_customer(self, request, pk):
        """Obtiene el cliente dentro del negocio actual."""

        return get_object_or_404(
            _customer_queryset(
                business=request.user.business,
            ),
            pk=pk,
        )

    def get(self, request, pk):
        """Muestra el formulario de edición."""

        customer = self.get_customer(
            request,
            pk,
        )

        form = CustomerUpdateForm(
            instance=customer,
            business=request.user.business,
        )

        context = {
            "customer": customer,
            "form": form,
            "is_create": False,
        }

        return render(
            request,
            self.template_name,
            context,
        )

    def post(self, request, pk):
        """Procesa la actualización del cliente."""

        customer = self.get_customer(
            request,
            pk,
        )

        form = CustomerUpdateForm(
            request.POST,
            instance=customer,
            business=request.user.business,
        )

        if not form.is_valid():
            return render(
                request,
                self.template_name,
                {
                    "customer": customer,
                    "form": form,
                    "is_create": False,
                },
            )

        try:
            customer = CustomerService.update_customer(
                business=request.user.business,
                customer=customer,
                customer_data=form.cleaned_data,
            )

        except ValidationError as error:
            _add_validation_error_to_form(
                form,
                error,
            )

            return render(
                request,
                self.template_name,
                {
                    "customer": customer,
                    "form": form,
                    "is_create": False,
                },
            )

        messages.success(
            request,
            "Cliente actualizado correctamente.",
        )

        return redirect(
            "customers:customer_detail",
            pk=customer.pk,
        )


# ==========================================================
# Desactivación
# ==========================================================


class CustomerDeactivateView(
    ManagerOrOwnerRequiredMixin,
    BusinessRequiredMixin,
    View,
):
    """Desactiva un cliente sin borrar su histórico."""

    http_method_names = ["post"]

    def post(self, request, pk):
        """Procesa la desactivación del cliente."""

        customer = get_object_or_404(
            _customer_queryset(
                business=request.user.business,
            ),
            pk=pk,
        )

        try:
            customer = CustomerService.deactivate_customer(
                business=request.user.business,
                customer=customer,
            )

        except ValidationError as error:
            if hasattr(error, "messages"):
                for message in error.messages:
                    messages.error(
                        request,
                        message,
                    )
            else:
                messages.error(
                    request,
                    str(error),
                )

            return redirect(
                "customers:customer_detail",
                pk=customer.pk,
            )

        messages.success(
            request,
            "Cliente desactivado correctamente.",
        )

        return redirect(
            "customers:customer_detail",
            pk=customer.pk,
        )
