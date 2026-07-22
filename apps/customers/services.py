from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction

from apps.customers.models import (
    Customer,
    CustomerAccount,
    CustomerAccountEntry,
    CustomerAccountEntryTypeChoices,
)


def _to_decimal(value):
    return value if isinstance(value, Decimal) else Decimal(str(value))


def _validate_business(business):
    if business is None:
        raise ValidationError("No se ha indicado el negocio.")
    if not business.is_active:
        raise ValidationError("No se pueden operar clientes de un negocio inactivo.")


def _validate_user_business(*, user, business):
    if user is None:
        return
    if user.is_superuser:
        return
    if user.business_id != business.pk:
        raise ValidationError("El usuario debe pertenecer al mismo negocio.")


class CustomerService:
    @staticmethod
    @transaction.atomic
    def create_customer(
        *, business, data, credit_limit=Decimal("0.00"), is_blocked=False
    ):
        _validate_business(business)
        customer = Customer(business=business, **data)
        customer.save()
        CustomerAccount.objects.create(
            business=business,
            customer=customer,
            balance=Decimal("0.00"),
            credit_limit=credit_limit,
            is_blocked=is_blocked,
        )
        return customer

    @staticmethod
    @transaction.atomic
    def update_customer(*, business, customer, data):
        _validate_business(business)
        customer = Customer.objects.select_for_update().get(
            pk=customer.pk, business=business
        )
        for field in [
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
        ]:
            if field in data:
                setattr(customer, field, data[field])
        customer.save()
        return customer

    @staticmethod
    @transaction.atomic
    def deactivate_customer(*, business, customer):
        _validate_business(business)
        customer = Customer.objects.select_for_update().get(
            pk=customer.pk, business=business
        )
        if customer.is_active:
            customer.is_active = False
            customer.save(update_fields=["is_active", "updated_at"])
        return customer

    @staticmethod
    @transaction.atomic
    def reactivate_customer(*, business, customer):
        _validate_business(business)
        customer = Customer.objects.select_for_update().get(
            pk=customer.pk, business=business
        )
        if not customer.is_active:
            customer.is_active = True
            customer.save(update_fields=["is_active", "updated_at"])
        return customer


class CustomerAccountService:
    @staticmethod
    @transaction.atomic
    def update_account_settings(*, business, account, credit_limit, is_blocked):
        _validate_business(business)
        credit_limit = _to_decimal(credit_limit)
        if credit_limit < Decimal("0.00"):
            raise ValidationError(
                {"credit_limit": "El límite de crédito no puede ser negativo."}
            )
        account = CustomerAccount.objects.select_for_update().get(
            pk=account.pk, business=business
        )
        account.credit_limit = credit_limit
        account.is_blocked = bool(is_blocked)
        account.save(update_fields=["credit_limit", "is_blocked", "updated_at"])
        return account

    @staticmethod
    def create_charge(*, business, account, amount, user=None, notes=""):
        return CustomerAccountService._apply_entry(
            business=business,
            account=account,
            entry_type=CustomerAccountEntryTypeChoices.CHARGE,
            amount=abs(_to_decimal(amount)),
            user=user,
            notes=notes,
        )

    @staticmethod
    def register_payment(*, business, account, amount, user=None, notes=""):
        return CustomerAccountService._apply_entry(
            business=business,
            account=account,
            entry_type=CustomerAccountEntryTypeChoices.PAYMENT,
            amount=-abs(_to_decimal(amount)),
            user=user,
            notes=notes,
        )

    @staticmethod
    def register_refund(*, business, account, amount, user=None, notes=""):
        return CustomerAccountService._apply_entry(
            business=business,
            account=account,
            entry_type=CustomerAccountEntryTypeChoices.REFUND,
            amount=-abs(_to_decimal(amount)),
            user=user,
            notes=notes,
        )

    @staticmethod
    def create_adjustment(*, business, account, amount, user=None, notes=""):
        if not (notes or "").strip():
            raise ValidationError({"notes": "Los ajustes requieren una justificación."})
        return CustomerAccountService._apply_entry(
            business=business,
            account=account,
            entry_type=CustomerAccountEntryTypeChoices.ADJUSTMENT,
            amount=_to_decimal(amount),
            user=user,
            notes=notes,
        )

    @staticmethod
    @transaction.atomic
    def _apply_entry(*, business, account, entry_type, amount, user=None, notes=""):
        _validate_business(business)
        _validate_user_business(user=user, business=business)
        account = (
            CustomerAccount.objects.select_for_update()
            .select_related("customer")
            .get(pk=account.pk, business=business)
        )
        if amount == Decimal("0.00"):
            raise ValidationError({"amount": "El importe no puede ser cero."})
        if entry_type == CustomerAccountEntryTypeChoices.CHARGE:
            if not account.customer.is_active:
                raise ValidationError(
                    "No se pueden crear cargos para clientes inactivos."
                )
            if account.is_blocked:
                raise ValidationError("La cuenta está bloqueada para nuevos cargos.")
            if account.balance + amount > account.credit_limit:
                raise ValidationError("El cargo supera el límite de crédito.")
        balance_after = account.balance + amount
        account.balance = balance_after
        account.save(update_fields=["balance", "updated_at"])
        return CustomerAccountEntry.objects.create(
            business=business,
            account=account,
            entry_type=entry_type,
            amount=amount,
            balance_after=balance_after,
            notes=notes,
            created_by=user,
        )
