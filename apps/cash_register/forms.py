from decimal import Decimal

from django import forms

from apps.cash_register.models import CashMovement, CashRegister


class CashSessionOpenForm(forms.Form):
    cash_register = forms.ModelChoiceField(
        label="Caja", queryset=CashRegister.objects.none()
    )
    opening_amount = forms.DecimalField(
        label="Efectivo inicial", min_value=0, decimal_places=2, max_digits=14
    )

    def __init__(self, *args, business, store, cash_register=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["cash_register"].queryset = CashRegister.objects.filter(
            business=business, store=store, is_active=True
        )
        if cash_register is not None:
            self.fields["cash_register"].queryset = self.fields[
                "cash_register"
            ].queryset.filter(pk=cash_register.pk)
            self.fields["cash_register"].initial = cash_register
            self.fields["cash_register"].widget = forms.HiddenInput()


class CashAmountForm(forms.Form):
    amount = forms.DecimalField(
        min_value=Decimal("0.01"), decimal_places=2, max_digits=14
    )
    reason = forms.CharField(required=False, widget=forms.Textarea)


class CashInForm(CashAmountForm):
    pass


class CashOutForm(CashAmountForm):
    pass


class CashAdjustmentForm(CashAmountForm):
    adjustment_direction = forms.ChoiceField(
        choices=CashMovement.AdjustmentDirection.choices
    )


class CashCountReviewForm(forms.Form):
    counted_amount = forms.DecimalField(min_value=0, decimal_places=2, max_digits=14)
    notes = forms.CharField(required=False, widget=forms.Textarea)


class CashSessionCloseForm(CashCountReviewForm):
    pin = forms.CharField(required=False, widget=forms.PasswordInput)
