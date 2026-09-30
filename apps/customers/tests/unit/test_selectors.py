from decimal import Decimal

from django.test import TestCase

from apps.customers.models import CustomerTypeChoices
from apps.customers.selectors import (
    get_customer_account_entries,
    get_customer_detail,
    get_customer_list_kpis,
    get_customers_for_business,
)
from apps.customers.tests.factories import create_account, create_customer, create_entry
from apps.users.tests.factories import create_business


class CustomerSelectorTests(TestCase):
    def test_filters_search_detail_and_entries(self):
        b1 = create_business(slug="s1")
        b2 = create_business(name="Otro", slug="s2")
        c1 = create_customer(
            business=b1,
            name="Ana",
            legal_name="Ana SL",
            tax_identifier="B123",
            phone="600",
            email="ana@test.com",
            customer_type=CustomerTypeChoices.COMPANY,
        )
        a1 = create_account(business=b1, customer=c1)
        c2 = create_customer(business=b1, name="Inactive", is_active=False)
        create_account(business=b1, customer=c2)
        create_account(business=b2)
        self.assertFalse(get_customers_for_business(business=None).exists())
        self.assertEqual(list(get_customers_for_business(business=b1)), [c1])
        self.assertEqual(
            list(get_customers_for_business(business=b1, status="inactive")), [c2]
        )
        self.assertEqual(
            get_customers_for_business(business=b1, status="all").count(), 2
        )
        for q in ["Ana", "Ana SL", "B123", "600", "ana@test.com"]:
            self.assertEqual(
                list(get_customers_for_business(business=b1, query=q, status="all")),
                [c1],
            )
        self.assertEqual(
            list(
                get_customers_for_business(
                    business=b1, customer_type=CustomerTypeChoices.COMPANY
                )
            ),
            [c1],
        )
        self.assertEqual(
            get_customers_for_business(business=b1, customer_type="bad").count(), 1
        )
        self.assertEqual(get_customer_detail(business=b1, pk=c1.pk), c1)
        with self.assertRaises(Exception):
            get_customer_detail(business=b2, pk=c1.pk)
        for i in range(3):
            create_entry(
                business=b1,
                account=a1,
                amount=Decimal("1.00"),
                balance_after=Decimal(str(i)),
            )
        entries = list(get_customer_account_entries(business=b1, account=a1, limit=2))
        self.assertEqual(len(entries), 2)
        self.assertGreater(entries[0].pk, entries[1].pk)

    def test_account_state_filters_and_positive_debt_kpis(self):
        business = create_business(slug="customer-kpis")
        debt = create_account(business=business, balance=Decimal("40.00"))
        create_account(business=business, balance=Decimal("-12.00"))
        settled = create_account(business=business, balance=Decimal("0.00"))
        settled.customer.is_active = False
        settled.customer.save()

        self.assertEqual(
            list(
                get_customers_for_business(
                    business=business, status="all", account_state="debt"
                )
            ),
            [debt.customer],
        )
        self.assertEqual(
            get_customer_list_kpis(business=business),
            {"active": 2, "with_debt": 1, "debt_total": Decimal("40.00")},
        )
