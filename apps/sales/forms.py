"""Formularios del módulo sales.

Reglas:
- Los formularios validan entrada HTTP.
- Los services repiten las validaciones críticas.
- Ningún formulario calcula o persiste totales definitivos.
"""

from decimal import Decimal

from django import forms
from django.core.exceptions import ObjectDoesNotExist, ValidationError

from apps.business_config.models import POSSettings
from apps.cash_register.models import CashRegister, CashSession
from apps.catalog.models import Product
from apps.customers.models import Customer
from apps.sales.models import (
    PaymentStatusChoices,
    RequestedDocumentTypeChoices,
    Sale,
    SaleLine,
    SaleReturnStatusChoices,
    SaleStatusChoices,
)
from apps.users.models import CustomUser


EMPTY_CHOICE = [("", "Todos")]


def _get_pos_settings(business):
    """Obtiene la configuración TPV sin ocultar una configuración ausente."""
    if business is None:
        return None

    try:
        return business.pos_settings
    except ObjectDoesNotExist:
        return POSSettings.objects.filter(
            business=business,
        ).first()


# ==========================================================
# Filtros de ventas
# ==========================================================


class SaleFilterForm(forms.Form):
    """Formulario para filtrar el listado de ventas."""

    query = forms.CharField(
        label="Buscar",
        required=False,
        max_length=180,
        widget=forms.TextInput(
            attrs={"placeholder": ("Número, cliente, tienda o usuario")}
        ),
    )

    customer = forms.ModelChoiceField(
        label="Cliente",
        required=False,
        queryset=Customer.objects.none(),
    )

    opened_by = forms.ModelChoiceField(
        label="Abierta por",
        required=False,
        queryset=CustomUser.objects.none(),
    )

    status = forms.ChoiceField(
        label="Estado",
        required=False,
        choices=(EMPTY_CHOICE + list(SaleStatusChoices.choices)),
    )

    payment_status = forms.ChoiceField(
        label="Estado del pago",
        required=False,
        choices=(EMPTY_CHOICE + list(PaymentStatusChoices.choices)),
    )

    document_type_requested = forms.ChoiceField(
        label="Documento solicitado",
        required=False,
        choices=(EMPTY_CHOICE + list(RequestedDocumentTypeChoices.choices)),
    )

    date_from = forms.DateField(
        label="Desde",
        required=False,
        widget=forms.DateInput(
            attrs={"type": "date"},
        ),
    )

    date_to = forms.DateField(
        label="Hasta",
        required=False,
        widget=forms.DateInput(
            attrs={"type": "date"},
        ),
    )

    def __init__(
        self,
        *args,
        business,
        store=None,
        **kwargs,
    ):
        super().__init__(*args, **kwargs)

        self.business = business
        self.store = store

        self.fields["customer"].queryset = Customer.objects.filter(
            business=business,
        ).order_by(
            "name",
            "pk",
        )

        self.fields["opened_by"].queryset = CustomUser.objects.filter(
            business=business,
            is_active=True,
        ).order_by(
            "first_name",
            "last_name",
            "email",
        )

    def clean(self):
        cleaned_data = super().clean()

        date_from = cleaned_data.get("date_from")
        date_to = cleaned_data.get("date_to")

        if date_from and date_to and date_from > date_to:
            raise ValidationError(
                "La fecha inicial no puede ser posterior a la fecha final."
            )

        return cleaned_data


# ==========================================================
# Apertura de ventas
# ==========================================================


class SaleOpenForm(forms.Form):
    """Formulario para abrir una venta."""

    customer = forms.ModelChoiceField(
        label="Cliente",
        required=False,
        queryset=Customer.objects.none(),
    )

    cash_register = forms.ModelChoiceField(
        label="Caja",
        required=False,
        queryset=CashRegister.objects.none(),
    )

    cash_session = forms.ModelChoiceField(
        label="Sesión de caja",
        required=False,
        queryset=CashSession.objects.none(),
    )

    document_type_requested = forms.ChoiceField(
        label="Documento solicitado",
        choices=(RequestedDocumentTypeChoices.choices),
        initial=(RequestedDocumentTypeChoices.TICKET),
    )

    def __init__(
        self,
        *args,
        business,
        store,
        user,
        **kwargs,
    ):
        super().__init__(*args, **kwargs)

        self.business = business
        self.store = store
        self.user = user
        self.pos_settings = _get_pos_settings(
            business,
        )

        self.fields["customer"].queryset = Customer.objects.filter(
            business=business,
            is_active=True,
        ).order_by(
            "name",
            "pk",
        )

        register_queryset = CashRegister.objects.filter(
            business=business,
            store=store,
            is_active=True,
        ).order_by("pk")

        register_id = self.data.get("cash_register") if self.is_bound else None
        if register_id is None:
            initial_register = self.initial.get("cash_register")
            register_id = getattr(initial_register, "pk", initial_register)

        session_queryset = CashSession.objects.filter(
            business=business,
            store=store,
            status=CashSession.Status.OPEN,
            closed_at__isnull=True,
        )
        if register_id:
            session_queryset = session_queryset.filter(cash_register_id=register_id)
        else:
            session_queryset = session_queryset.none()
        session_queryset = session_queryset.order_by("pk")

        self.fields["cash_register"].queryset = register_queryset

        self.fields["cash_session"].queryset = session_queryset

        if self.pos_settings and self.pos_settings.require_open_cash_register:
            self.fields["cash_register"].required = True

            self.fields["cash_session"].required = True

    def clean(self):
        cleaned_data = super().clean()

        customer = cleaned_data.get(
            "customer",
        )

        document_type = cleaned_data.get(
            "document_type_requested",
        )

        cash_register = cleaned_data.get(
            "cash_register",
        )

        cash_session = cleaned_data.get(
            "cash_session",
        )

        if document_type == RequestedDocumentTypeChoices.INVOICE and customer is None:
            self.add_error(
                "customer",
                ("Debes seleccionar un cliente cuando se solicita factura."),
            )

        if bool(cash_register) != bool(cash_session):
            message = "La caja y la sesión de caja deben indicarse conjuntamente."

            if cash_register is None:
                self.add_error(
                    "cash_register",
                    message,
                )

            if cash_session is None:
                self.add_error(
                    "cash_session",
                    message,
                )

        if (
            cash_session is not None
            and cash_register is not None
            and hasattr(
                cash_session,
                "cash_register_id",
            )
            and cash_session.cash_register_id != cash_register.pk
        ):
            self.add_error(
                "cash_session",
                ("La sesión seleccionada no pertenece a la caja indicada."),
            )

        return cleaned_data


# ==========================================================
# Actualización de cabecera
# ==========================================================


class SaleHeaderUpdateForm(forms.Form):
    """Formulario para modificar la cabecera editable."""

    customer = forms.ModelChoiceField(
        label="Cliente",
        required=False,
        queryset=Customer.objects.none(),
    )

    document_type_requested = forms.ChoiceField(
        label="Documento solicitado",
        choices=(RequestedDocumentTypeChoices.choices),
    )

    def __init__(
        self,
        *args,
        business,
        store,
        sale,
        **kwargs,
    ):
        super().__init__(*args, **kwargs)

        self.business = business
        self.store = store
        self.sale = sale

        self.fields["customer"].queryset = Customer.objects.filter(
            business=business,
            is_active=True,
        ).order_by(
            "name",
            "pk",
        )

    def clean(self):
        cleaned_data = super().clean()

        customer = cleaned_data.get(
            "customer",
        )

        document_type = cleaned_data.get(
            "document_type_requested",
        )

        if document_type == RequestedDocumentTypeChoices.INVOICE and customer is None:
            self.add_error(
                "customer",
                ("Debes seleccionar un cliente cuando se solicita factura."),
            )

        return cleaned_data


# ==========================================================
# Líneas de venta
# ==========================================================


class BaseSaleLineForm(forms.Form):
    """Formulario base para crear o editar líneas."""

    quantity = forms.DecimalField(
        label="Cantidad",
        max_digits=14,
        decimal_places=3,
        min_value=Decimal("0.001"),
    )

    unit_base_price = forms.DecimalField(
        label="Precio unitario sin IVA",
        required=False,
        max_digits=12,
        decimal_places=2,
        min_value=Decimal("0.00"),
        help_text=("Déjalo vacío para utilizar el precio actual del producto."),
    )

    discount_amount = forms.DecimalField(
        label="Descuento total de la línea",
        required=False,
        max_digits=14,
        decimal_places=2,
        min_value=Decimal("0.00"),
        initial=Decimal("0.00"),
    )

    def __init__(
        self,
        *args,
        business,
        store,
        sale,
        user,
        **kwargs,
    ):
        super().__init__(*args, **kwargs)

        self.business = business
        self.store = store
        self.sale = sale
        self.user = user
        self.pos_settings = _get_pos_settings(
            business,
        )

        if self.pos_settings:
            if not self.pos_settings.allow_manual_price:
                self.fields["unit_base_price"].disabled = True

                self.fields[
                    "unit_base_price"
                ].help_text = "El negocio no permite modificar manualmente el precio."

            if not self.pos_settings.allow_manual_discounts:
                self.fields["discount_amount"].disabled = True

                self.fields["discount_amount"].initial = Decimal("0.00")

                self.fields[
                    "discount_amount"
                ].help_text = "El negocio no permite aplicar descuentos manuales."

    def get_reference_price(
        self,
        cleaned_data,
    ):
        """Debe devolver el precio de referencia."""
        raise NotImplementedError

    def clean(self):
        cleaned_data = super().clean()

        quantity = cleaned_data.get(
            "quantity",
        )

        unit_base_price = cleaned_data.get(
            "unit_base_price",
        )

        discount_amount = cleaned_data.get("discount_amount") or Decimal("0.00")

        if quantity is None:
            return cleaned_data

        reference_price = self.get_reference_price(
            cleaned_data,
        )

        if unit_base_price is None:
            effective_price = reference_price
        else:
            effective_price = unit_base_price

        if effective_price is None:
            return cleaned_data

        gross_amount = effective_price * quantity

        if discount_amount > gross_amount:
            self.add_error(
                "discount_amount",
                ("El descuento no puede superar el importe bruto de la línea."),
            )

            return cleaned_data

        if self.pos_settings:
            if (
                unit_base_price is not None
                and unit_base_price != reference_price
                and not self.pos_settings.allow_manual_price
            ):
                self.add_error(
                    "unit_base_price",
                    ("La configuración del negocio no permite precios manuales."),
                )

            if (
                discount_amount > Decimal("0.00")
                and not self.pos_settings.allow_manual_discounts
            ):
                self.add_error(
                    "discount_amount",
                    ("La configuración del negocio no permite descuentos manuales."),
                )

            if gross_amount > Decimal("0.00"):
                discount_percent = (discount_amount / gross_amount) * Decimal("100.00")

                if discount_percent > self.pos_settings.max_manual_discount_percent:
                    self.add_error(
                        "discount_amount",
                        (
                            "El descuento supera "
                            "el máximo permitido "
                            f"({self.pos_settings.max_manual_discount_percent} %)."
                        ),
                    )

        cleaned_data["discount_amount"] = discount_amount

        return cleaned_data


class SaleLineCreateForm(BaseSaleLineForm):
    """Formulario para añadir una línea."""

    product = forms.ModelChoiceField(
        label="Producto o servicio",
        queryset=Product.objects.none(),
    )

    field_order = [
        "product",
        "quantity",
        "unit_base_price",
        "discount_amount",
    ]

    def __init__(
        self,
        *args,
        business,
        store,
        sale,
        user,
        **kwargs,
    ):
        super().__init__(
            *args,
            business=business,
            store=store,
            sale=sale,
            user=user,
            **kwargs,
        )

        self.fields["product"].queryset = (
            Product.objects.filter(
                business=business,
                is_active=True,
            )
            .select_related(
                "tax",
                "category",
            )
            .order_by(
                "sort_order",
                "name",
                "pk",
            )
        )

    def get_reference_price(
        self,
        cleaned_data,
    ):
        product = cleaned_data.get(
            "product",
        )

        if product is None:
            return None

        return product.base_price


class SaleLineUpdateForm(BaseSaleLineForm):
    """Formulario para actualizar una línea."""

    def __init__(
        self,
        *args,
        business,
        store,
        sale,
        line,
        user,
        **kwargs,
    ):
        self.line = line

        super().__init__(
            *args,
            business=business,
            store=store,
            sale=sale,
            user=user,
            **kwargs,
        )

        self.fields[
            "unit_base_price"
        ].help_text = "Precio histórico aplicado a esta línea."

    def get_reference_price(
        self,
        cleaned_data,
    ):
        return self.line.unit_base_price


# ==========================================================
# Cancelación de venta
# ==========================================================


class SaleCancelForm(forms.Form):
    """Formulario de confirmación de cancelación."""

    pin = forms.CharField(
        label="PIN de seguridad",
        required=False,
        min_length=4,
        max_length=6,
        widget=forms.PasswordInput(
            render_value=False,
        ),
    )

    def __init__(
        self,
        *args,
        sale,
        user,
        **kwargs,
    ):
        super().__init__(*args, **kwargs)

        self.sale = sale
        self.user = user
        self.pos_settings = _get_pos_settings(
            sale.business,
        )

        if self.pos_settings and self.pos_settings.require_pin_for_sensitive_actions:
            self.fields["pin"].required = True

    def clean_pin(self):
        pin = self.cleaned_data.get(
            "pin",
        )

        if (
            self.pos_settings
            and self.pos_settings.require_pin_for_sensitive_actions
            and not self.user.check_pin(pin)
        ):
            raise ValidationError("El PIN indicado no es válido.")

        return pin


# ==========================================================
# Filtros de devoluciones
# ==========================================================


class SaleReturnFilterForm(forms.Form):
    """Formulario de filtros para devoluciones."""

    query = forms.CharField(
        label="Buscar",
        required=False,
        max_length=180,
        widget=forms.TextInput(
            attrs={"placeholder": ("Número, venta, motivo, cliente o usuario")}
        ),
    )

    original_sale = forms.ModelChoiceField(
        label="Venta original",
        required=False,
        queryset=Sale.objects.none(),
    )

    created_by = forms.ModelChoiceField(
        label="Creada por",
        required=False,
        queryset=CustomUser.objects.none(),
    )

    status = forms.ChoiceField(
        label="Estado",
        required=False,
        choices=(EMPTY_CHOICE + list(SaleReturnStatusChoices.choices)),
    )

    date_from = forms.DateField(
        label="Desde",
        required=False,
        widget=forms.DateInput(
            attrs={"type": "date"},
        ),
    )

    date_to = forms.DateField(
        label="Hasta",
        required=False,
        widget=forms.DateInput(
            attrs={"type": "date"},
        ),
    )

    def __init__(
        self,
        *args,
        business,
        store=None,
        **kwargs,
    ):
        super().__init__(*args, **kwargs)

        self.business = business
        self.store = store

        sales_queryset = Sale.objects.filter(
            business=business,
        )

        if store is not None:
            sales_queryset = sales_queryset.filter(
                store=store,
            )

        self.fields["original_sale"].queryset = sales_queryset.order_by(
            "-created_at",
            "-pk",
        )

        self.fields["created_by"].queryset = CustomUser.objects.filter(
            business=business,
            is_active=True,
        ).order_by(
            "first_name",
            "last_name",
            "email",
        )

    def clean(self):
        cleaned_data = super().clean()

        date_from = cleaned_data.get(
            "date_from",
        )

        date_to = cleaned_data.get(
            "date_to",
        )

        if date_from and date_to and date_from > date_to:
            raise ValidationError(
                "La fecha inicial no puede ser posterior a la fecha final."
            )

        return cleaned_data


# ==========================================================
# Creación de devoluciones
# ==========================================================


class SaleReturnCreateForm(forms.Form):
    """Formulario para abrir una devolución."""

    reason = forms.CharField(
        label="Motivo de la devolución",
        max_length=1000,
        widget=forms.Textarea(
            attrs={"rows": 4},
        ),
    )

    def __init__(
        self,
        *args,
        business,
        sale,
        user,
        **kwargs,
    ):
        super().__init__(*args, **kwargs)

        self.business = business
        self.sale = sale
        self.user = user

    def clean_reason(self):
        reason = (self.cleaned_data.get("reason") or "").strip()

        if not reason:
            raise ValidationError("Debes indicar el motivo de la devolución.")

        return reason


# ==========================================================
# Líneas de devolución
# ==========================================================


class SaleReturnLineCreateForm(forms.Form):
    """Formulario para añadir una línea devuelta."""

    original_line = forms.ModelChoiceField(
        label="Línea original",
        queryset=SaleLine.objects.none(),
    )

    quantity = forms.DecimalField(
        label="Cantidad a devolver",
        max_digits=14,
        decimal_places=3,
        min_value=Decimal("0.001"),
    )

    def __init__(
        self,
        *args,
        business,
        return_doc,
        returnable_lines,
        **kwargs,
    ):
        super().__init__(*args, **kwargs)

        self.business = business
        self.return_doc = return_doc

        self.fields["original_line"].queryset = returnable_lines

    def clean(self):
        cleaned_data = super().clean()

        original_line = cleaned_data.get(
            "original_line",
        )

        quantity = cleaned_data.get(
            "quantity",
        )

        if original_line is None or quantity is None:
            return cleaned_data

        returnable_quantity = getattr(
            original_line,
            "returnable_quantity",
            original_line.quantity,
        )

        if quantity > returnable_quantity:
            self.add_error(
                "quantity",
                (
                    "La cantidad supera lo que "
                    "todavía puede devolverse "
                    f"({returnable_quantity})."
                ),
            )

        return cleaned_data


class SaleReturnLineUpdateForm(forms.Form):
    """Formulario para actualizar una línea devuelta."""

    quantity = forms.DecimalField(
        label="Cantidad a devolver",
        max_digits=14,
        decimal_places=3,
        min_value=Decimal("0.001"),
    )

    def __init__(
        self,
        *args,
        business,
        return_doc,
        line,
        **kwargs,
    ):
        super().__init__(*args, **kwargs)

        self.business = business
        self.return_doc = return_doc
        self.line = line

    def clean_quantity(self):
        quantity = self.cleaned_data["quantity"]

        if quantity > self.line.original_line.quantity:
            raise ValidationError("La cantidad no puede superar la cantidad vendida.")

        return quantity


# ==========================================================
# Confirmación de devoluciones
# ==========================================================


class SaleReturnCompleteForm(forms.Form):
    """Formulario para completar una devolución."""

    pin = forms.CharField(
        label="PIN de seguridad",
        required=False,
        min_length=4,
        max_length=6,
        widget=forms.PasswordInput(
            render_value=False,
        ),
    )

    def __init__(
        self,
        *args,
        return_doc,
        user,
        **kwargs,
    ):
        super().__init__(*args, **kwargs)

        self.return_doc = return_doc
        self.user = user
        self.pos_settings = _get_pos_settings(
            return_doc.business,
        )

        if self.pos_settings and self.pos_settings.require_pin_for_sensitive_actions:
            self.fields["pin"].required = True

    def clean_pin(self):
        pin = self.cleaned_data.get(
            "pin",
        )

        if (
            self.pos_settings
            and self.pos_settings.require_pin_for_sensitive_actions
            and not self.user.check_pin(pin)
        ):
            raise ValidationError("El PIN indicado no es válido.")

        return pin


class SaleReturnCancelForm(SaleReturnCompleteForm):
    """
    Cancelar una devolución utiliza
    la misma protección mediante PIN.
    """
