from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import Http404
from django.shortcuts import redirect, render
from django.views import View

from apps.business_config.models import POSSettings
from apps.payments.forms import PaymentCancelForm, PaymentCreateForm, PaymentRefundForm
from apps.payments.selectors import get_payment_detail
from apps.payments.services import (
    cancel_payment,
    register_refund,
    register_sale_payment,
)
from apps.sales.selectors import get_sale_detail, get_sale_return_detail
from apps.users.helpers import can_access_store
from apps.users.mixins import BusinessRequiredMixin


class _BasePaymentView(BusinessRequiredMixin, View):
    def context(self):
        business = self.request.user.business
        if not business:
            raise PermissionDenied
        return business, POSSettings.objects.filter(business=business).first()

    def validate_store(self, obj):
        if obj.store_id != self.kwargs["store_id"] or not can_access_store(
            self.request.user, obj.store
        ):
            raise Http404

    @staticmethod
    def add_error(form, error):
        if hasattr(error, "message_dict"):
            for field, values in error.message_dict.items():
                for value in values:
                    form.add_error(field if field in form.fields else None, value)
        else:
            form.add_error(None, error)


class PaymentCreateView(_BasePaymentView):
    template_name = "payments/payment_form.html"

    def get(self, request, *args, **kwargs):
        business, _ = self.context()
        sale = get_sale_detail(business=business, pk=kwargs["sale_id"])
        self.validate_store(sale)
        return render(
            request,
            self.template_name,
            {"form": PaymentCreateForm(business=business), "sale": sale},
        )

    def post(self, request, *args, **kwargs):
        business, _ = self.context()
        sale = get_sale_detail(business=business, pk=kwargs["sale_id"])
        self.validate_store(sale)
        form = PaymentCreateForm(request.POST, business=business)
        if form.is_valid():
            try:
                register_sale_payment(
                    business=business,
                    sale_id=sale.pk,
                    user=request.user,
                    method_id=form.cleaned_data["method"].pk,
                    amount=form.cleaned_data["amount"],
                    idempotency_key=form.cleaned_data["idempotency_key"],
                    external_reference=form.cleaned_data["external_reference"],
                    notes=form.cleaned_data["notes"],
                )
            except ValidationError as error:
                self.add_error(form, error)
            else:
                messages.success(request, "Cobro registrado correctamente.")
                return redirect(
                    "sales:sale_detail", store_id=sale.store_id, sale_pk=sale.pk
                )
        return render(request, self.template_name, {"form": form, "sale": sale})


class PaymentRefundView(_BasePaymentView):
    template_name = "payments/refund_form.html"

    def _data(self):
        business, settings = self.context()
        returned = get_sale_return_detail(
            business=business, pk=self.kwargs["sale_return_id"]
        )
        self.validate_store(returned)
        return business, settings, returned

    def get(self, request, *args, **kwargs):
        business, settings, returned = self._data()
        form = PaymentRefundForm(business=business, pos_settings=settings)
        return render(
            request, self.template_name, {"form": form, "return_doc": returned}
        )

    def post(self, request, *args, **kwargs):
        business, settings, returned = self._data()
        form = PaymentRefundForm(request.POST, business=business, pos_settings=settings)
        if form.is_valid():
            try:
                register_refund(
                    business=business,
                    sale_return_id=returned.pk,
                    user=request.user,
                    method_id=form.cleaned_data["method"].pk,
                    amount=form.cleaned_data["amount"],
                    idempotency_key=form.cleaned_data["idempotency_key"],
                    pin=form.cleaned_data["pin"],
                    external_reference=form.cleaned_data["external_reference"],
                    notes=form.cleaned_data["notes"],
                )
            except ValidationError as error:
                self.add_error(form, error)
            else:
                messages.success(request, "Reembolso registrado correctamente.")
                return redirect(
                    "sales:return_detail",
                    store_id=returned.store_id,
                    return_pk=returned.pk,
                )
        return render(
            request, self.template_name, {"form": form, "return_doc": returned}
        )


class PaymentCancelView(_BasePaymentView):
    template_name = "payments/cancel_confirm.html"

    def _data(self):
        business, settings = self.context()
        payment = get_payment_detail(business=business, pk=self.kwargs["payment_id"])
        self.validate_store(payment)
        return business, settings, payment

    def get(self, request, *args, **kwargs):
        _, settings, payment = self._data()
        return render(
            request,
            self.template_name,
            {"form": PaymentCancelForm(pos_settings=settings), "payment": payment},
        )

    def post(self, request, *args, **kwargs):
        business, settings, payment = self._data()
        form = PaymentCancelForm(request.POST, pos_settings=settings)
        if form.is_valid():
            try:
                cancel_payment(
                    business=business,
                    payment_id=payment.pk,
                    user=request.user,
                    pin=form.cleaned_data["pin"],
                )
            except ValidationError as error:
                self.add_error(form, error)
            else:
                messages.success(request, "Pago cancelado.")
                return redirect(
                    "sales:sale_detail",
                    store_id=payment.store_id,
                    sale_pk=payment.sale_id,
                )
        return render(request, self.template_name, {"form": form, "payment": payment})
