from django.db.models import Count, DecimalField, Q, Sum, Value
from django.db.models.functions import Coalesce
from django.shortcuts import get_object_or_404

from apps.customers.models import Customer, CustomerAccountEntry, CustomerTypeChoices


def get_customers_for_business(
    *, business, query="", status="active", customer_type="", account_state=""
):
    if business is None:
        return Customer.objects.none()
    qs = Customer.objects.filter(business=business).select_related(
        "business", "account"
    )
    if status == "active":
        qs = qs.filter(is_active=True)
    elif status == "inactive":
        qs = qs.filter(is_active=False)
    if customer_type in CustomerTypeChoices.values:
        qs = qs.filter(customer_type=customer_type)
    if account_state == "debt":
        qs = qs.filter(account__balance__gt=0)
    elif account_state == "settled":
        qs = qs.filter(account__balance=0)
    elif account_state == "credit":
        qs = qs.filter(account__balance__lt=0)
    query = (query or "").strip()
    if query:
        qs = qs.filter(
            Q(name__icontains=query)
            | Q(legal_name__icontains=query)
            | Q(tax_identifier__icontains=query)
            | Q(foreign_id__icontains=query)
            | Q(phone__icontains=query)
            | Q(email__icontains=query)
        )
    return qs.order_by("name", "pk")


def get_customer_list_kpis(*, business):
    """Business-global customer metrics, calculated entirely by the database."""
    if business is None:
        return {"active": 0, "with_debt": 0, "debt_total": 0}
    return Customer.objects.filter(business=business).aggregate(
        active=Count("pk", filter=Q(is_active=True)),
        with_debt=Count("pk", filter=Q(account__balance__gt=0)),
        debt_total=Coalesce(
            Sum("account__balance", filter=Q(account__balance__gt=0)),
            Value(0),
            output_field=DecimalField(max_digits=14, decimal_places=2),
        ),
    )


def get_customer_detail(*, business, pk):
    return get_object_or_404(
        Customer.objects.select_related("business", "account"), business=business, pk=pk
    )


def get_customer_account_entries(*, business, account, limit=None):
    if business is None:
        return CustomerAccountEntry.objects.none()
    queryset = (
        CustomerAccountEntry.objects.filter(business=business, account=account)
        .select_related("created_by", "sale", "sale__store", "payment")
        .order_by("-created_at", "-pk")
    )
    return queryset[:limit] if limit is not None else queryset


def get_customer_pending_debt_sales(*, business, customer, stores):
    """Completed, accessible sales whose debt was explicitly charged on account."""
    from apps.sales.models import SaleStatusChoices
    from apps.sales.selectors import get_sales_for_business

    return (
        get_sales_for_business(business=business, filters={"customer": customer})
        .filter(
            store__in=stores,
            status=SaleStatusChoices.COMPLETED,
            pending_amount__gt=0,
            customer_account_entries__entry_type="charge",
        )
        .distinct()
    )
