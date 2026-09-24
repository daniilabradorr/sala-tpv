from decimal import Decimal

from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.http import QueryDict
from django.shortcuts import redirect, render
from django.views.decorators.vary import vary_on_headers
from django.utils.decorators import method_decorator
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
    get_customer_list_kpis,
    get_customer_pending_debt_sales,
    get_customers_for_business,
)
from apps.customers.services import CustomerAccountService, CustomerService
from apps.users.mixins import BusinessRequiredMixin, ManagerOrOwnerRequiredMixin
from apps.sales.selectors import get_sales_for_business
from apps.billing.selectors import billing_documents_for_customer
from apps.stores.selectors import get_stores_available_for_user
from apps.users.helpers import can_sell_in_store
from apps.core.shell import resolve_active_store
from apps.sales.forms import SaleFilterForm


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


@method_decorator(vary_on_headers("HX-Request"), name="dispatch")
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
            account_state=self.request.GET.get("account_state", ""),
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(
            {
                "query": self.request.GET.get("q", ""),
                "status": self.request.GET.get("status", "active"),
                "customer_type": self.request.GET.get("customer_type", ""),
                "account_state": self.request.GET.get("account_state", ""),
                "customer_type_choices": CustomerTypeChoices.choices,
                "kpis": get_customer_list_kpis(business=_get_business(self.request)),
            }
        )
        return context

    def render_to_response(self, context, **response_kwargs):
        if self.request.headers.get("HX-Request") == "true":
            self.template_name = "customers/partials/_customer_results.html"
        return super().render_to_response(context, **response_kwargs)


@method_decorator(vary_on_headers("HX-Request"), name="dispatch")
class CustomerDetailView(BusinessRequiredMixin, DetailView):
    template_name = "customers/customer_detail.html"
    context_object_name = "customer"

    def get_object(self, queryset=None):
        return get_customer_detail(
            business=_get_business(self.request), pk=self.kwargs["pk"]
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["account"] = self.object.account
        business = _get_business(self.request)
        stores = get_stores_available_for_user(
            user=self.request.user, only_active=False
        )
        store_ids = list(stores.values_list("pk", flat=True))
        _, active_store = resolve_active_store(self.request, user=self.request.user)
        sellable_stores = [
            store
            for store in get_stores_available_for_user(user=self.request.user)
            if can_sell_in_store(self.request.user, store)
        ]
        operational_store = (
            active_store
            if active_store is not None
            and can_sell_in_store(self.request.user, active_store)
            else next(iter(sellable_stores), None)
        )
        tab = self.request.GET.get("tab", "summary")
        if tab not in {"summary", "sales", "account", "documents"}:
            tab = "summary"
        context.update(
            {
                "tab": tab,
                "stores": stores,
                "operational_store": operational_store,
                "visible_store_ids": store_ids,
            }
        )
        if tab == "sales":
            has_filters = any(
                self.request.GET.get(key)
                for key in ("period", "status", "date_from", "date_to")
            )
            filter_form = SaleFilterForm(
                self.request.GET if has_filters else None, business=business
            )
            valid_filters = filter_form.cleaned_data if filter_form.is_valid() else {}
            period = self.request.GET.get("period", "")
            filters = {
                "customer": self.object,
                "status": valid_filters.get("status", ""),
                "date_from": valid_filters.get("date_from"),
                "date_to": valid_filters.get("date_to"),
            }
            sales = get_sales_for_business(business=business, filters=filters).filter(
                store_id__in=store_ids
            )
            store_id = self.request.GET.get("store")
            if store_id and store_id.isdigit():
                sales = sales.filter(store_id=store_id)
            context.update(
                {
                    "sales_store": store_id or "",
                    "sales_status": filters["status"],
                    "sales_period": period,
                    "date_from": self.request.GET.get("date_from", ""),
                    "date_to": self.request.GET.get("date_to", ""),
                    "sales_filter_errors": filter_form.errors,
                }
            )
            query = QueryDict(mutable=True)
            for key in ("period", "store", "status", "date_from", "date_to"):
                if self.request.GET.get(key):
                    query[key] = self.request.GET[key]
            context["sales_query"] = f"{query.urlencode()}&" if query else ""
            context["sales_page"] = Paginator(sales, 25).get_page(
                self.request.GET.get("page")
            )
        elif tab == "account":
            entries = get_customer_account_entries(
                business=business, account=self.object.account
            )
            context["entries_page"] = Paginator(entries, 25).get_page(
                self.request.GET.get("page")
            )
            context["pending_sales"] = get_customer_pending_debt_sales(
                business=business,
                customer=self.object,
                stores=sellable_stores,
            )
        elif tab == "documents":
            docs = (
                billing_documents_for_customer(business=business, customer=self.object)
                .filter(store__in=stores)
                .order_by("-operation_date", "-pk")
            )
            context["documents_page"] = Paginator(docs, 25).get_page(
                self.request.GET.get("page")
            )
        return context

    def render_to_response(self, context, **response_kwargs):
        if self.request.headers.get("HX-Request") == "true":
            self.template_name = "customers/partials/_customer_workspace_content.html"
        return super().render_to_response(context, **response_kwargs)


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
                customer, _account = CustomerService.create_customer(
                    business=business,
                    customer_data=form.cleaned_data,
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
                    business=business,
                    customer=customer,
                    customer_data=form.cleaned_data,
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
