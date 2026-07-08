"""Forms del módulo inventory.

Regla general:
- El usuario nunca elige business desde formularios.
- Los querysets de store, product e inventory_item se filtran por business.
- Los forms validan entrada del usuario.
- Los services ejecutan cambios de stock.
- Los models protegen coherencia final.
"""

from decimal import Decimal

from django import forms

from apps.catalog.models import Product
from apps.inventory.models import (
    InventoryItem,
    StockAdjustment,
    StockAdjustmentLine,
    StockMovement,
)
from apps.stores.models import Store


# ==========================================================
# Helpers internos
# ==========================================================


def _decimal_attrs(step="0.001", min_value="0"):
    """Attrs comunes para campos decimales de stock."""

    return {
        "class": "form-control",
        "step": step,
        "min": min_value,
    }


# ==========================================================
# Filtros de inventario
# ==========================================================


class InventoryItemFilterForm(forms.Form):
    """Formulario de filtros para el listado de inventario."""

    store = forms.ModelChoiceField(
        label="Tienda",
        queryset=Store.objects.none(),
        required=False,
        widget=forms.Select(attrs={"class": "form-select"}),
    )

    product = forms.ModelChoiceField(
        label="Producto",
        queryset=Product.objects.none(),
        required=False,
        widget=forms.Select(attrs={"class": "form-select"}),
    )

    is_active = forms.ChoiceField(
        label="Estado",
        required=False,
        choices=[
            ("", "Todos"),
            ("true", "Activos"),
            ("false", "Inactivos"),
        ],
        widget=forms.Select(attrs={"class": "form-select"}),
    )

    low_stock = forms.BooleanField(
        label="Solo stock bajo",
        required=False,
        widget=forms.CheckboxInput(attrs={"class": "form-check-input"}),
    )

    out_of_stock = forms.BooleanField(
        label="Solo sin stock",
        required=False,
        widget=forms.CheckboxInput(attrs={"class": "form-check-input"}),
    )

    def __init__(self, *args, business=None, **kwargs):
        super().__init__(*args, **kwargs)

        self.business = business

        if not self.business:
            return

        # En filtros permitimos ver tiendas históricas aunque estén inactivas.
        self.fields["store"].queryset = Store.objects.filter(
            business=self.business,
        ).order_by("name")

        # En filtros permitimos ver productos físicos con control de stock,
        # aunque estén inactivos, porque pueden tener histórico.
        self.fields["product"].queryset = Product.objects.filter(
            business=self.business,
            is_service=False,
            track_stock=True,
        ).order_by("name")


# ==========================================================
# InventoryItem
# ==========================================================


class InventoryItemCreateForm(forms.ModelForm):
    """Formulario para crear una ficha de inventario.

    IMPORTANTE:
    - No muestra business.
    - No muestra current_stock.
    - No muestra reserved_stock.
    - La ficha se crea con stock 0.
    - El stock inicial se carga después mediante InitialStockForm + service.
    """

    class Meta:
        model = InventoryItem
        fields = [
            "store",
            "product",
            "minimum_stock",
            "maximum_stock",
            "location",
        ]

        widgets = {
            "store": forms.Select(
                attrs={
                    "class": "form-select",
                }
            ),
            "product": forms.Select(
                attrs={
                    "class": "form-select",
                }
            ),
            "minimum_stock": forms.NumberInput(
                attrs={
                    **_decimal_attrs(),
                    "placeholder": "Ejemplo: 5.000",
                }
            ),
            "maximum_stock": forms.NumberInput(
                attrs={
                    **_decimal_attrs(),
                    "placeholder": "Opcional. Ejemplo: 100.000",
                }
            ),
            "location": forms.TextInput(
                attrs={
                    "class": "form-control",
                    "placeholder": "Ejemplo: almacén, estantería A1, cámara...",
                }
            ),
        }

        help_texts = {
            "store": "Tienda donde se controlará el stock.",
            "product": "Solo aparecen productos físicos que controlan stock.",
            "minimum_stock": "Cantidad mínima antes de avisar reposición.",
            "maximum_stock": "Cantidad máxima recomendada. Opcional.",
            "location": "Ubicación interna del producto. Opcional.",
        }

    def __init__(self, *args, business=None, **kwargs):
        super().__init__(*args, **kwargs)

        self.business = business

        self.fields["store"].queryset = Store.objects.none()
        self.fields["product"].queryset = Product.objects.none()

        self.fields["maximum_stock"].required = False
        self.fields["location"].required = False

        if not self.business:
            return

        self.instance.business = self.business

        self.fields["store"].queryset = Store.objects.filter(
            business=self.business,
            is_active=True,
        ).order_by("name")

        self.fields["product"].queryset = Product.objects.filter(
            business=self.business,
            is_active=True,
            is_service=False,
            track_stock=True,
        ).order_by("name")

    def clean_store(self):
        store = self.cleaned_data.get("store")

        if store and self.business and store.business_id != self.business.id:
            raise forms.ValidationError("La tienda debe pertenecer al mismo negocio.")

        if store and not store.is_active:
            raise forms.ValidationError(
                "No puedes crear inventario en una tienda inactiva."
            )

        return store

    def clean_product(self):
        product = self.cleaned_data.get("product")

        if product and self.business and product.business_id != self.business.id:
            raise forms.ValidationError("El producto debe pertenecer al mismo negocio.")

        if product and product.is_service:
            raise forms.ValidationError("No se puede controlar stock de un servicio.")

        if product and not product.track_stock:
            raise forms.ValidationError(
                "No se puede crear inventario para un producto que no controla stock."
            )

        if product and not product.is_active:
            raise forms.ValidationError(
                "No puedes crear inventario para un producto inactivo."
            )

        return product

    def clean_minimum_stock(self):
        minimum_stock = self.cleaned_data.get("minimum_stock")

        if minimum_stock is not None and minimum_stock < Decimal("0.000"):
            raise forms.ValidationError("El stock mínimo no puede ser negativo.")

        return minimum_stock

    def clean_maximum_stock(self):
        maximum_stock = self.cleaned_data.get("maximum_stock")

        if maximum_stock is not None and maximum_stock < Decimal("0.000"):
            raise forms.ValidationError("El stock máximo no puede ser negativo.")

        return maximum_stock

    def clean_location(self):
        location = self.cleaned_data.get("location")

        if location:
            return location.strip()

        return location

    def clean(self):
        cleaned_data = super().clean()

        store = cleaned_data.get("store")
        product = cleaned_data.get("product")
        minimum_stock = cleaned_data.get("minimum_stock")
        maximum_stock = cleaned_data.get("maximum_stock")

        if (
            maximum_stock is not None
            and minimum_stock is not None
            and maximum_stock < minimum_stock
        ):
            self.add_error(
                "maximum_stock",
                "El stock máximo no puede ser menor que el stock mínimo.",
            )

        if self.business and store and product:
            exists = InventoryItem.objects.filter(
                business=self.business,
                store=store,
                product=product,
            ).exists()

            if exists:
                raise forms.ValidationError(
                    "Ya existe una ficha de inventario para este producto en esta tienda."
                )

        return cleaned_data

    def save(self, commit=True):
        """Crea la ficha de inventario sin tocar stock físico real.

        La ficha nace con:
        - current_stock = 0
        - reserved_stock = 0

        El stock inicial se cargará después con InitialStockForm + service.
        """

        inventory_item = super().save(commit=False)

        if self.business:
            inventory_item.business = self.business

        inventory_item.current_stock = Decimal("0.000")
        inventory_item.reserved_stock = Decimal("0.000")

        if commit:
            inventory_item.save()

        return inventory_item


class InventoryItemUpdateForm(forms.ModelForm):
    """Formulario para editar configuración de inventario.

    IMPORTANTE:
    Aquí NO se edita current_stock.
    Si quieres cambiar stock real, se debe hacer con:
    - carga de stock inicial
    - ajuste de stock
    - compra recibida
    - venta
    - devolución
    """

    class Meta:
        model = InventoryItem
        fields = [
            "minimum_stock",
            "maximum_stock",
            "location",
            "is_active",
        ]

        widgets = {
            "minimum_stock": forms.NumberInput(
                attrs={
                    **_decimal_attrs(),
                    "placeholder": "Ejemplo: 5.000",
                }
            ),
            "maximum_stock": forms.NumberInput(
                attrs={
                    **_decimal_attrs(),
                    "placeholder": "Opcional. Ejemplo: 100.000",
                }
            ),
            "location": forms.TextInput(
                attrs={
                    "class": "form-control",
                    "placeholder": "Ejemplo: almacén, estantería A1, cámara...",
                }
            ),
            "is_active": forms.CheckboxInput(
                attrs={
                    "class": "form-check-input",
                }
            ),
        }

        help_texts = {
            "minimum_stock": "Cantidad mínima antes de avisar reposición.",
            "maximum_stock": "Cantidad máxima recomendada. Opcional.",
            "location": "Ubicación interna del producto. Opcional.",
            "is_active": "Desactiva la ficha sin borrar histórico.",
        }

    def __init__(self, *args, business=None, **kwargs):
        super().__init__(*args, **kwargs)

        self.business = business
        self.fields["maximum_stock"].required = False
        self.fields["location"].required = False

        if self.business:
            self.instance.business = self.business

    def clean_minimum_stock(self):
        minimum_stock = self.cleaned_data.get("minimum_stock")

        if minimum_stock is not None and minimum_stock < Decimal("0.000"):
            raise forms.ValidationError("El stock mínimo no puede ser negativo.")

        return minimum_stock

    def clean_maximum_stock(self):
        maximum_stock = self.cleaned_data.get("maximum_stock")

        if maximum_stock is not None and maximum_stock < Decimal("0.000"):
            raise forms.ValidationError("El stock máximo no puede ser negativo.")

        return maximum_stock

    def clean_location(self):
        location = self.cleaned_data.get("location")

        if location:
            return location.strip()

        return location

    def clean(self):
        cleaned_data = super().clean()

        minimum_stock = cleaned_data.get("minimum_stock")
        maximum_stock = cleaned_data.get("maximum_stock")

        if self.business and self.instance.pk:
            if self.instance.business_id != self.business.id:
                raise forms.ValidationError(
                    "No puedes editar inventario de otro negocio."
                )

        if (
            maximum_stock is not None
            and minimum_stock is not None
            and maximum_stock < minimum_stock
        ):
            self.add_error(
                "maximum_stock",
                "El stock máximo no puede ser menor que el stock mínimo.",
            )

        return cleaned_data


class InitialStockForm(forms.Form):
    """Formulario para cargar stock inicial.

    Este form NO modifica stock.
    Solo valida los datos de entrada.

    La view deberá llamar a un service tipo:

    create_initial_stock(
        inventory_item=inventory_item,
        quantity=form.cleaned_data["quantity"],
        unit_cost=form.cleaned_data["unit_cost"],
        reason=form.cleaned_data["reason"],
        notes=form.cleaned_data["notes"],
        user=request.user,
    )
    """

    quantity = forms.DecimalField(
        label="Cantidad inicial",
        max_digits=14,
        decimal_places=3,
        min_value=Decimal("0.001"),
        widget=forms.NumberInput(
            attrs={
                **_decimal_attrs(),
                "placeholder": "Ejemplo: 25.000",
            }
        ),
        help_text="Cantidad física inicial que hay realmente.",
    )

    unit_cost = forms.DecimalField(
        label="Coste unitario",
        max_digits=12,
        decimal_places=2,
        required=False,
        min_value=Decimal("0.00"),
        widget=forms.NumberInput(
            attrs={
                "class": "form-control",
                "step": "0.01",
                "min": "0",
                "placeholder": "Opcional. Ejemplo: 1.50",
            }
        ),
        help_text="Opcional. Coste unitario asociado al stock inicial.",
    )

    reason = forms.CharField(
        label="Motivo",
        max_length=180,
        required=False,
        widget=forms.TextInput(
            attrs={
                "class": "form-control",
                "placeholder": "Ejemplo: inventario inicial",
            }
        ),
    )

    notes = forms.CharField(
        label="Notas",
        required=False,
        widget=forms.Textarea(
            attrs={
                "class": "form-control",
                "rows": 3,
                "placeholder": "Notas internas opcionales.",
            }
        ),
    )

    def clean_reason(self):
        reason = self.cleaned_data.get("reason")

        if reason:
            return reason.strip()

        return reason

    def clean_notes(self):
        notes = self.cleaned_data.get("notes")

        if notes:
            return notes.strip()

        return notes


# ==========================================================
# Movimientos de stock
# ==========================================================


class StockMovementFilterForm(forms.Form):
    """Formulario de filtros para movimientos de stock."""

    store = forms.ModelChoiceField(
        label="Tienda",
        queryset=Store.objects.none(),
        required=False,
        widget=forms.Select(attrs={"class": "form-select"}),
    )

    product = forms.ModelChoiceField(
        label="Producto",
        queryset=Product.objects.none(),
        required=False,
        widget=forms.Select(attrs={"class": "form-select"}),
    )

    movement_type = forms.ChoiceField(
        label="Tipo de movimiento",
        choices=[],
        required=False,
        widget=forms.Select(attrs={"class": "form-select"}),
    )

    reference_type = forms.ChoiceField(
        label="Tipo de referencia",
        choices=[],
        required=False,
        widget=forms.Select(attrs={"class": "form-select"}),
    )

    date_from = forms.DateField(
        label="Desde",
        required=False,
        widget=forms.DateInput(
            attrs={
                "class": "form-control",
                "type": "date",
            }
        ),
    )

    date_to = forms.DateField(
        label="Hasta",
        required=False,
        widget=forms.DateInput(
            attrs={
                "class": "form-control",
                "type": "date",
            }
        ),
    )

    def __init__(self, *args, business=None, **kwargs):
        super().__init__(*args, **kwargs)

        self.business = business

        self.fields["movement_type"].choices = [
            ("", "Todos"),
            *StockMovement.MOVEMENT_TYPE_CHOICES,
        ]

        self.fields["reference_type"].choices = [
            ("", "Todas"),
            *StockMovement.REFERENCE_TYPE_CHOICES,
        ]

        if not self.business:
            return

        # En filtros dejamos ver histórico aunque la tienda esté inactiva.
        self.fields["store"].queryset = Store.objects.filter(
            business=self.business,
        ).order_by("name")

        # En filtros dejamos ver histórico aunque el producto esté inactivo.
        self.fields["product"].queryset = Product.objects.filter(
            business=self.business,
            is_service=False,
            track_stock=True,
        ).order_by("name")

    def clean(self):
        cleaned_data = super().clean()

        date_from = cleaned_data.get("date_from")
        date_to = cleaned_data.get("date_to")

        if date_from and date_to and date_from > date_to:
            self.add_error(
                "date_to",
                "La fecha hasta no puede ser anterior a la fecha desde.",
            )

        return cleaned_data


# ==========================================================
# Ajustes de stock
# ==========================================================


class StockAdjustmentFilterForm(forms.Form):
    """Formulario de filtros para ajustes de stock."""

    store = forms.ModelChoiceField(
        label="Tienda",
        queryset=Store.objects.none(),
        required=False,
        widget=forms.Select(attrs={"class": "form-select"}),
    )

    status = forms.ChoiceField(
        label="Estado",
        choices=[],
        required=False,
        widget=forms.Select(attrs={"class": "form-select"}),
    )

    reason = forms.ChoiceField(
        label="Motivo",
        choices=[],
        required=False,
        widget=forms.Select(attrs={"class": "form-select"}),
    )

    date_from = forms.DateField(
        label="Desde",
        required=False,
        widget=forms.DateInput(
            attrs={
                "class": "form-control",
                "type": "date",
            }
        ),
    )

    date_to = forms.DateField(
        label="Hasta",
        required=False,
        widget=forms.DateInput(
            attrs={
                "class": "form-control",
                "type": "date",
            }
        ),
    )

    def __init__(self, *args, business=None, **kwargs):
        super().__init__(*args, **kwargs)

        self.business = business

        self.fields["status"].choices = [
            ("", "Todos"),
            *StockAdjustment.STATUS_CHOICES,
        ]

        self.fields["reason"].choices = [
            ("", "Todos"),
            *StockAdjustment.REASON_CHOICES,
        ]

        if not self.business:
            return

        # En filtros dejamos ver histórico aunque la tienda esté inactiva.
        self.fields["store"].queryset = Store.objects.filter(
            business=self.business,
        ).order_by("name")

    def clean(self):
        cleaned_data = super().clean()

        date_from = cleaned_data.get("date_from")
        date_to = cleaned_data.get("date_to")

        if date_from and date_to and date_from > date_to:
            self.add_error(
                "date_to",
                "La fecha hasta no puede ser anterior a la fecha desde.",
            )

        return cleaned_data


class StockAdjustmentCreateForm(forms.ModelForm):
    """Formulario para crear cabecera de ajuste.

    IMPORTANTE:
    Crear un ajuste NO toca stock.
    Solo crea el documento en borrador.
    """

    class Meta:
        model = StockAdjustment
        fields = [
            "store",
            "reason",
            "notes",
        ]

        widgets = {
            "store": forms.Select(
                attrs={
                    "class": "form-select",
                }
            ),
            "reason": forms.Select(
                attrs={
                    "class": "form-select",
                }
            ),
            "notes": forms.Textarea(
                attrs={
                    "class": "form-control",
                    "rows": 3,
                    "placeholder": "Notas internas del ajuste.",
                }
            ),
        }

        help_texts = {
            "store": "Tienda donde se realiza el ajuste.",
            "reason": "Motivo principal del ajuste.",
            "notes": "Notas internas opcionales.",
        }

    def __init__(self, *args, business=None, user=None, **kwargs):
        super().__init__(*args, **kwargs)

        self.business = business
        self.user = user

        self.fields["store"].queryset = Store.objects.none()
        self.fields["notes"].required = False

        if not self.business:
            return

        self.instance.business = self.business

        if self.user and not self.instance.created_by_id:
            self.instance.created_by = self.user

        # En creación sí exigimos tienda activa.
        self.fields["store"].queryset = Store.objects.filter(
            business=self.business,
            is_active=True,
        ).order_by("name")

    def clean_store(self):
        store = self.cleaned_data.get("store")

        if store and self.business and store.business_id != self.business.id:
            raise forms.ValidationError("La tienda debe pertenecer al mismo negocio.")

        if store and not store.is_active:
            raise forms.ValidationError(
                "No puedes crear un ajuste en una tienda inactiva."
            )

        return store

    def clean_notes(self):
        notes = self.cleaned_data.get("notes")

        if notes:
            return notes.strip()

        return notes

    def save(self, commit=True):
        """Crea una cabecera de ajuste en borrador.

        Crear un ajuste NO toca stock.
        """

        adjustment = super().save(commit=False)

        if self.business:
            adjustment.business = self.business

        if self.user and not adjustment.created_by_id:
            adjustment.created_by = self.user

        adjustment.status = StockAdjustment.STATUS_DRAFT

        if commit:
            adjustment.save()

        return adjustment


class StockAdjustmentLineForm(forms.ModelForm):
    """Formulario para crear o editar líneas de ajuste.

    IMPORTANTE:
    El usuario solo informa:
    - inventory_item
    - counted_stock
    - notes

    No se pide:
    - product
    - system_stock
    - difference

    system_stock debe salir de inventory_item.current_stock.
    difference la calcula StockAdjustmentLine.clean().
    """

    adjustment = forms.ModelChoiceField(
        queryset=StockAdjustment.objects.none(),
        required=False,
        widget=forms.HiddenInput(),
    )

    system_stock = forms.DecimalField(
        required=False,
        widget=forms.HiddenInput(),
    )

    class Meta:
        model = StockAdjustmentLine
        fields = [
            "inventory_item",
            "counted_stock",
            "notes",
        ]

        widgets = {
            "inventory_item": forms.Select(
                attrs={
                    "class": "form-select",
                }
            ),
            "counted_stock": forms.NumberInput(
                attrs={
                    **_decimal_attrs(),
                    "placeholder": "Stock contado físicamente",
                }
            ),
            "notes": forms.TextInput(
                attrs={
                    "class": "form-control",
                    "placeholder": "Nota opcional de la línea.",
                }
            ),
        }

        help_texts = {
            "inventory_item": "Producto cuyo stock se está revisando.",
            "counted_stock": "Cantidad física real contada.",
            "notes": "Notas opcionales de la línea.",
        }

    def __init__(self, *args, business=None, adjustment=None, **kwargs):
        super().__init__(*args, **kwargs)

        self.business = business
        self.adjustment = adjustment

        self.fields["inventory_item"].queryset = InventoryItem.objects.none()
        self.fields["adjustment"].queryset = StockAdjustment.objects.none()
        self.fields["notes"].required = False

        if self.adjustment:
            self.instance.adjustment = self.adjustment

        if not self.business or not self.adjustment:
            return

        self.initial["adjustment"] = self.adjustment.pk
        self.fields["adjustment"].queryset = StockAdjustment.objects.filter(
            pk=self.adjustment.pk
        )

        self.fields["inventory_item"].queryset = (
            InventoryItem.objects.filter(
                business=self.business,
                store=self.adjustment.store,
                is_active=True,
                product__is_service=False,
                product__track_stock=True,
                product__is_active=True,
            )
            .select_related("product", "store")
            .order_by("product__name")
        )

    def clean_inventory_item(self):
        inventory_item = self.cleaned_data.get("inventory_item")

        if not inventory_item:
            return inventory_item

        if self.business and inventory_item.business_id != self.business.id:
            raise forms.ValidationError(
                "El stock afectado debe pertenecer al mismo negocio."
            )

        if self.adjustment and inventory_item.store_id != self.adjustment.store_id:
            raise forms.ValidationError(
                "El stock afectado debe pertenecer a la misma tienda que el ajuste."
            )

        if not inventory_item.is_active:
            raise forms.ValidationError(
                "No puedes ajustar una ficha de inventario inactiva."
            )

        if inventory_item.product.is_service:
            raise forms.ValidationError("No se puede ajustar stock de un servicio.")

        if not inventory_item.product.track_stock:
            raise forms.ValidationError(
                "No se puede ajustar un producto que no controla stock."
            )

        return inventory_item

    def clean_counted_stock(self):
        counted_stock = self.cleaned_data.get("counted_stock")

        if counted_stock is None:
            raise forms.ValidationError("Debes indicar el stock contado.")

        if counted_stock < Decimal("0.000"):
            raise forms.ValidationError("El stock contado no puede ser negativo.")

        return counted_stock

    def clean_notes(self):
        notes = self.cleaned_data.get("notes")

        if notes:
            return notes.strip()

        return notes

    def clean(self):
        cleaned_data = super().clean()

        inventory_item = cleaned_data.get("inventory_item")

        if self.adjustment:
            self.instance.adjustment = self.adjustment

        if inventory_item:
            self.instance.product = inventory_item.product
            self.instance.system_stock = inventory_item.current_stock
            cleaned_data["system_stock"] = inventory_item.current_stock

        if not self.adjustment:
            raise forms.ValidationError("No se ha indicado el ajuste de stock.")

        if self.business and self.adjustment.business_id != self.business.id:
            raise forms.ValidationError("El ajuste debe pertenecer al mismo negocio.")

        if not self.adjustment.is_draft:
            raise forms.ValidationError(
                "Solo se pueden modificar líneas de ajustes en borrador."
            )

        if self.adjustment and inventory_item:
            duplicate_queryset = StockAdjustmentLine.objects.filter(
                adjustment=self.adjustment,
                inventory_item=inventory_item,
            )

            if self.instance and self.instance.pk:
                duplicate_queryset = duplicate_queryset.exclude(pk=self.instance.pk)

            if duplicate_queryset.exists():
                self.add_error(
                    "inventory_item",
                    "Este producto ya tiene una línea en este ajuste.",
                )

        return cleaned_data

    def save(self, commit=True):
        """Asigna campos que el usuario no debe tocar.

        OJO:
        Esto NO modifica stock.
        Solo prepara la línea del ajuste.

        El usuario no introduce:
        - product
        - system_stock
        - difference

        product sale de inventory_item.product.
        system_stock sale de inventory_item.current_stock.
        difference la calcula el modelo.
        """

        line = super().save(commit=False)

        if self.adjustment:
            line.adjustment = self.adjustment

        if line.inventory_item:
            line.product = line.inventory_item.product
            line.system_stock = line.inventory_item.current_stock

        if commit:
            line.save()

        return line


class StockAdjustmentConfirmForm(forms.Form):
    """Formulario simple para confirmar un ajuste.

    Este form solo valida la intención del usuario.
    La confirmación real debe hacerla el service:

    confirm_stock_adjustment(adjustment=adjustment, user=request.user)
    """

    confirm = forms.BooleanField(
        label="Confirmo que quiero aplicar este ajuste de stock",
        required=True,
        widget=forms.CheckboxInput(
            attrs={
                "class": "form-check-input",
            }
        ),
    )

    def __init__(self, *args, adjustment=None, **kwargs):
        super().__init__(*args, **kwargs)

        self.adjustment = adjustment

    def clean(self):
        cleaned_data = super().clean()

        if not self.adjustment:
            raise forms.ValidationError("No se ha indicado el ajuste a confirmar.")

        if not self.adjustment.is_draft:
            raise forms.ValidationError("Solo se pueden confirmar ajustes en borrador.")

        if not self.adjustment.lines.exists():
            raise forms.ValidationError("No puedes confirmar un ajuste sin líneas.")

        return cleaned_data
