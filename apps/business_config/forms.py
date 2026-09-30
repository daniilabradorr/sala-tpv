from decimal import Decimal

from django import forms

from apps.business_config.models import BusinessProfile, POSSettings
from apps.core.forms import wire_field_accessibility
from apps.core.media.validation import validate_image_upload


class BusinessProfileForm(forms.ModelForm):
    logo_upload = forms.FileField(
        label="Seleccionar nuevo logo",
        required=False,
        widget=forms.FileInput(
            attrs={
                "accept": "image/jpeg,image/png,image/webp",
                "data-media-upload": "",
            }
        ),
    )
    remove_logo = forms.BooleanField(label="Eliminar logo", required=False)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        wire_field_accessibility(self)

    def clean_logo_upload(self):
        upload = self.cleaned_data.get("logo_upload")
        return validate_image_upload(upload) if upload else upload

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("logo_upload") and cleaned.get("remove_logo"):
            raise forms.ValidationError(
                "No puedes subir y eliminar el logo al mismo tiempo."
            )
        return cleaned

    def clean_country_code(self):
        return self.cleaned_data["country_code"].strip().upper()

    def clean_tax_identifier(self):
        return self.cleaned_data["tax_identifier"].strip().upper()

    class Meta:
        model = BusinessProfile
        fields = [
            "legal_name",
            "tax_identifier",
            "trade_name",
            "phone",
            "email",
            "website",
            "address_line_1",
            "address_line_2",
            "postal_code",
            "city",
            "province",
            "country_code",
            "currency_code",
            "brand_name",
            "receipt_footer",
            "return_policy",
        ]
        widgets = {
            "receipt_footer": forms.Textarea(attrs={"rows": 3}),
            "return_policy": forms.Textarea(attrs={"rows": 4}),
        }


class POSSettingsForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # The dependency UI disables this input when discounts are off, so a
        # legitimate browser POST omits it. Conditional requiredness belongs
        # in clean(), not in the generated model field.
        self.fields["max_manual_discount_percent"].required = False
        wire_field_accessibility(self)

    def clean(self):
        cleaned = super().clean()
        if not cleaned.get("allow_manual_discounts"):
            cleaned["max_manual_discount_percent"] = Decimal("0.00")
        elif cleaned.get("max_manual_discount_percent") is None:
            self.add_error(
                "max_manual_discount_percent",
                "Indica el descuento máximo permitido.",
            )
        # A disabled dependent checkbox is absent from POST. Turning stock
        # control off must not silently overwrite the saved preference.
        if (
            not cleaned.get("enable_stock_control")
            and "allow_sale_without_stock" not in self.data
            and self.instance.pk
        ):
            cleaned["allow_sale_without_stock"] = self.instance.allow_sale_without_stock
        return cleaned

    class Meta:
        model = POSSettings
        fields = [
            "prices_include_tax",
            "enable_stock_control",
            "allow_sale_without_stock",
            "allow_manual_price",
            "allow_manual_discounts",
            "max_manual_discount_percent",
            "require_open_cash_register",
            "allow_split_payments",
            "require_pin_for_sensitive_actions",
        ]
        widgets = {
            "max_manual_discount_percent": forms.NumberInput(
                attrs={"min": "0", "max": "100", "step": "0.01"}
            )
        }
