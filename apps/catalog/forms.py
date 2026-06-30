from django import forms

from apps.catalog.models import Category, Tax, Product


class CategoryBaseForm(forms.ModelForm):
    """
    Formulario base para categorías.

    Reglas importantes:
    - El usuario NO elige el business desde el formulario.
    - El business se recibe desde la vista usando request.user.business.
    - El parent solo puede ser una categoría del mismo negocio.
    """

    class Meta:
        model = Category
        fields = [
            "name",
            "slug",
            "parent",
            "sort_order",
            "is_active",
        ]

        widgets = {
            "name": forms.TextInput(
                attrs={
                    "class": "form-control",
                    "placeholder": "Ejemplo: Bebidas",
                }
            ),
            "slug": forms.TextInput(
                attrs={
                    "class": "form-control",
                    "placeholder": "Se genera automáticamente si lo dejas vacío",
                }
            ),
            "parent": forms.Select(
                attrs={
                    "class": "form-select",
                }
            ),
            "sort_order": forms.NumberInput(
                attrs={
                    "class": "form-control",
                    "min": "0",
                }
            ),
            "is_active": forms.CheckboxInput(
                attrs={
                    "class": "form-check-input",
                }
            ),
        }

        help_texts = {
            "name": "Nombre visible de la categoría.",
            "slug": "Identificador interno para URLs. Si lo dejas vacío, se genera automáticamente.",
            "parent": "Opcional. Sirve para crear subcategorías.",
            "sort_order": "Orden visual. Los números más bajos aparecen antes.",
            "is_active": "Si está desactivada, no debería mostrarse para nuevas ventas.",
        }

    def __init__(self, *args, business=None, **kwargs):
        super().__init__(*args, **kwargs)

        self.business = business

        # Por defecto, no mostramos ninguna categoría padre
        # hasta saber el business.
        self.fields["parent"].queryset = Category.objects.none()

        if self.business:
            parent_queryset = Category.objects.filter(
                business=self.business,
                is_active=True,
            ).order_by(
                "sort_order",
                "name",
            )

            # En edición, evitamos que una categoría pueda ser padre de sí misma.
            if self.instance and self.instance.pk:
                parent_queryset = parent_queryset.exclude(pk=self.instance.pk)

            self.fields["parent"].queryset = parent_queryset

            # Asignamos el business a la instancia para que model.clean()
            # pueda validar correctamente.
            self.instance.business = self.business

    def clean_parent(self):
        parent = self.cleaned_data.get("parent")

        if parent and self.business and parent.business_id != self.business.id:
            raise forms.ValidationError(
                "La categoría padre debe pertenecer al mismo negocio."
            )

        return parent


class CategoryCreateForm(CategoryBaseForm):
    """
    Formulario para crear categorías.
    """

    class Meta(CategoryBaseForm.Meta):
        fields = [
            "name",
            "slug",
            "parent",
            "sort_order",
        ]


class CategoryUpdateForm(CategoryBaseForm):
    """
    Formulario para editar categorías.
    """

    class Meta(CategoryBaseForm.Meta):
        fields = [
            "name",
            "slug",
            "parent",
            "sort_order",
            "is_active",
        ]


class TaxBaseForm(forms.ModelForm):
    """
    Formulario base para impuestos/tratamientos fiscales.

    Reglas:
    - El usuario NO elige el business desde el formulario.
    - El business se asigna desde la vista con request.user.business.
    - is_default no se gestiona aquí porque tendremos una vista específica:
      TaxSetDefaultView.
    """

    class Meta:
        model = Tax
        fields = [
            "name",
            "code",
            "tax_type",
            "rate",
            "clave_regimen",
            "calificacion_operacion",
            "operacion_exenta",
            "has_equivalence_surcharge",
            "equivalence_surcharge_rate",
            "is_active",
        ]

        widgets = {
            "name": forms.TextInput(
                attrs={
                    "class": "form-control",
                    "placeholder": "Ejemplo: IVA 21%",
                }
            ),
            "code": forms.TextInput(
                attrs={
                    "class": "form-control",
                    "placeholder": "Ejemplo: IVA_21. Se genera si lo dejas vacío.",
                }
            ),
            "tax_type": forms.Select(
                attrs={
                    "class": "form-select",
                }
            ),
            "rate": forms.NumberInput(
                attrs={
                    "class": "form-control",
                    "step": "0.01",
                    "min": "0",
                    "placeholder": "Ejemplo: 21.00",
                }
            ),
            "clave_regimen": forms.Select(
                attrs={
                    "class": "form-select",
                }
            ),
            "calificacion_operacion": forms.Select(
                attrs={
                    "class": "form-select",
                }
            ),
            "operacion_exenta": forms.Select(
                attrs={
                    "class": "form-select",
                }
            ),
            "has_equivalence_surcharge": forms.CheckboxInput(
                attrs={
                    "class": "form-check-input",
                }
            ),
            "equivalence_surcharge_rate": forms.NumberInput(
                attrs={
                    "class": "form-control",
                    "step": "0.01",
                    "min": "0",
                    "placeholder": "Ejemplo: 5.20",
                }
            ),
            "is_active": forms.CheckboxInput(
                attrs={
                    "class": "form-check-input",
                }
            ),
        }

        help_texts = {
            "name": "Nombre visible del impuesto.",
            "code": "Código interno. Si lo dejas vacío, se genera automáticamente.",
            "tax_type": "Normalmente IVA para península/Baleares.",
            "rate": "Porcentaje del impuesto. Ejemplo: 21.00, 10.00, 4.00 o 0.00.",
            "clave_regimen": "Para venta normal con IVA, normalmente 01.",
            "calificacion_operacion": "S1 para venta normal con IVA.",
            "operacion_exenta": "Solo se rellena si la operación está exenta.",
            "has_equivalence_surcharge": "Marcar solo si aplica recargo de equivalencia.",
            "equivalence_surcharge_rate": "Solo si hay recargo de equivalencia.",
            "is_active": "Si está desactivado, no debería usarse en nuevos productos.",
        }

    def __init__(self, *args, business=None, **kwargs):
        super().__init__(*args, **kwargs)

        self.business = business

        if self.business:
            self.instance.business = self.business

        # Permitimos vacío en estos campos porque no siempre aplican.
        self.fields["clave_regimen"].required = False
        self.fields["calificacion_operacion"].required = False
        self.fields["operacion_exenta"].required = False
        self.fields["equivalence_surcharge_rate"].required = False

    def clean_code(self):
        """
        Si el código viene vacío, lo dejamos vacío.
        El modelo Tax.save() generará uno automático.
        """

        code = self.cleaned_data.get("code")

        if code:
            return code.strip().upper()

        return code


class TaxCreateForm(TaxBaseForm):
    """
    Formulario para crear impuestos.
    """

    class Meta(TaxBaseForm.Meta):
        fields = [
            "name",
            "code",
            "tax_type",
            "rate",
            "clave_regimen",
            "calificacion_operacion",
            "operacion_exenta",
            "has_equivalence_surcharge",
            "equivalence_surcharge_rate",
        ]


class TaxUpdateForm(TaxBaseForm):
    """
    Formulario para editar impuestos.
    """

    class Meta(TaxBaseForm.Meta):
        fields = [
            "name",
            "code",
            "tax_type",
            "rate",
            "clave_regimen",
            "calificacion_operacion",
            "operacion_exenta",
            "has_equivalence_surcharge",
            "equivalence_surcharge_rate",
            "is_active",
        ]


class ProductBaseForm(forms.ModelForm):
    """
    Formulario base para productos y servicios.

    Reglas:
    - El usuario NO elige el business desde el formulario.
    - category solo muestra categorías del negocio.
    - tax solo muestra impuestos activos del negocio.
    - sku se puede dejar vacío y se genera automáticamente.
    - barcode se puede dejar vacío y se genera automáticamente solo en productos físicos.
    - is_active y track_stock en la creacion no se ponen,se dejan como default, en el update si.
    """

    class Meta:
        model = Product
        fields = [
            "name",
            "sku",
            "barcode",
            "category",
            "tax",
            "base_price",
            "cost_price",
            "unit",
            "sort_order",
            "is_service",
        ]

        widgets = {
            "name": forms.TextInput(
                attrs={
                    "class": "form-control",
                    "placeholder": "Ejemplo: Coca-Cola 500ml",
                }
            ),
            "sku": forms.TextInput(
                attrs={
                    "class": "form-control",
                    "placeholder": "Se genera automáticamente si lo dejas vacío",
                }
            ),
            "barcode": forms.TextInput(
                attrs={
                    "class": "form-control",
                    "placeholder": "Se genera en productos físicos si lo dejas vacío",
                }
            ),
            "category": forms.Select(
                attrs={
                    "class": "form-select",
                }
            ),
            "tax": forms.Select(
                attrs={
                    "class": "form-select",
                }
            ),
            "base_price": forms.NumberInput(
                attrs={
                    "class": "form-control",
                    "step": "0.01",
                    "min": "0",
                    "placeholder": "Precio sin IVA",
                }
            ),
            "cost_price": forms.NumberInput(
                attrs={
                    "class": "form-control",
                    "step": "0.01",
                    "min": "0",
                    "placeholder": "Coste de compra",
                }
            ),
            "unit": forms.Select(
                attrs={
                    "class": "form-select",
                }
            ),
            "sort_order": forms.NumberInput(
                attrs={
                    "class": "form-control",
                    "min": "0",
                }
            ),
            "is_service": forms.CheckboxInput(
                attrs={
                    "class": "form-check-input",
                }
            ),
        }

        help_texts = {
            "name": "Nombre visible en catálogo, venta y ticket.",
            "sku": "Código interno. Si lo dejas vacío, se genera automáticamente.",
            "barcode": "Código escaneable. Si es producto físico y lo dejas vacío, se genera automáticamente.",
            "category": "Categoría comercial del producto.",
            "tax": "Impuesto específico. Si se deja vacío, se usará el impuesto por defecto del negocio.",
            "base_price": "Precio base sin IVA.",
            "cost_price": "Coste para márgenes y reporting.",
            "unit": "Unidad de venta.",
            "sort_order": "Orden visual dentro de la categoría. Los números más bajos aparecen antes.",
            "is_service": "Marca si no es un producto físico.",
        }

    def __init__(self, *args, business=None, **kwargs):
        super().__init__(*args, **kwargs)

        self.business = business

        self.fields["category"].queryset = Category.objects.none()
        self.fields["tax"].queryset = Tax.objects.none()

        if self.business:
            self.instance.business = self.business

            self.fields["category"].queryset = Category.objects.filter(
                business=self.business,
                is_active=True,
            ).order_by(
                "sort_order",
                "name",
            )

            self.fields["tax"].queryset = Tax.objects.filter(
                business=self.business,
                is_active=True,
            ).order_by(
                "-is_default",
                "name",
            )

        self.fields["category"].required = False
        self.fields["tax"].required = False
        self.fields["sku"].required = False
        self.fields["barcode"].required = False
        self.fields["cost_price"].required = False

    def clean_sku(self):
        """
        Si el SKU viene vacío, lo dejamos vacío.
        Product.save() generará uno automático.
        """

        sku = self.cleaned_data.get("sku")

        if sku:
            return sku.strip().upper()

        return sku

    def clean_barcode(self):
        """
        Si el barcode viene vacío, lo dejamos vacío.
        Product.save() decidirá:
        - Producto físico: genera barcode interno.
        - Servicio: lo deja en None.
        """

        barcode = self.cleaned_data.get("barcode")

        if barcode:
            return barcode.strip()

        return barcode

    def clean_category(self):
        category = self.cleaned_data.get("category")

        if category and self.business and category.business_id != self.business.id:
            raise forms.ValidationError(
                "La categoría debe pertenecer al mismo negocio."
            )

        return category

    def clean_tax(self):
        tax = self.cleaned_data.get("tax")

        if tax and self.business and tax.business_id != self.business.id:
            raise forms.ValidationError("El impuesto debe pertenecer al mismo negocio.")

        if tax and not tax.is_active:
            raise forms.ValidationError(
                "No puedes asignar un impuesto inactivo al producto."
            )

        return tax


class ProductCreateForm(ProductBaseForm):
    """
    Formulario para crear productos/servicios.
    """

    class Meta(ProductBaseForm.Meta):
        fields = [
            "name",
            "sku",
            "barcode",
            "category",
            "tax",
            "base_price",
            "cost_price",
            "unit",
            "sort_order",
            "is_service",
        ]


class ProductUpdateForm(ProductBaseForm):
    """
    Formulario para editar productos/servicios.
    """

    class Meta(ProductBaseForm.Meta):
        fields = [
            "name",
            "sku",
            "barcode",
            "category",
            "tax",
            "base_price",
            "cost_price",
            "unit",
            "sort_order",
            "track_stock",
            "is_service",
            "is_active",
        ]
