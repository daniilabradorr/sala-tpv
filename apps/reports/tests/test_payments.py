from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from django.test import TestCase

from apps.reports.periods import ReportPeriod
from apps.reports.selectors import payment_summary, payments_by_method
from apps.sales.tests.factories import create_sales_business, create_sales_store


class PaymentReportTests(TestCase):
    def test_empty_period_and_scope_validation(self):
        business = create_sales_business()
        period = ReportPeriod(
            datetime(2026, 9, 1, tzinfo=ZoneInfo("UTC")),
            datetime(2026, 9, 2, tzinfo=ZoneInfo("UTC")),
        )
        self.assertEqual(
            payment_summary(business=business, period=period),
            {
                "collected_amount": Decimal("0.00"),
                "refunded_amount": Decimal("0.00"),
                "payment_count": 0,
                "refund_count": 0,
                "net_amount": Decimal("0.00"),
            },
        )
        self.assertEqual(payments_by_method(business=business, period=period), [])

        foreign_business = create_sales_business()
        foreign_store = create_sales_store(business=foreign_business)
        with self.assertRaisesRegex(ValueError, "store must belong"):
            payment_summary(business=business, period=period, store=foreign_store)
