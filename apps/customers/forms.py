from decimal import Decimal

from django import forms

from apps.customers.models import Customer, CustomerAccount


class CustomerBaseForm(forms.ModelForm):
    class Meta:
        model = Customer
        fields = [
            "customer_type",
            "name",
            "legal_name",
            "tax_identifier",
            "country_code",
            "foreign_id_type",
            "foreign_id",
            "email",
            "phone",
            "address_line_1",
            "postal_code",
            "city",
            "province",
        ]
        widgets = {
            field: forms.TextInput(attrs={"class": "form-control"})
            for field in fields
            if field != "customer_type"
        }
        widgets["customer_type"] = forms.Select(attrs={"class": "form-select"})
        widgets["email"] = forms.EmailInput(attrs={"class": "form-control"})
        help_texts = {
            "country_code": "Código ISO de dos letras.",
            "tax_identifier": "NIF/CIF nacional si aplica.",
            "foreign_id": "Requiere informar también el tipo de documento extranjero.",
        }

    def __init__(self, *args, business=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.business = business
        if business is not None:
            self.instance.business = business


class CustomerCreateForm(CustomerBaseForm):
    pass


class CustomerUpdateForm(CustomerBaseForm):
    pass


class CustomerAccountSettingsForm(forms.ModelForm):
    class Meta:
        model = CustomerAccount
        fields = ["credit_limit", "is_blocked"]
        widgets = {
            "credit_limit": forms.NumberInput(
                attrs={"class": "form-control", "step": "0.01", "min": "0"}
            ),
            "is_blocked": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }
        help_texts = {
            "credit_limit": "Límite máximo para nuevos cargos.",
            "is_blocked": "Solo bloquea cargos nuevos.",
        }

    def clean_credit_limit(self):
        credit_limit = self.cleaned_data["credit_limit"]
        if credit_limit < Decimal("0.00"):
            raise forms.ValidationError("El límite de crédito no puede ser negativo.")
        return credit_limit
