from decimal import Decimal
from uuid import uuid4

from django import forms
from django.db.models import Q

from apps.catalog.models import Product
from apps.purchases.models import Supplier
from apps.stores.models import Store
from apps.purchases.selectors import get_accessible_purchase_stores


class PurchaseFilterForm(forms.Form):
    q = forms.CharField(required=False, label="Buscar")
    status = forms.ChoiceField(required=False, choices=(), label="Estado")
    supplier = forms.ModelChoiceField(
        required=False, queryset=Supplier.objects.none(), label="Proveedor"
    )
    store = forms.ModelChoiceField(
        required=False, queryset=Store.objects.none(), label="Tienda"
    )
    date_from = forms.DateField(
        required=False, widget=forms.DateInput(attrs={"type": "date"})
    )
    date_to = forms.DateField(
        required=False, widget=forms.DateInput(attrs={"type": "date"})
    )

    def __init__(self, *args, business, user, **kwargs):
        super().__init__(*args, **kwargs)
        from apps.purchases.models import PurchaseStatusChoices

        self.fields["status"].choices = [("", "Todos")] + list(
            PurchaseStatusChoices.choices
        )
        self.fields["supplier"].queryset = Supplier.objects.filter(business=business)
        self.fields["store"].queryset = get_accessible_purchase_stores(
            business=business, user=user
        )


class SupplierFilterForm(forms.Form):
    q = forms.CharField(required=False, label="Buscar")
    status = forms.ChoiceField(
        required=False,
        initial="active",
        choices=(("active", "Activos"), ("inactive", "Inactivos"), ("all", "Todos")),
    )


class SupplierForm(forms.Form):
    name = forms.CharField(max_length=180)
    legal_name = forms.CharField(max_length=180, required=False)
    tax_identifier = forms.CharField(max_length=30, required=False)
    email = forms.EmailField(required=False)
    phone = forms.CharField(max_length=30, required=False)
    address = forms.CharField(widget=forms.Textarea, required=False)
    is_active = forms.BooleanField(required=False, initial=True)


class _PurchaseHeaderForm(forms.Form):
    store = forms.ModelChoiceField(queryset=Store.objects.none())
    supplier = forms.ModelChoiceField(queryset=Supplier.objects.none())
    reference = forms.CharField(max_length=120, required=False)
    notes = forms.CharField(widget=forms.Textarea, required=False)

    def __init__(self, *args, business, user, purchase=None, **kwargs):
        super().__init__(*args, **kwargs)
        stores = get_accessible_purchase_stores(
            business=business, user=user, active_only=True
        )
        suppliers = Supplier.objects.filter(business=business, is_active=True)
        if purchase is not None:
            accessible = get_accessible_purchase_stores(business=business, user=user)
            stores = accessible.filter(Q(is_active=True) | Q(pk=purchase.store_id))
            suppliers = Supplier.objects.filter(business=business).filter(
                Q(is_active=True) | Q(pk=purchase.supplier_id)
            )
        self.fields["store"].queryset = stores
        self.fields["supplier"].queryset = suppliers.order_by("name", "pk")


class PurchaseCreateForm(_PurchaseHeaderForm):
    pass


class PurchaseUpdateForm(_PurchaseHeaderForm):
    pass


class PurchaseLineCreateForm(forms.Form):
    product = forms.ModelChoiceField(queryset=Product.objects.none())
    quantity = forms.DecimalField(
        max_digits=14, decimal_places=3, min_value=Decimal("0.001")
    )
    unit_cost = forms.DecimalField(max_digits=12, decimal_places=2, min_value=0)
    tax_rate = forms.DecimalField(
        max_digits=5, decimal_places=2, min_value=0, initial=0
    )

    def __init__(self, *args, business, **kwargs):
        super().__init__(*args, **kwargs)
        products = Product.objects.filter(business=business, is_active=True)
        product_query = (
            self.data.get("product_query") or kwargs.pop("product_query", "")
        ).strip()
        if product_query:
            products = products.filter(
                Q(name__icontains=product_query)
                | Q(sku__icontains=product_query)
                | Q(barcode__icontains=product_query)
            )
        self.fields["product"].queryset = products.order_by("name", "pk")[:30]


class PurchaseLineUpdateForm(forms.Form):
    quantity = forms.DecimalField(
        max_digits=14, decimal_places=3, min_value=Decimal("0.001")
    )
    unit_cost = forms.DecimalField(max_digits=12, decimal_places=2, min_value=0)
    tax_rate = forms.DecimalField(max_digits=5, decimal_places=2, min_value=0)


class PurchaseReceiptForm(forms.Form):
    notes = forms.CharField(widget=forms.Textarea, required=False)
    idempotency_key = forms.UUIDField(widget=forms.HiddenInput)

    def __init__(self, *args, purchase_lines, **kwargs):
        super().__init__(*args, **kwargs)
        if not self.is_bound:
            self.initial.setdefault("idempotency_key", uuid4())
        self.purchase_lines = list(purchase_lines)
        for line in self.purchase_lines:
            remaining = line.quantity_ordered - line.quantity_received
            if remaining <= 0:
                continue
            self.fields[f"line_{line.pk}"] = forms.DecimalField(
                max_digits=14,
                decimal_places=3,
                min_value=Decimal("0.001"),
                required=False,
                label=(
                    f"{line.product_name}: pedida {line.quantity_ordered}, "
                    f"recibida {line.quantity_received}, pendiente {remaining}"
                ),
            )

    def clean(self):
        cleaned = super().clean()
        if not any(
            cleaned.get(f"line_{line.pk}")
            for line in self.purchase_lines
            if f"line_{line.pk}" in self.fields
        ):
            raise forms.ValidationError(
                "Debes indicar al menos una cantidad a recibir."
            )
        return cleaned

    def receipt_lines(self):
        return [
            {
                "purchase_line": line,
                "quantity_received": self.cleaned_data[f"line_{line.pk}"],
            }
            for line in self.purchase_lines
            if f"line_{line.pk}" in self.fields
            and self.cleaned_data.get(f"line_{line.pk}") is not None
        ]
