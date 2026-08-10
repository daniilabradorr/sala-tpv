from decimal import Decimal
from uuid import uuid4

from apps.customers.models import (
    Customer,
    CustomerAccount,
    CustomerAccountEntry,
    EntryTypeChoices,
    CustomerTypeChoices,
)
from apps.users.models import RoleChoices
from apps.users.tests.factories import create_business, create_user


def unique_slug(prefix="customers"):
    return f"{prefix}-{uuid4().hex[:8]}"


def create_customer(
    *,
    business=None,
    name=None,
    tax_identifier="",
    customer_type=CustomerTypeChoices.PERSON,
    is_active=True,
    **kwargs,
):
    business = business or create_business(slug=unique_slug())
    return Customer.objects.create(
        business=business,
        name=name or f"Cliente {uuid4().hex[:6]}",
        tax_identifier=tax_identifier,
        customer_type=customer_type,
        is_active=is_active,
        **kwargs,
    )


def create_account(
    *,
    business=None,
    customer=None,
    balance=Decimal("0.00"),
    credit_limit=Decimal("100.00"),
    is_blocked=False,
):
    business = business or create_business(slug=unique_slug())
    customer = customer or create_customer(business=business)
    return CustomerAccount.objects.create(
        business=business,
        customer=customer,
        balance=balance,
        credit_limit=credit_limit,
        is_blocked=is_blocked,
    )


def create_entry(
    *,
    business,
    account,
    amount=Decimal("10.00"),
    entry_type=EntryTypeChoices.CHARGE,
    balance_after=Decimal("10.00"),
    created_by=None,
    notes="",
    sale=None,
):
    return CustomerAccountEntry.objects.create(
        business=business,
        account=account,
        entry_type=entry_type,
        amount=amount,
        balance_after=balance_after,
        created_by=created_by,
        notes=notes,
        sale=sale,
    )


def create_customer_user(
    *, business, role=RoleChoices.CASHIER, password="testpass123", **extra_fields
):
    return create_user(
        business=business,
        email=f"{role}-{uuid4().hex[:8]}@customers.test",
        password=password,
        role=role,
        **extra_fields,
    )
