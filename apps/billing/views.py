"""Thin HTTP coordination layer for Billing."""

import uuid

from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.http import Http404
from django.shortcuts import redirect, render
from django.views import View

from apps.billing.forms import (
    BillingDocumentFilterForm,
    BillingSeriesFilterForm,
    BillingSeriesForm,
    IssueSaleDocumentForm,
    SaleReturnRectificationForm,
    SubstituteSimplifiedDocumentForm,
)
from apps.billing.selectors import (
    billing_document_detail,
    billing_document_list,
    billing_series_detail,
    billing_series_list,
)
from apps.billing.services import (
    issue_sale_document,
    issue_sale_return_rectification,
    substitute_simplified_document,
    activate_billing_series,
    create_billing_series,
    deactivate_billing_series,
    update_billing_series,
)
from apps.sales.selectors import get_sale_detail, get_sale_return_detail
from apps.users.mixins import (
    BusinessRequiredMixin,
    CanSellInStoreMixin,
    StoreAccessRequiredMixin,
    ManagerOrOwnerRequiredMixin,
)
from apps.users.helpers import can_sell_in_store, is_owner_or_manager


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
        if self.request.user.is_superuser:
            business = self.store.business
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
        page = Paginator(documents, 25).get_page(request.GET.get("page"))
        query = request.GET.copy()
        query.pop("page", None)
        template = (
            "billing/partials/document_results.html"
            if request.headers.get("HX-Request") == "true"
            else "billing/document_list.html"
        )
        return render(
            request,
            template,
            {
                "store": self.store,
                "form": form,
                "documents": page,
                "can_manage_series": request.user.is_superuser
                or is_owner_or_manager(request.user),
                "filter_query": query.urlencode(),
            },
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
        tab = request.GET.get("tab", "summary")
        if tab not in {"summary", "lines", "fiscal", "relations"}:
            tab = "summary"
        can_substitute = (
            document.document_type == "F2"
            and document.status == "issued"
            and document.sale_id
            and can_sell_in_store(request.user, self.store)
            and not any(
                relation.relation_type == "substitutes"
                for relation in document.incoming_relations.all()
            )
        )
        template = (
            "billing/partials/document_workspace.html"
            if request.headers.get("HX-Request") == "true"
            else "billing/document_detail.html"
        )
        return render(
            request,
            template,
            {
                "store": self.store,
                "document": document,
                "tab": tab,
                "can_substitute": can_substitute,
                "can_manage_series": request.user.is_superuser
                or is_owner_or_manager(request.user),
            },
        )


class BillingSeriesBaseView(
    ManagerOrOwnerRequiredMixin,
    BusinessRequiredMixin,
    StoreAccessRequiredMixin,
    BillingStoreContextMixin,
    View,
):
    pass


class BillingSeriesListView(BillingSeriesBaseView):
    http_method_names = ["get"]

    def get(self, request, *args, **kwargs):
        form = BillingSeriesFilterForm(request.GET or None)
        filters = form.cleaned_data if form.is_valid() else {}
        series = billing_series_list(
            business=self.business, store=self.store, **filters
        )
        page = Paginator(series, 25).get_page(request.GET.get("page"))
        query = request.GET.copy()
        query.pop("page", None)
        template = (
            "billing/partials/series_results.html"
            if request.headers.get("HX-Request") == "true"
            else "billing/series_list.html"
        )
        return render(
            request,
            template,
            {
                "store": self.store,
                "form": form,
                "series_page": page,
                "filter_query": query.urlencode(),
            },
        )


class BillingSeriesDetailView(BillingSeriesBaseView):
    http_method_names = ["get"]

    def get(self, request, *args, **kwargs):
        series = billing_series_detail(
            business=self.business, store=self.store, series_id=kwargs["series_pk"]
        )
        return render(
            request,
            "billing/series_detail.html",
            {"store": self.store, "series": series},
        )


class BillingSeriesFormView(BillingSeriesBaseView):
    http_method_names = ["get", "post"]

    def get_series(self):
        if "series_pk" not in self.kwargs:
            return None
        return billing_series_detail(
            business=self.business, store=self.store, series_id=self.kwargs["series_pk"]
        )

    def _render(self, form, series=None):
        return render(
            self.request,
            "billing/series_form.html",
            {"store": self.store, "form": form, "series": series},
        )

    def get(self, request, *args, **kwargs):
        series = self.get_series()
        return self._render(
            BillingSeriesForm(
                business=self.business, store=self.store, instance=series
            ),
            series,
        )

    def post(self, request, *args, **kwargs):
        series = self.get_series()
        form = BillingSeriesForm(
            request.POST, business=self.business, store=self.store, instance=series
        )
        if form.is_valid():
            payload = {
                "business": self.business,
                "store": self.store,
                "name": form.cleaned_data["name"],
                "cash_register": form.cleaned_data.get(
                    "cash_register", getattr(series, "cash_register", None)
                ),
                "document_type": form.cleaned_data.get(
                    "document_type", getattr(series, "document_type", None)
                ),
                "prefix": form.cleaned_data.get(
                    "prefix", getattr(series, "prefix", None)
                ),
                "year": form.cleaned_data.get("year", getattr(series, "year", None)),
                "padding": form.cleaned_data.get(
                    "padding", getattr(series, "padding", None)
                ),
            }
            try:
                if series:
                    saved = update_billing_series(series_id=series.pk, **payload)
                else:
                    saved = create_billing_series(**payload)
            except ValidationError as error:
                _add_service_errors(form, error)
            else:
                messages.success(request, "Serie guardada correctamente.")
                return redirect(
                    "billing:series_detail", store_id=self.store.pk, series_pk=saved.pk
                )
        return self._render(form, series)


class BillingSeriesToggleView(BillingSeriesBaseView):
    http_method_names = ["post"]

    def post(self, request, *args, **kwargs):
        action = kwargs["action"]
        if action not in {"activate", "deactivate"}:
            raise Http404
        service = (
            activate_billing_series
            if action == "activate"
            else deactivate_billing_series
        )
        service(series_id=kwargs["series_pk"], business=self.business, store=self.store)
        messages.success(request, "Serie actualizada correctamente.")
        return redirect(
            "billing:series_detail",
            store_id=self.store.pk,
            series_pk=kwargs["series_pk"],
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
                response = redirect(
                    "billing:document_detail",
                    store_id=self.store.pk,
                    document_pk=document.pk,
                )
                if request.headers.get("HX-Request") == "true":
                    response["HX-Redirect"] = response.url
                return response
        return self.render_form(
            form,
            subject,
            status=422 if request.headers.get("HX-Request") == "true" else 200,
        )

    def render_form(self, form, subject, status=200):
        return render(
            self.request,
            self.template_name,
            {"store": self.store, "form": form, "subject": subject},
            status=status,
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
