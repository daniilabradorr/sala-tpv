from django import forms
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError

from apps.business_config.models import BusinessProfile
from apps.stores.models import Store
from apps.users.models import CustomUser


class OnboardingForm(forms.Form):
    legal_name = forms.CharField(label="Razón social", max_length=150)
    tax_identifier = forms.CharField(label="NIF/CIF", max_length=20)
    trade_name = forms.CharField(
        label="Nombre comercial", max_length=150, required=False
    )
    phone = forms.CharField(label="Teléfono", max_length=30)
    email = forms.EmailField(label="Email")
    address_line_1 = forms.CharField(label="Dirección", max_length=255)
    address_line_2 = forms.CharField(
        label="Dirección adicional", max_length=255, required=False
    )
    postal_code = forms.CharField(label="Código postal", max_length=12)
    city = forms.CharField(label="Ciudad", max_length=100)
    province = forms.CharField(label="Provincia", max_length=100)

    store_name = forms.CharField(label="Nombre de la tienda", max_length=150)
    same_business_address = forms.BooleanField(
        label="Usar la misma dirección del negocio", required=False, initial=True
    )
    store_address_line_1 = forms.CharField(
        label="Dirección", max_length=150, required=False
    )
    store_address_line_2 = forms.CharField(
        label="Dirección adicional", max_length=150, required=False
    )
    store_postal_code = forms.CharField(
        label="Código postal", max_length=10, required=False
    )
    store_city = forms.CharField(label="Ciudad", max_length=120, required=False)
    store_province = forms.CharField(label="Provincia", max_length=120, required=False)
    store_phone = forms.CharField(label="Teléfono", max_length=30, required=False)
    store_email = forms.EmailField(label="Email", max_length=120, required=False)

    owner_first_name = forms.CharField(label="Nombre", max_length=150)
    owner_last_name = forms.CharField(label="Apellidos", max_length=150)
    owner_email = forms.EmailField(label="Email")
    owner_phone = forms.CharField(label="Teléfono", max_length=20, required=False)
    owner_password = forms.CharField(
        label="Contraseña",
        strip=False,
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}),
    )
    owner_password_confirmation = forms.CharField(
        label="Confirmar contraseña",
        strip=False,
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}),
    )
    owner_pin = forms.RegexField(
        label="PIN",
        regex=r"^\d{4,6}$",
        error_messages={"invalid": "El PIN debe tener entre 4 y 6 dígitos."},
        widget=forms.PasswordInput(
            attrs={"inputmode": "numeric", "autocomplete": "new-password"}
        ),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Keep lengths aligned with the domain models rather than duplicating them.
        model_fields = {
            "legal_name": BusinessProfile._meta.get_field("legal_name"),
            "tax_identifier": BusinessProfile._meta.get_field("tax_identifier"),
            "store_name": Store._meta.get_field("name"),
            "owner_first_name": CustomUser._meta.get_field("first_name"),
        }
        for name, model_field in model_fields.items():
            self.fields[name].max_length = model_field.max_length

    def clean_tax_identifier(self):
        return self.cleaned_data["tax_identifier"].strip().upper()

    def clean_owner_password(self):
        password = self.cleaned_data["owner_password"]
        try:
            validate_password(password)
        except ValidationError as exc:
            raise forms.ValidationError(exc.messages) from exc
        return password

    def clean(self):
        cleaned = super().clean()
        password = cleaned.get("owner_password")
        confirmation = cleaned.get("owner_password_confirmation")
        if password and confirmation and password != confirmation:
            self.add_error(
                "owner_password_confirmation", "Las contraseñas no coinciden."
            )

        override_names = (
            "store_address_line_1",
            "store_address_line_2",
            "store_postal_code",
            "store_city",
            "store_province",
            "store_phone",
            "store_email",
        )
        if cleaned.get("same_business_address"):
            for name in override_names:
                cleaned[name] = None
        else:
            for name in override_names:
                cleaned[name] = cleaned.get(name) or None
        return cleaned

    def full_clean(self):
        super().full_clean()
        for name, errors in self.errors.items():
            if name in self.fields and errors:
                self.fields[name].widget.attrs.update(
                    {"aria-invalid": "true", "aria-describedby": f"id_{name}_error"}
                )

    def service_data(self):
        excluded = {"owner_password_confirmation", "same_business_address"}
        return {
            key: value
            for key, value in self.cleaned_data.items()
            if key not in excluded
        } | {"country_code": "ES"}
