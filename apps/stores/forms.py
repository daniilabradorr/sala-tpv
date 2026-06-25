from django import forms

from apps.stores.models import Store


class StoreCreateForm(forms.ModelForm):
    """Formulario para crear una tienda"""

    class Meta:
        model = Store
        fields = [
            "name",
            # por defecto voy a dejar que se genere automaticamente el código de tienda,
            "address_line_1",
            "address_line_2",
            "postal_code",
            "city",
            "province",
            "country_code",
            "phone_store",
            "email_store",
        ]

    def __init__(self, *args, business=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.business = business

        if self.business:
            self.instance.business = self.business


class StoreUpdateForm(forms.ModelForm):
    """Formulrio para actualizar una tienda."""

    class Meta:
        model = Store
        fields = [
            "name",
            # para editar, dejo que edite el codifgo interno de la tienda,
            "code",
            "address_line_1",
            "address_line_2",
            "postal_code",
            "city",
            "province",
            "country_code",
            "phone_store",
            "email_store",
        ]
