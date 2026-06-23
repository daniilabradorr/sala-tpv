from django import forms
from django.forms import modelformset_factory

from app.stores.models import Store

class StoreCreateForm(forms.ModelForm):
    """Formulario para crear una tienda
    """
    
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

class StoreUpdateForm(forms.ModelForm):
    """Formulrio para actualizar una tienda.
    """
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