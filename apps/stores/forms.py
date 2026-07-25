from django import forms

from apps.stores.models import Store


class StoreBaseForm(forms.ModelForm):
    """
    Formulario base para tiendas.

    Se encarga de asociar el Business a la instancia sin exponerlo
    como un campo manipulable por el usuario.
    """

    def __init__(self, *args, business=None, **kwargs):
        super().__init__(*args, **kwargs)

        self.business = business

        if self.business is not None:
            self.instance.business = self.business
        elif getattr(self.instance, "business_id", None):
            self.business = self.instance.business

    def _get_validation_exclusions(self):
        """
        Incluye business en la validación del modelo aunque no aparezca
        como campo editable del formulario.

        Esto permite validar correctamente constraints como:

        - business + name;
        - business + code.
        """
        exclude = super()._get_validation_exclusions()

        if getattr(self.instance, "business_id", None):
            exclude.discard("business")

        return exclude


class StoreCreateForm(StoreBaseForm):
    """
    Formulario para crear una tienda.

    El código se genera automáticamente desde Store.save().
    """

    class Meta:
        model = Store
        fields = [
            "name",
            "address_line_1",
            "address_line_2",
            "postal_code",
            "city",
            "province",
            "country_code",
            "phone_store",
            "email_store",
        ]


class StoreUpdateForm(StoreBaseForm):
    """
    Formulario para actualizar los datos editables de una tienda.

    El Business, el estado y la condición de predeterminada no pueden
    modificarse desde este formulario.
    """

    class Meta:
        model = Store
        fields = [
            "name",
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
