from decimal import Decimal

from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.shortcuts import redirect, render
from django.views import View
from django.views.generic import ListView, DetailView

from apps.customers.forms import (
    CustomerAccountSettingsForm,
    CustomerCreateForm,
    CustomerUpdateForm,
)
from apps.customers.models import CustomerTypeChoices
from apps.customers.selectors import (
    get_customer_account_entries,
    get_customer_detail,
    get_customers_for_business,
)
from apps.customers.services import CustomerAccountService, CustomerService
from apps.users.mixins import BusinessRequiredMixin, ManagerOrOwnerRequiredMixin


def _get_business(request):
    business = getattr(request.user, "business", None)
    if business is None:
        raise PermissionDenied("La interfaz de clientes requiere un negocio asociado.")
    return business


def add_service_errors(form, error):
    if hasattr(error, "error_dict"):
        for field, errors in error.message_dict.items():
            for message in errors:
                form.add_error(field if field in form.fields else None, message)
    else:
        form.add_error(None, error.message if hasattr(error, "message") else str(error))


class CustomerListView(BusinessRequiredMixin, ListView):
    template_name = "customers/customer_list.html"
    context_object_name = "customers"
    paginate_by = 25

    def get_queryset(self):
        business = _get_business(self.request)
        return get_customers_for_business(
            business=business,
            query=self.request.GET.get("q", ""),
            status=self.request.GET.get("status", "active"),
            customer_type=self.request.GET.get("customer_type", ""),
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(
            {
                "query": self.request.GET.get("q", ""),
                "status": self.request.GET.get("status", "active"),
                "customer_type": self.request.GET.get("customer_type", ""),
                "customer_types": CustomerTypeChoices.choices,
            }
        )
        return context


class CustomerDetailView(BusinessRequiredMixin, DetailView):
    template_name = "customers/customer_detail.html"
    context_object_name = "customer"

    def get_object(self, queryset=None):
        return get_customer_detail(
            business=_get_business(self.request), pk=self.kwargs["pk"]
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["entries"] = get_customer_account_entries(
            business=_get_business(self.request), account=self.object.account, limit=20
        )
        return context


class CustomerCreateView(BusinessRequiredMixin, View):
    template_name = "customers/customer_form.html"

    def get(self, request):
        return render(
            request,
            self.template_name,
            {
                "form": CustomerCreateForm(business=_get_business(request)),
                "is_create": True,
            },
        )

    def post(self, request):
        business = _get_business(request)
        form = CustomerCreateForm(request.POST, business=business)
        if form.is_valid():
            try:
                customer = CustomerService.create_customer(
                    business=business,
                    data=form.cleaned_data,
                    credit_limit=Decimal("0.00"),
                    is_blocked=False,
                )
            except ValidationError as error:
                add_service_errors(form, error)
            else:
                messages.success(request, "Cliente creado correctamente.")
                return redirect("customers:customer_detail", pk=customer.pk)
        return render(request, self.template_name, {"form": form, "is_create": True})


class CustomerUpdateView(ManagerOrOwnerRequiredMixin, BusinessRequiredMixin, View):
    template_name = "customers/customer_form.html"

    def get(self, request, pk):
        customer = get_customer_detail(business=_get_business(request), pk=pk)
        return render(
            request,
            self.template_name,
            {
                "form": CustomerUpdateForm(
                    instance=customer, business=_get_business(request)
                ),
                "customer": customer,
            },
        )

    def post(self, request, pk):
        business = _get_business(request)
        customer = get_customer_detail(business=business, pk=pk)
        form = CustomerUpdateForm(request.POST, instance=customer, business=business)
        if form.is_valid():
            try:
                customer = CustomerService.update_customer(
                    business=business, customer=customer, data=form.cleaned_data
                )
            except ValidationError as error:
                add_service_errors(form, error)
            else:
                messages.success(request, "Cliente actualizado correctamente.")
                return redirect("customers:customer_detail", pk=customer.pk)
        return render(request, self.template_name, {"form": form, "customer": customer})


class CustomerDeactivateView(ManagerOrOwnerRequiredMixin, BusinessRequiredMixin, View):
    http_method_names = ["post"]

    def post(self, request, pk):
        customer = get_customer_detail(business=_get_business(request), pk=pk)
        CustomerService.deactivate_customer(
            business=_get_business(request), customer=customer
        )
        messages.success(request, "Cliente desactivado correctamente.")
        return redirect("customers:customer_detail", pk=pk)


class CustomerReactivateView(ManagerOrOwnerRequiredMixin, BusinessRequiredMixin, View):
    http_method_names = ["post"]

    def post(self, request, pk):
        customer = get_customer_detail(business=_get_business(request), pk=pk)
        CustomerService.reactivate_customer(
            business=_get_business(request), customer=customer
        )
        messages.success(request, "Cliente reactivado correctamente.")
        return redirect("customers:customer_detail", pk=pk)


class CustomerAccountSettingsView(
    ManagerOrOwnerRequiredMixin, BusinessRequiredMixin, View
):
    template_name = "customers/customer_account_settings.html"

    def get(self, request, pk):
        customer = get_customer_detail(business=_get_business(request), pk=pk)
        return render(
            request,
            self.template_name,
            {
                "customer": customer,
                "form": CustomerAccountSettingsForm(instance=customer.account),
            },
        )

    def post(self, request, pk):
        business = _get_business(request)
        customer = get_customer_detail(business=business, pk=pk)
        form = CustomerAccountSettingsForm(request.POST, instance=customer.account)
        if form.is_valid():
            try:
                CustomerAccountService.update_account_settings(
                    business=business,
                    account=customer.account,
                    credit_limit=form.cleaned_data["credit_limit"],
                    is_blocked=form.cleaned_data["is_blocked"],
                )
            except ValidationError as error:
                add_service_errors(form, error)
            else:
                messages.success(request, "Configuración de cuenta actualizada.")
                return redirect("customers:customer_detail", pk=customer.pk)
        return render(request, self.template_name, {"customer": customer, "form": form})
