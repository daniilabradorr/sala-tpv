from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.shortcuts import get_object_or_404, redirect, render
from django.views import View
from django.views.generic import ListView

from apps.purchases.forms import (
    PurchaseCreateForm,
    PurchaseLineCreateForm,
    PurchaseLineUpdateForm,
    PurchaseReceiptForm,
    PurchaseUpdateForm,
    SupplierForm,
)
from apps.purchases.models import PurchaseStatusChoices
from apps.purchases.selectors import (
    get_accessible_purchase_stores,
    get_purchase_detail,
    get_purchase_lines,
    get_purchase_receipts,
    get_purchases_for_user,
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


class _PurchasesView(ManagerOrOwnerRequiredMixin, BusinessRequiredMixin):
    pass


class SupplierListView(_PurchasesView, ListView):
    template_name = "purchases/supplier_list.html"
    context_object_name = "suppliers"
    paginate_by = 25

    def get_queryset(self):
        return get_suppliers_for_business(
            business=_business(self.request),
            query=self.request.GET.get("q", ""),
            status=self.request.GET.get("status", "active"),
        )


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
                create_supplier(
                    business=_business(request), user=request.user, **form.cleaned_data
                )
            except ValidationError as error:
                _service_errors(form, error)
            else:
                messages.success(request, "Proveedor creado correctamente.")
                return redirect("purchases:supplier_list")
        return render(request, self.template_name, {"form": form, "is_create": True})


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
                return redirect("purchases:supplier_list")
        return render(request, self.template_name, {"form": form, "supplier": supplier})


class PurchaseListView(_PurchasesView, ListView):
    template_name = "purchases/purchase_list.html"
    context_object_name = "purchases"
    paginate_by = 25

    def get_queryset(self):
        return get_purchases_for_user(
            business=_business(self.request),
            user=self.request.user,
            query=self.request.GET.get("q", ""),
            status=self.request.GET.get("status", ""),
            store=self.request.GET.get("store", ""),
            supplier=self.request.GET.get("supplier", ""),
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
            }
        )
        return context


class PurchaseCreateView(_PurchasesView, View):
    template_name = "purchases/purchase_form.html"

    def _form(self, data=None):
        return PurchaseCreateForm(
            data, business=_business(self.request), user=self.request.user
        )

    def get(self, request):
        return render(
            request, self.template_name, {"form": self._form(), "is_create": True}
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
        return render(request, self.template_name, {"form": form, "is_create": True})


class PurchaseDetailView(_PurchasesView, View):
    def get(self, request, pk):
        purchase = get_purchase_detail(
            business=_business(request), user=request.user, pk=pk
        )
        return render(
            request,
            "purchases/purchase_detail.html",
            {
                "purchase": purchase,
                "lines": get_purchase_lines(
                    business=_business(request), purchase=purchase
                ),
                "receipts": get_purchase_receipts(
                    business=_business(request), purchase=purchase
                ),
            },
        )


class PurchaseUpdateView(_PurchasesView, View):
    template_name = "purchases/purchase_form.html"

    def _purchase(self):
        return get_purchase_detail(
            business=_business(self.request),
            user=self.request.user,
            pk=self.kwargs["pk"],
        )

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


class PurchaseLineCreateView(_PurchaseLineView):
    def get(self, request, purchase_pk):
        return render(
            request,
            "purchases/purchase_line_form.html",
            {
                "form": PurchaseLineCreateForm(business=_business(request)),
                "purchase": self.purchase(),
            },
        )

    def post(self, request, purchase_pk):
        purchase = self.purchase()
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
                return redirect("purchases:purchase_detail", pk=purchase.pk)
        return render(
            request,
            "purchases/purchase_line_form.html",
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
            "purchases/purchase_line_form.html",
            {"form": form, "purchase": purchase, "line": line},
        )

    def post(self, request, purchase_pk, line_pk):
        purchase = self.purchase()
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
                return redirect("purchases:purchase_detail", pk=purchase.pk)
        return render(
            request,
            "purchases/purchase_line_form.html",
            {"form": form, "purchase": purchase, "line": line},
        )


class PurchaseLineDeleteView(_PurchaseLineView):
    http_method_names = ["post"]

    def post(self, request, purchase_pk, line_pk):
        purchase = self.purchase()
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
        return redirect("purchases:purchase_detail", pk=purchase.pk)


class _PurchaseActionView(_PurchasesView, View):
    http_method_names = ["post"]

    def purchase(self):
        return get_purchase_detail(
            business=_business(self.request),
            user=self.request.user,
            pk=self.kwargs["pk"],
        )


class PurchaseOrderView(_PurchaseActionView):
    def post(self, request, pk):
        purchase = self.purchase()
        try:
            order_purchase(
                business=_business(request), purchase=purchase, ordered_by=request.user
            )
        except ValidationError as error:
            messages.error(request, str(error))
        return redirect("purchases:purchase_detail", pk=pk)


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
                messages.success(request, "Recepción registrada correctamente.")
                return redirect("purchases:purchase_detail", pk=pk)
        return render(request, self.template_name, {"form": form, "purchase": purchase})
