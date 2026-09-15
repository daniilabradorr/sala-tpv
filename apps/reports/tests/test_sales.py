from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from django.test import TestCase

from apps.reports.periods import ReportPeriod
from apps.reports.selectors import sales_summary
from apps.sales.models import Sale, SaleStatusChoices
from apps.sales.tests.factories import (
    create_sale,
    create_sale_line,
    create_sales_business,
    create_sales_product,
    create_sales_store,
    create_sales_user,
)


class SalesReportTests(TestCase):
    def setUp(self):
        self.business = create_sales_business()
        self.store = create_sales_store(business=self.business)
        self.user = create_sales_user(business=self.business)
        self.product = create_sales_product(business=self.business, tax=None)
        self.period = ReportPeriod(
            datetime(2026, 9, 1, tzinfo=ZoneInfo("UTC")),
            datetime(2026, 9, 2, tzinfo=ZoneInfo("UTC")),
        )

    def test_empty_summary_uses_decimal_zeros(self):
        self.assertEqual(
            sales_summary(business=self.business, period=self.period),
            {
                "gross_sales": Decimal("0.00"),
                "returns_amount": Decimal("0.00"),
                "net_sales": Decimal("0.00"),
                "ticket_count": 0,
                "average_ticket": Decimal("0.00"),
                "units_sold": Decimal("0.000"),
                "units_returned": Decimal("0.000"),
            },
        )

    def test_completed_and_returned_sales_count_as_historical_sales(self):
        for status, hour in (
            (SaleStatusChoices.COMPLETED, 10),
            (SaleStatusChoices.RETURNED, 11),
        ):
            sale = create_sale(
                business=self.business,
                store=self.store,
                opened_by=self.user,
                status=SaleStatusChoices.COMPLETED,
            )
            create_sale_line(business=self.business, sale=sale, product=self.product)
            Sale.objects.filter(pk=sale.pk).update(
                status=status,
                completed_at=datetime(2026, 9, 1, hour, tzinfo=ZoneInfo("UTC")),
            )

        result = sales_summary(business=self.business, period=self.period)

        self.assertEqual(result["ticket_count"], 2)
        self.assertEqual(result["gross_sales"], Decimal("24.20"))
        self.assertEqual(result["average_ticket"], Decimal("12.10"))
        self.assertEqual(result["units_sold"], Decimal("2"))

    def test_foreign_store_is_rejected(self):
        other_business = create_sales_business()
        other_store = create_sales_store(business=other_business)
        with self.assertRaisesRegex(ValueError, "store must belong"):
            sales_summary(business=self.business, period=self.period, store=other_store)
