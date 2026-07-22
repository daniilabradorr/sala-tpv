from django.db.models import Q
from django.shortcuts import get_object_or_404

from apps.customers.models import Customer, CustomerAccountEntry, CustomerTypeChoices


def get_customers_for_business(
    *, business, query="", status="active", customer_type=""
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


def get_customer_detail(*, business, pk):
    return get_object_or_404(
        Customer.objects.select_related("business", "account"), business=business, pk=pk
    )


def get_customer_account_entries(*, business, account, limit=20):
    if business is None:
        return CustomerAccountEntry.objects.none()
    return (
        CustomerAccountEntry.objects.filter(business=business, account=account)
        .select_related("created_by")
        .order_by("-created_at", "-pk")[:limit]
    )
