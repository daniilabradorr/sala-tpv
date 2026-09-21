from django import forms
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError

from apps.business_config.models import BusinessProfile
from apps.stores.models import Store
from apps.users.models import CustomUser


class OnboardingForm(forms.Form):
    SPANISH_POSTAL_CODE_ERROR = "Introduce un código postal español de 5 dígitos."
    PHONE_ERROR = (
        "El teléfono solo puede contener números, espacios, +, guiones o paréntesis."
    )
    STORE_OVERRIDE_NAMES = (
        "store_address_line_1",
        "store_address_line_2",
        "store_postal_code",
        "store_city",
        "store_province",
        "store_phone",
        "store_email",
    )

    legal_name = forms.CharField(label="Razón social", max_length=150)
    tax_identifier = forms.CharField(label="NIF/CIF", max_length=20)
    trade_name = forms.CharField(
        label="Nombre comercial", max_length=150, required=False
    )
    phone = forms.RegexField(
        label="Teléfono",
        max_length=30,
        regex=r"^[0-9+\-\s()]{6,30}$",
        error_messages={"invalid": PHONE_ERROR},
    )
    email = forms.EmailField(label="Email")
    address_line_1 = forms.CharField(label="Dirección", max_length=255)
    address_line_2 = forms.CharField(
        label="Dirección adicional", max_length=255, required=False
    )
    postal_code = forms.RegexField(
        label="Código postal",
        max_length=5,
        regex=r"^\d{5}$",
        error_messages={"invalid": SPANISH_POSTAL_CODE_ERROR},
    )
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
    store_postal_code = forms.RegexField(
        label="Código postal",
        max_length=5,
        required=False,
        regex=r"^\d{5}$",
        error_messages={"invalid": SPANISH_POSTAL_CODE_ERROR},
    )
    store_city = forms.CharField(label="Ciudad", max_length=120, required=False)
    store_province = forms.CharField(label="Provincia", max_length=120, required=False)
    store_phone = forms.RegexField(
        label="Teléfono",
        max_length=30,
        required=False,
        regex=r"^[0-9+\-\s()]{6,30}$",
        error_messages={"invalid": PHONE_ERROR},
    )
    store_email = forms.EmailField(label="Email", max_length=120, required=False)

    owner_first_name = forms.CharField(label="Nombre", max_length=150)
    owner_last_name = forms.CharField(label="Apellidos", max_length=150)
    owner_email = forms.EmailField(label="Email")
    owner_phone = forms.RegexField(
        label="Teléfono",
        max_length=20,
        required=False,
        regex=r"^\d+$",
        error_messages={"invalid": "El teléfono debe contener solo dígitos."},
    )
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
        # Stale or manipulated overrides are deliberately ignored when the
        # business-address fallback is selected. Replacing these bound fields
        # prevents their own validators running before Form.clean().
        same_address = False
        if self.is_bound:
            checkbox = self.fields["same_business_address"].widget
            raw_value = checkbox.value_from_datadict(
                self.data, self.files, self.add_prefix("same_business_address")
            )
            same_address = forms.BooleanField(required=False).to_python(raw_value)
        if same_address:
            for name in self.STORE_OVERRIDE_NAMES:
                original = self.fields[name]
                self.fields[name] = forms.CharField(
                    label=original.label,
                    required=False,
                    widget=original.widget,
                )
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

    def clean_owner_email(self):
        email = CustomUser.objects.normalize_email(self.cleaned_data["owner_email"])
        if CustomUser.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError(
                "No podemos utilizar este correo para crear la cuenta."
            )
        return email

    def clean_owner_password(self):
        password = self.cleaned_data["owner_password"]
        owner_candidate = CustomUser(
            first_name=self.cleaned_data.get("owner_first_name", ""),
            last_name=self.cleaned_data.get("owner_last_name", ""),
            email=self.cleaned_data.get("owner_email", ""),
            phone=self.cleaned_data.get("owner_phone", ""),
        )
        try:
            validate_password(password, user=owner_candidate)
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

        if cleaned.get("same_business_address"):
            for name in self.STORE_OVERRIDE_NAMES:
                cleaned[name] = None
        else:
            for name in self.STORE_OVERRIDE_NAMES:
                cleaned[name] = cleaned.get(name) or None
        return cleaned

    def full_clean(self):
        super().full_clean()
        for name, errors in self.errors.items():
            if name in self.fields and errors:
                self._mark_field_invalid(name)

    def add_accessible_error(self, field, error):
        self.add_error(field, error)
        if field in self.fields:
            self._mark_field_invalid(field)

    def _mark_field_invalid(self, name):
        described_by = self.fields[name].widget.attrs.get("aria-describedby", "")
        error_id = f"id_{name}_error"
        ids = described_by.split()
        if error_id not in ids:
            ids.append(error_id)
        self.fields[name].widget.attrs.update(
            {"aria-invalid": "true", "aria-describedby": " ".join(ids)}
        )

    def service_data(self):
        excluded = {"owner_password_confirmation", "same_business_address"}
        return {
            key: value
            for key, value in self.cleaned_data.items()
            if key not in excluded
        } | {"country_code": "ES"}
