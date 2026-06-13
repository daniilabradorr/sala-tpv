from django import forms

from apps.business_config.models import BusinessProfile, POSSettings


class BusinessProfileForm(forms.ModelForm):
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
            "logo_url",
            "receipt_footer",
            "return_policy",
            "default_tax_rate",
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
