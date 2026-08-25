import uuid
from decimal import Decimal

from django import forms

from apps.cash_register.models import CashSession
from apps.payments.models import PaymentMethod


class _PaymentForm(forms.Form):
    method = forms.ModelChoiceField(queryset=PaymentMethod.objects.none())
    amount = forms.DecimalField(
        max_digits=14, decimal_places=2, min_value=Decimal("0.01")
    )
    cash_session = forms.ModelChoiceField(
        queryset=CashSession.objects.none(), required=True
    )
    external_reference = forms.CharField(max_length=150, required=False)
    notes = forms.CharField(required=False, widget=forms.Textarea)
    idempotency_key = forms.UUIDField(widget=forms.HiddenInput)

    def __init__(self, *args, business, store, **kwargs):
        kwargs.setdefault("initial", {})
        kwargs["initial"].setdefault("idempotency_key", uuid.uuid4())
        super().__init__(*args, **kwargs)
        self.fields["method"].queryset = PaymentMethod.objects.filter(
            business=business, is_active=True
        ).order_by("name", "pk")
        self.fields["cash_session"].queryset = (
            CashSession.objects.filter(
                business=business,
                store=store,
                status=CashSession.Status.OPEN,
                closed_at__isnull=True,
                cash_register__is_active=True,
            )
            .select_related("cash_register")
            .order_by("-opened_at", "-pk")
        )


class PaymentCreateForm(_PaymentForm):
    pass


class PaymentRefundForm(_PaymentForm):
    pin = forms.CharField(required=False, widget=forms.PasswordInput)

    def __init__(self, *args, pos_settings=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["method"].queryset = self.fields["method"].queryset.filter(
            allows_refund=True
        )
        if pos_settings and pos_settings.require_pin_for_sensitive_actions:
            self.fields["pin"].required = True


class PaymentCancelForm(forms.Form):
    pin = forms.CharField(required=False, widget=forms.PasswordInput)

    def __init__(self, *args, pos_settings=None, **kwargs):
        super().__init__(*args, **kwargs)
        if pos_settings and pos_settings.require_pin_for_sensitive_actions:
            self.fields["pin"].required = True


class SaleOnAccountForm(forms.Form):
    """Confirmación explícita; el importe se calcula bajo lock en el Service."""

    confirm = forms.BooleanField(label="Confirmar venta a cuenta")
