from django import forms

from apps.business_config.models import BusinessProfile, POSSettings
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
