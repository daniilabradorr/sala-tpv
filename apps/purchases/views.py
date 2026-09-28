from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.db.models import Q
from django.http import HttpResponse, HttpResponseRedirect
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views import View
from django.views.generic import ListView

from apps.purchases.forms import (
    PurchaseFilterForm,
    PurchaseCreateForm,
    PurchaseLineCreateForm,
    PurchaseLineUpdateForm,
    PurchaseReceiptForm,
    PurchaseUpdateForm,
    SupplierForm,
    SupplierFilterForm,
    SupplierPurchaseFilterForm,
)
from apps.catalog.models import Product
from apps.core.htmx import add_hx_trigger
from apps.purchases.models import Purchase, PurchaseStatusChoices
from apps.purchases.selectors import (
    get_accessible_purchase_stores,
    get_purchase_detail,
    get_purchase_lines,
    get_purchase_list_kpis,
    get_purchase_list,
    get_purchase_progress,
    get_purchase_receipts,
    get_supplier_detail,
    get_suppliers_for_business,
)
from apps.purchases.services import (
    add_purchase_line,
    cancel_purchase,
    create_purchase,
    create_supplier,
    delete_purchase_line,
    order_purchase,
    register_purchase_receipt,
    update_purchase_header,
    update_purchase_line,
    update_supplier,
)
from apps.users.mixins import BusinessRequiredMixin, ManagerOrOwnerRequiredMixin
from apps.core.shell import resolve_active_store
from django.utils.decorators import method_decorator
from django.views.decorators.vary import vary_on_headers


def _business(request):
    business = getattr(request.user, "business", None)
    if business is None:
        raise PermissionDenied("La interfaz de compras requiere un negocio.")
    return business


def _service_errors(form, error):
    if hasattr(error, "message_dict"):
        for field, errors in error.message_dict.items():
            for message in errors:
                form.add_error(field if field in form.fields else None, message)
    else:
        form.add_error(None, str(error))


def _page_query(request, *, effective_store=None, include_store=False):
    query = request.GET.copy()
    query.pop("page", None)
    if include_store and "store" not in query:
        query["store"] = str(effective_store.pk) if effective_store else ""
    encoded = query.urlencode()
    return f"{encoded}&" if encoded else ""


def _is_htmx(request):
    return request.headers.get("HX-Request") == "true"


class _PurchasesView(ManagerOrOwnerRequiredMixin, BusinessRequiredMixin):
    pass


@method_decorator(vary_on_headers("HX-Request"), name="dispatch")
class SupplierListView(_PurchasesView, ListView):
    template_name = "purchases/supplier_list.html"
    context_object_name = "suppliers"
    paginate_by = 25

    def get_queryset(self):
        self.filter_form = SupplierFilterForm(self.request.GET or None)
        data = self.filter_form.cleaned_data if self.filter_form.is_valid() else {}
        return get_suppliers_for_business(
            business=_business(self.request),
            query=data.get("q", ""),
            status=data.get("status", "active"),
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["filter_form"] = self.filter_form
        context["page_query"] = _page_query(self.request)
        context["pagination_target"] = "#supplier-results"
        return context

    def render_to_response(self, context, **kwargs):
        if self.request.headers.get("HX-Request") == "true":
            self.template_name = "purchases/partials/_supplier_results.html"
        return super().render_to_response(context, **kwargs)


class SupplierCreateView(_PurchasesView, View):
    template_name = "purchases/supplier_form.html"

    def get(self, request):
        return render(
            request, self.template_name, {"form": SupplierForm(), "is_create": True}
        )

    def post(self, request):
        form = SupplierForm(request.POST)
        if form.is_valid():
            try:
                supplier = create_supplier(
                    business=_business(request), user=request.user, **form.cleaned_data
                )
            except ValidationError as error:
                _service_errors(form, error)
            else:
                messages.success(request, "Proveedor creado correctamente.")
                if request.headers.get("HX-Request") == "true":
                    return render(
                        request,
                        "purchases/partials/_quick_supplier_success.html",
                        {"supplier": supplier},
                    )
                return redirect("purchases:supplier_detail", pk=supplier.pk)
        return render(request, self.template_name, {"form": form, "is_create": True})


class QuickSupplierCreateView(_PurchasesView, View):
    template_name = "purchases/partials/_quick_supplier_form.html"

    def get(self, request):
        return render(request, self.template_name, {"form": SupplierForm()})

    def post(self, request):
        form = SupplierForm(request.POST)
        if form.is_valid():
            try:
                supplier = create_supplier(
                    business=_business(request), user=request.user, **form.cleaned_data
                )
            except ValidationError as error:
                _service_errors(form, error)
            else:
                response = render(
                    request,
                    "purchases/partials/_quick_supplier_success.html",
                    {"supplier": supplier},
                )
                return add_hx_trigger(
                    response,
                    {
                        "purchases:supplier-selected": {
                            "id": supplier.pk,
                            "name": supplier.name,
                        },
                        "nx:close-modal": {"id": "quick-supplier"},
                        "nx:toast": {
                            "message": "Proveedor creado y seleccionado.",
                            "tone": "success",
                        },
                    },
                )
        response = render(request, self.template_name, {"form": form}, status=422)
        return response


class SupplierUpdateView(_PurchasesView, View):
    template_name = "purchases/supplier_form.html"

    def _supplier(self):
        return get_supplier_detail(
            business=_business(self.request), pk=self.kwargs["pk"]
        )

    def get(self, request, pk):
        supplier = self._supplier()
        return render(
            request,
            self.template_name,
            {
                "form": SupplierForm(
                    initial={
                        name: getattr(supplier, name)
                        for name in SupplierForm.base_fields
                    }
                ),
                "supplier": supplier,
            },
        )

    def post(self, request, pk):
        supplier = self._supplier()
        form = SupplierForm(request.POST)
        if form.is_valid():
            try:
                update_supplier(
                    business=_business(request),
                    supplier=supplier,
                    user=request.user,
                    **form.cleaned_data,
                )
            except ValidationError as error:
                _service_errors(form, error)
            else:
                messages.success(request, "Proveedor actualizado correctamente.")
                return redirect("purchases:supplier_detail", pk=supplier.pk)
        return render(request, self.template_name, {"form": form, "supplier": supplier})


class SupplierDetailView(_PurchasesView, View):
    def get(self, request, pk):
        business = _business(request)
        supplier = get_supplier_detail(business=business, pk=pk)
        tab = request.GET.get("tab", "summary")
        if tab not in {"summary", "purchases"}:
            tab = "summary"
        context = {
            "supplier": supplier,
            "tab": tab,
            "stores": get_accessible_purchase_stores(
                business=business, user=request.user
            ),
        }
        if tab == "purchases":
            form = SupplierPurchaseFilterForm(
                request.GET or None, business=business, user=request.user
            )
            data = form.cleaned_data if form.is_valid() else {}
            if request.GET and not form.is_valid():
                purchases = Purchase.objects.none()
            else:
                purchases = get_purchase_list(
                    business=business,
                    user=request.user,
                    supplier=supplier,
                    status=data.get("status", ""),
                    store=data.get("store"),
                    date_from=data.get("date_from"),
                    date_to=data.get("date_to"),
                )
            context.update(
                {
                    "purchase_filter_form": form,
                    "purchases_page": Paginator(purchases, 25).get_page(
                        request.GET.get("page")
                    ),
                    "page_query": _page_query(request),
                }
            )
        template = "purchases/supplier_detail.html"
        if _is_htmx(request):
            template = "purchases/partials/_supplier_workspace.html"
        return render(
            request,
            template,
            context,
        )


class SupplierStatusView(_PurchasesView, View):
    http_method_names = ["post"]
    active = False

    def post(self, request, pk):
        supplier = get_supplier_detail(business=_business(request), pk=pk)
        update_supplier(
            business=_business(request),
            supplier=supplier,
            user=request.user,
            is_active=self.active,
        )
        messages.success(
            request,
            "Proveedor reactivado."
            if self.active
            else "Proveedor desactivado; su histórico se conserva.",
        )
        return redirect("purchases:supplier_detail", pk=pk)


class SupplierActivateView(SupplierStatusView):
    active = True


class SupplierDeactivateView(SupplierStatusView):
    active = False


@method_decorator(vary_on_headers("HX-Request"), name="dispatch")
class PurchaseListView(_PurchasesView, ListView):
    template_name = "purchases/purchase_list.html"
    context_object_name = "purchases"
    paginate_by = 25

    def get_queryset(self):
        business = _business(self.request)
        _, active_store = resolve_active_store(self.request, user=self.request.user)
        filter_data = self.request.GET.copy() if self.request.GET else None
        if filter_data is not None and "store" not in filter_data:
            filter_data["store"] = str(active_store.pk) if active_store else ""
        self.filter_form = PurchaseFilterForm(
            filter_data,
            business=business,
            user=self.request.user,
            initial={"store": active_store},
        )
        data = self.filter_form.cleaned_data if self.filter_form.is_valid() else {}
        self.local_store = (
            data.get("store") if filter_data is not None else active_store
        )
        if self.request.GET and not self.filter_form.is_valid():
            return Purchase.objects.none()
        return get_purchase_list(
            business=business,
            user=self.request.user,
            query=data.get("q", ""),
            status=data.get("status", ""),
            store=self.local_store,
            supplier=data.get("supplier"),
            date_from=data.get("date_from"),
            date_to=data.get("date_to"),
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        business = _business(self.request)
        context.update(
            {
                "stores": get_accessible_purchase_stores(
                    business=business, user=self.request.user
                ),
                "suppliers": get_suppliers_for_business(
                    business=business, status="all"
                ),
                "statuses": PurchaseStatusChoices.choices,
                "filter_form": self.filter_form,
                "local_store": self.local_store,
                "all_stores": self.local_store is None,
                "kpis": get_purchase_list_kpis(
                    business=business, user=self.request.user, store=self.local_store
                ),
                "page_query": _page_query(
                    self.request,
                    effective_store=self.local_store,
                    include_store=True,
                ),
            }
        )
        return context

    def render_to_response(self, context, **kwargs):
        if self.request.headers.get("HX-Request") == "true":
            self.template_name = "purchases/partials/_purchase_results.html"
        return super().render_to_response(context, **kwargs)


class PurchaseCreateView(_PurchasesView, View):
    template_name = "purchases/purchase_form.html"

    def _form(self, data=None):
        initial = {}
        _, active_store = resolve_active_store(self.request, user=self.request.user)
        if active_store:
            initial["store"] = active_store
        if self.request.GET.get("supplier"):
            initial["supplier"] = self.request.GET["supplier"]
        return PurchaseCreateForm(
            data,
            business=_business(self.request),
            user=self.request.user,
            initial=initial,
        )

    def get(self, request):
        return render(
            request,
            self.template_name,
            {
                "form": self._form(),
                "quick_supplier_form": SupplierForm(),
                "is_create": True,
            },
        )

    def post(self, request):
        form = self._form(request.POST)
        if form.is_valid():
            try:
                purchase = create_purchase(
                    business=_business(request),
                    created_by=request.user,
                    **form.cleaned_data,
                )
            except ValidationError as error:
                _service_errors(form, error)
            else:
                messages.success(request, "Compra creada correctamente.")
                return redirect("purchases:purchase_detail", pk=purchase.pk)
        return render(
            request,
            self.template_name,
            {
                "form": form,
                "quick_supplier_form": SupplierForm(),
                "is_create": True,
            },
        )


class PurchaseDetailView(_PurchasesView, View):
    def get(self, request, pk):
        business = _business(request)
        purchase = get_purchase_detail(business=business, user=request.user, pk=pk)
        tab = request.GET.get("tab", "summary")
        if tab not in {"summary", "products", "receipts"}:
            tab = "summary"
        context = {
            "purchase": purchase,
            "tab": tab,
            "progress": get_purchase_progress(purchase),
            "receipt_registered": request.GET.get("receipt_registered") == "1",
            "received_units": request.GET.get("units", ""),
        }
        if tab == "products":
            context["lines"] = get_purchase_lines(business=business, purchase=purchase)
        elif tab == "receipts":
            context["receipts_page"] = Paginator(
                get_purchase_receipts(business=business, purchase=purchase), 25
            ).get_page(request.GET.get("page"))
            context["page_query"] = _page_query(request)
        template = "purchases/purchase_detail.html"
        if _is_htmx(request):
            template = "purchases/partials/_purchase_workspace.html"
        return render(
            request,
            template,
            context,
        )


class PurchaseUpdateView(_PurchasesView, View):
    template_name = "purchases/purchase_form.html"

    def _purchase(self):
        purchase = get_purchase_detail(
            business=_business(self.request),
            user=self.request.user,
            pk=self.kwargs["pk"],
        )
        if not purchase.is_draft:
            raise PermissionDenied("Solo se puede editar una compra en borrador.")
        return purchase

    def _form(self, purchase, data=None):
        return PurchaseUpdateForm(
            data,
            business=_business(self.request),
            user=self.request.user,
            purchase=purchase,
            initial={
                "store": purchase.store,
                "supplier": purchase.supplier,
                "reference": purchase.reference,
                "notes": purchase.notes,
            },
        )

    def get(self, request, pk):
        purchase = self._purchase()
        return render(
            request,
            self.template_name,
            {"form": self._form(purchase), "purchase": purchase},
        )

    def post(self, request, pk):
        purchase = self._purchase()
        form = self._form(purchase, request.POST)
        if form.is_valid():
            data = {
                "reference": form.cleaned_data["reference"],
                "notes": form.cleaned_data["notes"],
            }
            if form.cleaned_data["store"].pk != purchase.store_id:
                data["store"] = form.cleaned_data["store"]
            if form.cleaned_data["supplier"].pk != purchase.supplier_id:
                data["supplier"] = form.cleaned_data["supplier"]
            try:
                update_purchase_header(
                    business=_business(request),
                    purchase=purchase,
                    user=request.user,
                    **data,
                )
            except ValidationError as error:
                _service_errors(form, error)
            else:
                messages.success(request, "Compra actualizada correctamente.")
                return redirect("purchases:purchase_detail", pk=purchase.pk)
        return render(request, self.template_name, {"form": form, "purchase": purchase})


class _PurchaseLineView(_PurchasesView, View):
    def purchase(self):
        return get_purchase_detail(
            business=_business(self.request),
            user=self.request.user,
            pk=self.kwargs["purchase_pk"],
        )

    def line_response(self, purchase):
        if not _is_htmx(self.request):
            return redirect("purchases:purchase_detail", pk=purchase.pk)
        refreshed = get_purchase_detail(
            business=_business(self.request), user=self.request.user, pk=purchase.pk
        )
        response = render(
            self.request,
            "purchases/partials/_purchase_workspace.html",
            {
                "purchase": refreshed,
                "tab": "products",
                "lines": get_purchase_lines(
                    business=_business(self.request), purchase=refreshed
                ),
            },
        )
        return add_hx_trigger(
            response,
            {
                "nx:close-modal": {},
                "nx:toast": {"message": "Compra actualizada.", "tone": "success"},
            },
        )


class PurchaseLineCreateView(_PurchaseLineView):
    def get(self, request, purchase_pk):
        purchase = self.purchase()
        if not purchase.is_draft:
            raise PermissionDenied("Solo se pueden añadir productos a un borrador.")
        return render(
            request,
            "purchases/partials/_purchase_line_form.html"
            if _is_htmx(request)
            else "purchases/purchase_line_form.html",
            {
                "form": PurchaseLineCreateForm(business=_business(request)),
                "purchase": purchase,
            },
        )

    def post(self, request, purchase_pk):
        purchase = self.purchase()
        if not purchase.is_draft:
            raise PermissionDenied("Solo se pueden añadir productos a un borrador.")
        form = PurchaseLineCreateForm(request.POST, business=_business(request))
        if form.is_valid():
            try:
                add_purchase_line(
                    business=_business(request),
                    purchase=purchase,
                    user=request.user,
                    **form.cleaned_data,
                )
            except ValidationError as error:
                _service_errors(form, error)
            else:
                return self.line_response(purchase)
        return render(
            request,
            "purchases/partials/_purchase_line_form.html"
            if _is_htmx(request)
            else "purchases/purchase_line_form.html",
            {"form": form, "purchase": purchase},
        )


class PurchaseLineUpdateView(_PurchaseLineView):
    def _line(self, purchase):
        return get_object_or_404(
            get_purchase_lines(business=_business(self.request), purchase=purchase),
            pk=self.kwargs["line_pk"],
        )

    def get(self, request, purchase_pk, line_pk):
        purchase = self.purchase()
        if not purchase.is_draft:
            raise PermissionDenied("Solo se puede editar una compra en borrador.")
        line = self._line(purchase)
        form = PurchaseLineUpdateForm(
            initial={
                "quantity": line.quantity_ordered,
                "unit_cost": line.unit_cost,
                "tax_rate": line.tax_rate,
            }
        )
        return render(
            request,
            "purchases/partials/_purchase_line_form.html"
            if _is_htmx(request)
            else "purchases/purchase_line_form.html",
            {"form": form, "purchase": purchase, "line": line},
        )

    def post(self, request, purchase_pk, line_pk):
        purchase = self.purchase()
        if not purchase.is_draft:
            raise PermissionDenied("Solo se puede editar una compra en borrador.")
        line = self._line(purchase)
        form = PurchaseLineUpdateForm(request.POST)
        if form.is_valid():
            try:
                update_purchase_line(
                    business=_business(request),
                    purchase=purchase,
                    line=line,
                    user=request.user,
                    **form.cleaned_data,
                )
            except ValidationError as error:
                _service_errors(form, error)
            else:
                return self.line_response(purchase)
        return render(
            request,
            "purchases/partials/_purchase_line_form.html"
            if _is_htmx(request)
            else "purchases/purchase_line_form.html",
            {"form": form, "purchase": purchase, "line": line},
        )


class PurchaseLineDeleteView(_PurchaseLineView):
    http_method_names = ["post"]

    def post(self, request, purchase_pk, line_pk):
        purchase = self.purchase()
        if not purchase.is_draft:
            raise PermissionDenied("Solo se puede editar una compra en borrador.")
        line = get_object_or_404(
            get_purchase_lines(business=_business(request), purchase=purchase),
            pk=line_pk,
        )
        try:
            delete_purchase_line(
                business=_business(request),
                purchase=purchase,
                line=line,
                user=request.user,
            )
        except ValidationError as error:
            messages.error(request, str(error))
        return self.line_response(purchase)


class ProductSearchView(_PurchasesView, View):
    def get(self, request, purchase_pk):
        purchase = get_purchase_detail(
            business=_business(request), user=request.user, pk=purchase_pk
        )
        if not purchase.is_draft:
            raise PermissionDenied("La compra ya no admite productos.")
        query = request.GET.get("product_query", "").strip()
        products = Product.objects.filter(
            business=_business(request), is_active=True
        ).order_by("name", "pk")
        if query:
            products = products.filter(
                Q(name__icontains=query)
                | Q(sku__icontains=query)
                | Q(barcode__icontains=query)
            )
        else:
            products = products.none()
        return render(
            request,
            "purchases/partials/_product_results.html",
            {"products": products[:25], "query": query},
        )


class _PurchaseActionView(_PurchasesView, View):
    http_method_names = ["post"]

    def purchase(self):
        return get_purchase_detail(
            business=_business(self.request),
            user=self.request.user,
            pk=self.kwargs["pk"],
        )


class PurchaseOrderView(_PurchasesView, View):
    http_method_names = ["get", "post"]

    def purchase(self):
        return get_purchase_detail(
            business=_business(self.request),
            user=self.request.user,
            pk=self.kwargs["pk"],
        )

    def get(self, request, pk):
        purchase = self.purchase()
        if not purchase.is_draft:
            raise PermissionDenied("Solo se puede revisar un borrador.")
        return render(
            request,
            "purchases/purchase_order_review.html",
            {"purchase": purchase, "progress": get_purchase_progress(purchase)},
        )

    def post(self, request, pk):
        purchase = self.purchase()
        try:
            order_purchase(
                business=_business(request), purchase=purchase, ordered_by=request.user
            )
        except ValidationError as error:
            messages.error(request, str(error))
        url = reverse("purchases:purchase_detail", kwargs={"pk": pk})
        if _is_htmx(request):
            response = HttpResponse(status=204)
            response["HX-Redirect"] = url
            return response
        return redirect(url)


class PurchaseCancelView(_PurchaseActionView):
    def post(self, request, pk):
        purchase = self.purchase()
        try:
            cancel_purchase(
                business=_business(request),
                purchase=purchase,
                cancelled_by=request.user,
            )
        except ValidationError as error:
            messages.error(request, str(error))
        return redirect("purchases:purchase_detail", pk=pk)


class PurchaseReceiptCreateView(_PurchasesView, View):
    template_name = "purchases/purchase_receipt_form.html"

    def purchase(self):
        return get_purchase_detail(
            business=_business(self.request),
            user=self.request.user,
            pk=self.kwargs["pk"],
        )

    def get(self, request, pk):
        purchase = self.purchase()
        if purchase.status not in {
            PurchaseStatusChoices.ORDERED,
            PurchaseStatusChoices.PARTIALLY_RECEIVED,
        }:
            raise PermissionDenied("La compra no admite nuevas recepciones.")
        form = PurchaseReceiptForm(
            purchase_lines=get_purchase_lines(
                business=_business(request), purchase=purchase
            )
        )
        return render(request, self.template_name, {"form": form, "purchase": purchase})

    def post(self, request, pk):
        purchase = self.purchase()
        form = PurchaseReceiptForm(
            request.POST,
            purchase_lines=get_purchase_lines(
                business=_business(request), purchase=purchase
            ),
        )
        if request.POST.get("step") == "edit":
            return render(
                request,
                "purchases/partials/_receipt_form_content.html"
                if _is_htmx(request)
                else self.template_name,
                {"form": form, "purchase": purchase},
            )
        if form.is_valid() and request.POST.get("confirm") != "1":
            receipt_lines = form.receipt_lines()
            return render(
                request,
                "purchases/purchase_receipt_review.html",
                {
                    "form": form,
                    "purchase": purchase,
                    "receipt_lines": receipt_lines,
                    "total_units": sum(
                        item["quantity_received"] for item in receipt_lines
                    ),
                },
            )
        if form.is_valid():
            try:
                register_purchase_receipt(
                    business=_business(request),
                    purchase=purchase,
                    received_by=request.user,
                    lines=form.receipt_lines(),
                    idempotency_key=form.cleaned_data["idempotency_key"],
                    notes=form.cleaned_data["notes"],
                )
            except ValidationError as error:
                _service_errors(form, error)
            else:
                units = sum(item["quantity_received"] for item in form.receipt_lines())
                messages.success(request, "✓ Recepción registrada correctamente.")
                url = reverse("purchases:purchase_detail", kwargs={"pk": pk})
                url = f"{url}?receipt_registered=1&units={units}"
                if _is_htmx(request):
                    response = HttpResponse(status=204)
                    response["HX-Redirect"] = url
                    return response
                return HttpResponseRedirect(url)
        return render(
            request,
            "purchases/partials/_receipt_form_content.html"
            if _is_htmx(request)
            else self.template_name,
            {"form": form, "purchase": purchase},
            status=422 if _is_htmx(request) else 200,
        )
