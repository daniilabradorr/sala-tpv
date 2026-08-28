"""Thin HTTP coordination layer for Billing."""

import uuid

from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import Http404
from django.shortcuts import redirect, render
from django.views import View

from apps.billing.forms import (
    BillingDocumentFilterForm,
    IssueSaleDocumentForm,
    SaleReturnRectificationForm,
    SubstituteSimplifiedDocumentForm,
)
from apps.billing.selectors import billing_document_detail, billing_document_list
from apps.billing.services import (
    issue_sale_document,
    issue_sale_return_rectification,
    substitute_simplified_document,
)
from apps.sales.selectors import get_sale_detail, get_sale_return_detail
from apps.users.mixins import (
    BusinessRequiredMixin,
    CanSellInStoreMixin,
    StoreAccessRequiredMixin,
)


def _add_service_errors(form, error):
    if hasattr(error, "message_dict"):
        for field, errors in error.message_dict.items():
            target = field if field in form.fields else None
            for message in errors:
                form.add_error(target, message)
    else:
        for message in getattr(error, "messages", [str(error)]):
            form.add_error(None, message)


class BillingStoreContextMixin:
    @property
    def business(self):
        business = getattr(self.request.user, "business", None)
        if business is None:
            raise PermissionDenied("La interfaz de facturación requiere un negocio.")
        if self.store.business_id != business.id:
            raise Http404
        return business

    def get_sale(self):
        sale = get_sale_detail(business=self.business, pk=self.kwargs["sale_pk"])
        if sale.store_id != self.store.id:
            raise Http404
        return sale

    def get_sale_return(self):
        sale_return = get_sale_return_detail(
            business=self.business, pk=self.kwargs["return_pk"]
        )
        if sale_return.store_id != self.store.id:
            raise Http404
        return sale_return


class BillingDocumentListView(
    BusinessRequiredMixin, StoreAccessRequiredMixin, BillingStoreContextMixin, View
):
    http_method_names = ["get"]

    def get(self, request, *args, **kwargs):
        form = BillingDocumentFilterForm(request.GET or None, business=self.business)
        filters = {}
        if form.is_valid():
            filters = {
                key: value
                for key, value in form.cleaned_data.items()
                if value not in (None, "")
            }
        documents = billing_document_list(
            business=self.business, store=self.store, **filters
        )
        return render(
            request,
            "billing/document_list.html",
            {"store": self.store, "form": form, "documents": documents},
        )


class BillingDocumentDetailView(
    BusinessRequiredMixin, StoreAccessRequiredMixin, BillingStoreContextMixin, View
):
    http_method_names = ["get"]

    def get(self, request, *args, **kwargs):
        document = billing_document_detail(
            business=self.business, document_id=kwargs["document_pk"]
        )
        if document.store_id != self.store.id:
            raise Http404
        return render(
            request,
            "billing/document_detail.html",
            {"store": self.store, "document": document},
        )


class BillingCommandView(
    BusinessRequiredMixin, CanSellInStoreMixin, BillingStoreContextMixin, View
):
    form_class = None
    template_name = None
    success_message = "Documento fiscal emitido correctamente."

    def get_subject(self):
        raise NotImplementedError

    def form_kwargs(self, subject):
        raise NotImplementedError

    def execute(self, form, subject):
        raise NotImplementedError

    def get_initial(self, subject):
        return {"idempotency_key": uuid.uuid4()}

    def get(self, request, *args, **kwargs):
        subject = self.get_subject()
        form = self.form_class(
            **self.form_kwargs(subject), initial=self.get_initial(subject)
        )
        return self.render_form(form, subject)

    def post(self, request, *args, **kwargs):
        subject = self.get_subject()
        form = self.form_class(request.POST, **self.form_kwargs(subject))
        if form.is_valid():
            try:
                document = self.execute(form, subject)
            except ValidationError as error:
                _add_service_errors(form, error)
            else:
                messages.success(request, self.success_message)
                return redirect(
                    "billing:document_detail",
                    store_id=self.store.pk,
                    document_pk=document.pk,
                )
        return self.render_form(form, subject)

    def render_form(self, form, subject):
        return render(
            self.request,
            self.template_name,
            {"store": self.store, "form": form, "subject": subject},
        )


class IssueSaleDocumentView(BillingCommandView):
    form_class = IssueSaleDocumentForm
    template_name = "billing/issue_sale_document.html"

    def get_subject(self):
        return self.get_sale()

    def form_kwargs(self, sale):
        return {"business": self.business, "sale": sale}

    def execute(self, form, sale):
        return issue_sale_document(
            business=self.business,
            sale_id=sale.pk,
            series_id=form.cleaned_data["series"].pk,
            issued_by=self.request.user,
            idempotency_key=form.cleaned_data["idempotency_key"],
        )


class SubstituteSimplifiedDocumentView(BillingCommandView):
    form_class = SubstituteSimplifiedDocumentForm
    template_name = "billing/substitute_simplified_document.html"

    def get_subject(self):
        return self.get_sale()

    def form_kwargs(self, sale):
        return {"business": self.business, "sale": sale}

    def execute(self, form, sale):
        return substitute_simplified_document(
            business=self.business,
            sale_id=sale.pk,
            customer=form.cleaned_data["customer"],
            series_id=form.cleaned_data["series"].pk,
            issued_by=self.request.user,
            idempotency_key=form.cleaned_data["idempotency_key"],
        )


class IssueSaleReturnRectificationView(BillingCommandView):
    form_class = SaleReturnRectificationForm
    template_name = "billing/issue_sale_return_rectification.html"

    def get_subject(self):
        return self.get_sale_return()

    def form_kwargs(self, sale_return):
        return {"business": self.business, "sale_return": sale_return}

    def execute(self, form, sale_return):
        companion = form.cleaned_data.get("companion_f3_series")
        return issue_sale_return_rectification(
            business=self.business,
            sale_return_id=sale_return.pk,
            series_id=form.cleaned_data["series"].pk,
            companion_f3_series_id=companion.pk if companion else None,
            issued_by=self.request.user,
            idempotency_key=form.cleaned_data["idempotency_key"],
        )
