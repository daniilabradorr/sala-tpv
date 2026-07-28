from django.contrib import messages
from django.core.exceptions import ValidationError
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.views import View

from apps.users.mixins import CanSellInStoreMixin, StoreAccessRequiredMixin

from . import services
from .forms import (
    SaleCancelForm,
    SaleFilterForm,
    SaleHeaderUpdateForm,
    SaleLineCreateForm,
    SaleLineUpdateForm,
    SaleOpenForm,
    SaleReturnCancelForm,
    SaleReturnCompleteForm,
    SaleReturnCreateForm,
    SaleReturnFilterForm,
    SaleReturnLineCreateForm,
    SaleReturnLineUpdateForm,
)
from .models import Sale, SaleLine, SaleReturn, SaleReturnLine
from .selectors import sale_get, sale_list, sale_return_get, sale_return_list


def _ensure_sale_editable(sale):
    if sale.status != Sale.Status.OPEN:
        raise Http404("La venta no es editable.")


def _ensure_return_editable(sale_return):
    if sale_return.status != SaleReturn.Status.OPEN:
        raise Http404("La devolución no es editable.")


def _service_error(request, error):
    messages.error(request, "; ".join(error.messages))


class StoreView:
    template_name = "sales/page.html"

    @property
    def business(self):
        return self.store.business

    def page(self, request, **context):
        return render(request, self.template_name, {"store": self.store, **context})


class SaleListView(StoreAccessRequiredMixin, StoreView, View):
    def get(self, request, *args, **kwargs):
        form = SaleFilterForm(request.GET, business=self.business, store=self.store)
        return self.page(
            request,
            form=form,
            sales=sale_list(
                business=self.business,
                store=self.store,
                filters=form.cleaned_data if form.is_valid() else {},
            ),
        )


class SaleDetailView(StoreAccessRequiredMixin, StoreView, View):
    def get(self, request, sale_pk, *args, **kwargs):
        return self.page(
            request,
            sale=sale_get(business=self.business, store=self.store, sale_pk=sale_pk),
        )


class SaleOpenView(CanSellInStoreMixin, StoreView, View):
    def get(self, request, *args, **kwargs):
        return self.page(
            request, form=SaleOpenForm(business=self.business, store=self.store)
        )

    def post(self, request, *args, **kwargs):
        form = SaleOpenForm(request.POST, business=self.business, store=self.store)
        if form.is_valid():
            sale = services.open_sale(
                business=self.business,
                store=self.store,
                user=request.user,
                **form.cleaned_data,
            )
            return redirect(
                "sales:sale_detail", store_id=self.store.pk, sale_pk=sale.pk
            )
        return self.page(request, form=form)


class SaleObjectView(CanSellInStoreMixin, StoreView, View):
    def get_sale(self, sale_pk):
        return get_object_or_404(
            Sale, pk=sale_pk, business=self.business, store=self.store
        )


class SaleHeaderUpdateView(SaleObjectView):
    def get(self, request, sale_pk, *args, **kwargs):
        sale = self.get_sale(sale_pk)
        _ensure_sale_editable(sale)
        return self.page(
            request,
            sale=sale,
            form=SaleHeaderUpdateForm(
                business=self.business,
                store=self.store,
                initial={
                    "customer": sale.customer,
                    "cash_register": sale.cash_register,
                    "cash_session": sale.cash_session,
                    "requires_invoice": sale.requires_invoice,
                    "notes": sale.notes,
                },
            ),
        )

    def post(self, request, sale_pk, *args, **kwargs):
        sale = self.get_sale(sale_pk)
        _ensure_sale_editable(sale)
        form = SaleHeaderUpdateForm(
            request.POST, business=self.business, store=self.store
        )
        if form.is_valid():
            services.update_sale_header(sale=sale, **form.cleaned_data)
            return redirect(
                "sales:sale_detail", store_id=self.store.pk, sale_pk=sale.pk
            )
        return self.page(request, sale=sale, form=form)


class SaleLineAddView(SaleObjectView):
    def get(self, request, sale_pk, *args, **kwargs):
        sale = self.get_sale(sale_pk)
        _ensure_sale_editable(sale)
        return self.page(
            request,
            sale=sale,
            form=SaleLineCreateForm(business=self.business, store=self.store),
        )

    def post(self, request, sale_pk, *args, **kwargs):
        sale = self.get_sale(sale_pk)
        _ensure_sale_editable(sale)
        form = SaleLineCreateForm(
            request.POST, business=self.business, store=self.store
        )
        if form.is_valid():
            services.add_sale_line(sale=sale, **form.cleaned_data)
            return redirect(
                "sales:sale_detail", store_id=self.store.pk, sale_pk=sale.pk
            )
        return self.page(request, sale=sale, form=form)


class SaleLineUpdateView(SaleObjectView):
    def _objects(self, sale_pk, line_pk):
        sale = self.get_sale(sale_pk)
        _ensure_sale_editable(sale)
        return sale, get_object_or_404(SaleLine, pk=line_pk, sale=sale)

    def get(self, request, sale_pk, line_pk, *args, **kwargs):
        sale, line = self._objects(sale_pk, line_pk)
        return self.page(
            request, sale=sale, line=line, form=SaleLineUpdateForm(instance=line)
        )

    def post(self, request, sale_pk, line_pk, *args, **kwargs):
        sale, line = self._objects(sale_pk, line_pk)
        form = SaleLineUpdateForm(request.POST, instance=line)
        if form.is_valid():
            services.update_sale_line(line=line, **form.cleaned_data)
            return redirect(
                "sales:sale_detail", store_id=self.store.pk, sale_pk=sale.pk
            )
        return self.page(request, sale=sale, line=line, form=form)


class SaleLineDeleteView(SaleObjectView):
    http_method_names = ["post"]

    def post(self, request, sale_pk, line_pk, *args, **kwargs):
        sale = self.get_sale(sale_pk)
        _ensure_sale_editable(sale)
        services.delete_sale_line(
            line=get_object_or_404(SaleLine, pk=line_pk, sale=sale)
        )
        return redirect("sales:sale_detail", store_id=self.store.pk, sale_pk=sale.pk)


class SaleCompleteView(SaleObjectView):
    http_method_names = ["post"]

    def post(self, request, sale_pk, *args, **kwargs):
        sale = self.get_sale(sale_pk)
        _ensure_sale_editable(sale)
        try:
            services.complete_sale(sale=sale, user=request.user)
        except ValidationError as error:
            _service_error(request, error)
        return redirect("sales:sale_detail", store_id=self.store.pk, sale_pk=sale.pk)


class SaleCancelView(SaleObjectView):
    def get(self, request, sale_pk, *args, **kwargs):
        sale = self.get_sale(sale_pk)
        _ensure_sale_editable(sale)
        return self.page(request, sale=sale, form=SaleCancelForm())

    def post(self, request, sale_pk, *args, **kwargs):
        sale = self.get_sale(sale_pk)
        _ensure_sale_editable(sale)
        form = SaleCancelForm(request.POST)
        if form.is_valid():
            services.cancel_sale(
                sale=sale, user=request.user, reason=form.cleaned_data["reason"]
            )
            return redirect(
                "sales:sale_detail", store_id=self.store.pk, sale_pk=sale.pk
            )
        return self.page(request, sale=sale, form=form)


class SaleReturnListView(StoreAccessRequiredMixin, StoreView, View):
    def get(self, request, *args, **kwargs):
        form = SaleReturnFilterForm(
            request.GET, business=self.business, store=self.store
        )
        return self.page(
            request,
            form=form,
            returns=sale_return_list(
                business=self.business,
                store=self.store,
                filters=form.cleaned_data if form.is_valid() else {},
            ),
        )


class SaleReturnDetailView(StoreAccessRequiredMixin, StoreView, View):
    def get(self, request, return_pk, *args, **kwargs):
        return self.page(
            request,
            sale_return=sale_return_get(
                business=self.business, store=self.store, return_pk=return_pk
            ),
        )


class SaleReturnCreateView(CanSellInStoreMixin, StoreView, View):
    def get_sale(self, sale_pk):
        return get_object_or_404(
            Sale,
            pk=sale_pk,
            business=self.business,
            store=self.store,
            status=Sale.Status.COMPLETED,
        )

    def get(self, request, sale_pk, *args, **kwargs):
        return self.page(
            request, sale=self.get_sale(sale_pk), form=SaleReturnCreateForm()
        )

    def post(self, request, sale_pk, *args, **kwargs):
        sale = self.get_sale(sale_pk)
        form = SaleReturnCreateForm(request.POST)
        if form.is_valid():
            obj = services.create_sale_return(
                sale=sale, user=request.user, **form.cleaned_data
            )
            return redirect(
                "sales:return_detail", store_id=self.store.pk, return_pk=obj.pk
            )
        return self.page(request, sale=sale, form=form)


class ReturnObjectView(CanSellInStoreMixin, StoreView, View):
    def get_return(self, return_pk):
        return get_object_or_404(
            SaleReturn, pk=return_pk, business=self.business, store=self.store
        )


class SaleReturnLineAddView(ReturnObjectView):
    def get(self, request, return_pk, *args, **kwargs):
        obj = self.get_return(return_pk)
        _ensure_return_editable(obj)
        return self.page(
            request, sale_return=obj, form=SaleReturnLineCreateForm(sale=obj.sale)
        )

    def post(self, request, return_pk, *args, **kwargs):
        obj = self.get_return(return_pk)
        _ensure_return_editable(obj)
        form = SaleReturnLineCreateForm(request.POST, sale=obj.sale)
        if form.is_valid():
            services.add_sale_return_line(sale_return=obj, **form.cleaned_data)
            return redirect(
                "sales:return_detail", store_id=self.store.pk, return_pk=obj.pk
            )
        return self.page(request, sale_return=obj, form=form)


class SaleReturnLineUpdateView(ReturnObjectView):
    def _objects(self, return_pk, line_pk):
        obj = self.get_return(return_pk)
        _ensure_return_editable(obj)
        return obj, get_object_or_404(SaleReturnLine, pk=line_pk, sale_return=obj)

    def get(self, request, return_pk, line_pk, *args, **kwargs):
        obj, line = self._objects(return_pk, line_pk)
        return self.page(
            request,
            sale_return=obj,
            line=line,
            form=SaleReturnLineUpdateForm(instance=line),
        )

    def post(self, request, return_pk, line_pk, *args, **kwargs):
        obj, line = self._objects(return_pk, line_pk)
        form = SaleReturnLineUpdateForm(request.POST, instance=line)
        if form.is_valid():
            services.update_sale_return_line(line=line, **form.cleaned_data)
            return redirect(
                "sales:return_detail", store_id=self.store.pk, return_pk=obj.pk
            )
        return self.page(request, sale_return=obj, line=line, form=form)


class SaleReturnLineDeleteView(ReturnObjectView):
    http_method_names = ["post"]

    def post(self, request, return_pk, line_pk, *args, **kwargs):
        obj = self.get_return(return_pk)
        _ensure_return_editable(obj)
        services.delete_sale_return_line(
            line=get_object_or_404(SaleReturnLine, pk=line_pk, sale_return=obj)
        )
        return redirect("sales:return_detail", store_id=self.store.pk, return_pk=obj.pk)


class SaleReturnCompleteView(ReturnObjectView):
    http_method_names = ["post"]

    def post(self, request, return_pk, *args, **kwargs):
        obj = self.get_return(return_pk)
        _ensure_return_editable(obj)
        form = SaleReturnCompleteForm(request.POST)
        if form.is_valid():
            try:
                services.complete_sale_return(sale_return=obj, user=request.user)
            except ValidationError as error:
                _service_error(request, error)
        return redirect("sales:return_detail", store_id=self.store.pk, return_pk=obj.pk)


class SaleReturnCancelView(ReturnObjectView):
    def get(self, request, return_pk, *args, **kwargs):
        obj = self.get_return(return_pk)
        _ensure_return_editable(obj)
        return self.page(request, sale_return=obj, form=SaleReturnCancelForm())

    def post(self, request, return_pk, *args, **kwargs):
        obj = self.get_return(return_pk)
        _ensure_return_editable(obj)
        form = SaleReturnCancelForm(request.POST)
        if form.is_valid():
            services.cancel_sale_return(
                sale_return=obj, user=request.user, reason=form.cleaned_data["reason"]
            )
            return redirect(
                "sales:return_detail", store_id=self.store.pk, return_pk=obj.pk
            )
        return self.page(request, sale_return=obj, form=form)
