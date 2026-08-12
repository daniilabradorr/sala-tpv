"""Servicios de negocio del módulo customers."""

from decimal import Decimal, InvalidOperation

from django.core.exceptions import ValidationError
from django.db import transaction

from apps.customers.models import (
    Customer,
    CustomerAccount,
    CustomerAccountEntry,
    EntryTypeChoices,
)


def _to_decimal(value, *, field_name="importe"):
    """Convierte un valor a Decimal sin usar float."""
    try:
        decimal_value = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValidationError(f"El {field_name} debe ser un número válido.") from exc

    if not decimal_value.is_finite():
        raise ValidationError(f"El {field_name} debe ser un número finito.")

    return decimal_value


def _validate_business(business):
    """Valida que exista un negocio activo."""
    if business is None:
        raise ValidationError("No se ha indicado el negocio.")

    if not business.is_active:
        raise ValidationError(
            "No se pueden realizar operaciones en un negocio inactivo."
        )


def _validate_user_business(*, user, business):
    """Evita asignar usuarios de otro negocio a un movimiento."""
    if user is None:
        return

    if user.is_superuser:
        return

    if user.business_id != business.pk:
        raise ValidationError("El usuario debe pertenecer al mismo negocio.")


class CustomerService:
    """Casos de uso relacionados con la ficha del cliente."""

    CUSTOMER_EDITABLE_FIELDS = {
        "customer_type",
        "name",
        "legal_name",
        "tax_identifier",
        "country_code",
        "foreign_id_type",
        "foreign_id",
        "email",
        "phone",
        "address_line_1",
        "postal_code",
        "city",
        "province",
    }

    @classmethod
    def _extract_customer_data(cls, customer_data):
        """Acepta únicamente campos editables de Customer."""
        customer_data = customer_data or {}
        return {
            field: customer_data[field]
            for field in cls.CUSTOMER_EDITABLE_FIELDS
            if field in customer_data
        }

    @classmethod
    @transaction.atomic
    def create_customer(
        cls,
        *,
        business,
        customer_data,
        credit_limit=Decimal("0.00"),
        is_blocked=False,
    ):
        """Crea un cliente y su cuenta corriente en una sola transacción."""
        _validate_business(business)
        credit_limit = _to_decimal(credit_limit, field_name="límite de crédito")
        if credit_limit < Decimal("0.00"):
            raise ValidationError("El límite de crédito no puede ser negativo.")

        customer = Customer(
            business=business,
            **cls._extract_customer_data(customer_data),
        )
        customer.save()

        account = CustomerAccount(
            business=business,
            customer=customer,
            balance=Decimal("0.00"),
            credit_limit=credit_limit,
            is_blocked=is_blocked,
        )
        account.save()

        return customer, account

    @classmethod
    @transaction.atomic
    def update_customer(cls, *, business, customer, customer_data):
        """Actualiza los datos editables de un cliente."""
        _validate_business(business)
        try:
            locked_customer = Customer.objects.select_for_update().get(
                pk=customer.pk,
                business=business,
            )
        except Customer.DoesNotExist as exc:
            raise ValidationError(
                "El cliente no pertenece al negocio indicado."
            ) from exc

        update_data = cls._extract_customer_data(customer_data)
        for field, value in update_data.items():
            setattr(locked_customer, field, value)
        locked_customer.save()
        return locked_customer

    @classmethod
    @transaction.atomic
    def deactivate_customer(cls, *, business, customer):
        """Desactiva un cliente sin eliminar su histórico."""
        _validate_business(business)
        try:
            locked_customer = Customer.objects.select_for_update().get(
                pk=customer.pk,
                business=business,
            )
        except Customer.DoesNotExist as exc:
            raise ValidationError(
                "El cliente no pertenece al negocio indicado."
            ) from exc

        if not locked_customer.is_active:
            return locked_customer

        locked_customer.is_active = False
        locked_customer.save(update_fields=["is_active", "updated_at"])
        return locked_customer

    @classmethod
    @transaction.atomic
    def reactivate_customer(cls, *, business, customer):
        """Reactiva un cliente desactivado."""
        _validate_business(business)
        try:
            locked_customer = Customer.objects.select_for_update().get(
                pk=customer.pk,
                business=business,
            )
        except Customer.DoesNotExist as exc:
            raise ValidationError(
                "El cliente no pertenece al negocio indicado."
            ) from exc

        if locked_customer.is_active:
            return locked_customer

        locked_customer.is_active = True
        locked_customer.save(update_fields=["is_active", "updated_at"])
        return locked_customer


class CustomerAccountService:
    """Casos de uso relacionados con la cuenta del cliente."""

    @staticmethod
    def _positive_amount(amount):
        """Valida que el importe introducido sea positivo."""
        amount = _to_decimal(amount)
        if amount <= Decimal("0.00"):
            raise ValidationError("El importe debe ser mayor que cero.")
        return amount

    @staticmethod
    def _get_locked_account(*, business, account):
        """Obtiene y bloquea la cuenta dentro de la transacción actual."""
        try:
            return (
                CustomerAccount.objects.select_for_update()
                .select_related("business", "customer")
                .get(pk=account.pk, business=business)
            )
        except CustomerAccount.DoesNotExist as exc:
            raise ValidationError(
                "La cuenta no pertenece al negocio indicado."
            ) from exc

    @classmethod
    @transaction.atomic
    def update_account_settings(cls, *, business, account, credit_limit, is_blocked):
        """Actualiza límite de crédito y bloqueo sin modificar balance."""
        _validate_business(business)
        credit_limit = _to_decimal(credit_limit, field_name="límite de crédito")
        if credit_limit < Decimal("0.00"):
            raise ValidationError("El límite de crédito no puede ser negativo.")

        locked_account = cls._get_locked_account(business=business, account=account)
        locked_account.credit_limit = credit_limit
        locked_account.is_blocked = bool(is_blocked)
        locked_account.save(update_fields=["credit_limit", "is_blocked", "updated_at"])
        return locked_account

    @classmethod
    @transaction.atomic
    def _apply_entry(
        cls,
        *,
        business,
        account,
        entry_type,
        amount_delta,
        user=None,
        notes="",
        sale=None,
        payment=None,
        check_customer_active=False,
        check_account_blocked=False,
        check_credit_limit=False,
    ):
        """Aplica una variación al saldo y crea su movimiento."""
        _validate_business(business)
        _validate_user_business(user=user, business=business)
        amount_delta = _to_decimal(amount_delta)
        if amount_delta == Decimal("0.00"):
            raise ValidationError("El importe del movimiento no puede ser cero.")

        locked_account = cls._get_locked_account(business=business, account=account)

        if sale is not None:
            if sale.business_id != business.pk:
                raise ValidationError("La venta debe pertenecer al mismo negocio.")
            if sale.customer_id != locked_account.customer_id:
                raise ValidationError("La venta no pertenece al cliente de la cuenta.")
        if payment is not None:
            if payment.business_id != business.pk:
                raise ValidationError("El pago debe pertenecer al mismo negocio.")
            if sale is not None and payment.sale_id != sale.pk:
                raise ValidationError("El pago no corresponde a la venta indicada.")

        if check_customer_active and not locked_account.customer.is_active:
            raise ValidationError(
                "No se pueden generar nuevos cargos para un cliente inactivo."
            )
        if check_account_blocked and locked_account.is_blocked:
            raise ValidationError(
                "La cuenta del cliente está bloqueada para nuevas ventas."
            )

        balance_before = locked_account.balance
        balance_after = balance_before + amount_delta

        if check_credit_limit and balance_after > locked_account.credit_limit:
            raise ValidationError(
                "El movimiento supera el límite de crédito del cliente."
            )

        locked_account.balance = balance_after
        locked_account.save(update_fields=["balance", "updated_at"])

        entry = CustomerAccountEntry(
            business=business,
            account=locked_account,
            entry_type=entry_type,
            amount=amount_delta,
            balance_after=balance_after,
            created_by=user,
            notes=(notes or "").strip(),
            sale=sale,
            payment=payment,
        )
        entry.save()
        return locked_account, entry

    @classmethod
    @transaction.atomic
    def create_charge(
        cls, *, business, account, amount, user=None, notes="", sale=None
    ):
        """Registra una deuda nueva del cliente."""
        amount = cls._positive_amount(amount)
        if sale is not None:
            locked_account = cls._get_locked_account(business=business, account=account)
            existing = CustomerAccountEntry.objects.filter(
                business=business,
                account=locked_account,
                sale=sale,
                entry_type=EntryTypeChoices.CHARGE,
            ).first()
            if existing:
                if existing.amount != amount:
                    raise ValidationError(
                        "La venta ya tiene un cargo con un importe diferente."
                    )
                return locked_account, existing
        return cls._apply_entry(
            business=business,
            account=account,
            entry_type=EntryTypeChoices.CHARGE,
            amount_delta=amount,
            user=user,
            notes=notes,
            sale=sale,
            check_customer_active=True,
            check_account_blocked=True,
            check_credit_limit=True,
        )

    @classmethod
    def register_payment(
        cls, *, business, account, amount, user=None, notes="", sale=None, payment=None
    ):
        """Registra un pago recibido del cliente."""
        amount = cls._positive_amount(amount)
        return cls._apply_entry(
            business=business,
            account=account,
            entry_type=EntryTypeChoices.PAYMENT,
            amount_delta=-amount,
            user=user,
            notes=notes,
            sale=sale,
            payment=payment,
        )

    @classmethod
    def register_refund(
        cls, *, business, account, amount, user=None, notes="", sale=None, payment=None
    ):
        """Registra un reembolso a favor del cliente."""
        amount = cls._positive_amount(amount)
        return cls._apply_entry(
            business=business,
            account=account,
            entry_type=EntryTypeChoices.REFUND,
            amount_delta=-amount,
            user=user,
            notes=notes,
            sale=sale,
            payment=payment,
        )

    @classmethod
    def create_adjustment(cls, *, business, account, amount_delta, user=None, notes):
        """Registra una corrección manual del saldo."""
        amount_delta = _to_decimal(amount_delta, field_name="importe del ajuste")
        notes = (notes or "").strip()
        if amount_delta == Decimal("0.00"):
            raise ValidationError("El importe del ajuste no puede ser cero.")
        if not notes:
            raise ValidationError("Debes indicar el motivo del ajuste.")
        return cls._apply_entry(
            business=business,
            account=account,
            entry_type=EntryTypeChoices.ADJUSTMENT,
            amount_delta=amount_delta,
            user=user,
            notes=notes,
        )
