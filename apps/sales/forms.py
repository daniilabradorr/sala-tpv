from django import forms

from apps.business_config.models import POSSettings
from apps.cash_register.models import CashRegister, CashSession
from apps.catalog.models import Product
from apps.customers.models import Customer

from .models import SaleLine, SaleReturnLine


class BusinessStoreForm(forms.Form):
    def __init__(self, *args, business, store=None, **kwargs):
        self.business = business
        self.store = store
        super().__init__(*args, **kwargs)


class SaleFilterForm(BusinessStoreForm):
    status = forms.ChoiceField(
        required=False,
        choices=[
            ("", "Todos"),
            ("open", "Abiertas"),
            ("completed", "Completadas"),
            ("cancelled", "Canceladas"),
        ],
    )
    query = forms.CharField(required=False)


class SaleOpenForm(BusinessStoreForm):
    customer = forms.ModelChoiceField(queryset=Customer.objects.none(), required=False)
    cash_register = forms.ModelChoiceField(
        queryset=CashRegister.objects.none(), required=False
    )
    cash_session = forms.ModelChoiceField(
        queryset=CashSession.objects.none(), required=False
    )
    requires_invoice = forms.BooleanField(required=False)
    notes = forms.CharField(required=False, widget=forms.Textarea)

    def __init__(self, *args, business, store, **kwargs):
        super().__init__(*args, business=business, store=store, **kwargs)
        self.fields["customer"].queryset = Customer.objects.filter(
            business=business, is_active=True
        )
        self.fields["cash_register"].queryset = CashRegister.objects.filter(
            business=business, store=store, is_active=True
        )
        sessions = CashSession.objects.filter(
            business=business,
            store=store,
            status=CashSession.Status.OPEN,
            closed_at__isnull=True,
        )
        register_id = (
            self.data.get("cash_register")
            if self.is_bound
            else self.initial.get("cash_register")
        )
        if register_id:
            sessions = sessions.filter(
                cash_register_id=getattr(register_id, "pk", register_id)
            )
        self.fields["cash_session"].queryset = sessions
        required = (
            POSSettings.objects.filter(business=business)
            .values_list("require_open_cash_register", flat=True)
            .first()
        )
        self.require_cash = True if required is None else required
        self.fields["cash_register"].required = self.require_cash
        self.fields["cash_session"].required = self.require_cash

    def clean(self):
        cleaned = super().clean()
        register, session = cleaned.get("cash_register"), cleaned.get("cash_session")
        if bool(register) != bool(session):
            raise forms.ValidationError(
                "La caja y la sesión deben indicarse conjuntamente."
            )
        if self.require_cash and not (register and session):
            raise forms.ValidationError("Se requiere una caja con una sesión abierta.")
        if session and register and session.cash_register_id != register.pk:
            self.add_error(
                "cash_session", "La sesión no pertenece a la caja seleccionada."
            )
        if cleaned.get("requires_invoice") and not cleaned.get("customer"):
            self.add_error(
                "customer", "Debes seleccionar un cliente para emitir factura."
            )
        return cleaned


class SaleHeaderUpdateForm(SaleOpenForm):
    pass


class SaleLineCreateForm(BusinessStoreForm):
    product = forms.ModelChoiceField(queryset=Product.objects.none())
    quantity = forms.DecimalField(min_value=0.001, max_digits=12, decimal_places=3)
    unit_price = forms.DecimalField(
        required=False, min_value=0, max_digits=12, decimal_places=2
    )
    discount_percent = forms.DecimalField(
        required=False,
        min_value=0,
        max_value=100,
        initial=0,
        max_digits=5,
        decimal_places=2,
    )

    def __init__(self, *args, business, store=None, **kwargs):
        super().__init__(*args, business=business, store=store, **kwargs)
        self.fields["product"].queryset = Product.objects.filter(
            business=business, is_active=True
        )


class SaleLineUpdateForm(forms.ModelForm):
    class Meta:
        model = SaleLine
        fields = ("quantity", "unit_price", "discount_percent")


class SaleCancelForm(forms.Form):
    reason = forms.CharField(widget=forms.Textarea)


class SaleReturnFilterForm(SaleFilterForm):
    pass


class SaleReturnCreateForm(forms.Form):
    reason = forms.CharField(widget=forms.Textarea)


class SaleReturnLineCreateForm(forms.Form):
    sale_line = forms.ModelChoiceField(queryset=SaleLine.objects.none())
    quantity = forms.DecimalField(min_value=0.001, max_digits=12, decimal_places=3)

    def __init__(self, *args, sale, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["sale_line"].queryset = sale.lines.all()


class SaleReturnLineUpdateForm(forms.ModelForm):
    class Meta:
        model = SaleReturnLine
        fields = ("quantity",)


class SaleReturnCompleteForm(forms.Form):
    confirm = forms.BooleanField()


class SaleReturnCancelForm(SaleCancelForm):
    pass
