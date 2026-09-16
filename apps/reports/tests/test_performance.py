from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext

from apps.inventory.tests.factories import (
    create_business,
    create_inventory_item,
    create_inventory_product,
    create_inventory_store,
)
from apps.reports.periods import ReportPeriod
from apps.reports.selectors import dashboard_summary


class ReportsPerformanceTests(TestCase):
    def setUp(self):
        self.business = create_business()
        self.store = create_inventory_store(business=self.business)
        self.period = ReportPeriod(
            datetime(2026, 9, 1, tzinfo=ZoneInfo("UTC")),
            datetime(2026, 10, 1, tzinfo=ZoneInfo("UTC")),
        )

    def _item(self, number):
        product = create_inventory_product(
            business=self.business, name=f"Product {number}"
        )
        create_inventory_item(
            business=self.business,
            store=self.store,
            product=product,
            current_stock=Decimal(number),
            minimum_stock=Decimal("5"),
        )

    def _dashboard_query_count(self):
        with CaptureQueriesContext(connection) as queries:
            dashboard_summary(
                business=self.business, period=self.period, store=self.store
            )
        return len(queries)

    def test_dashboard_query_count_is_bounded_and_independent_of_inventory_rows(self):
        self._item(1)
        one_count = self._dashboard_query_count()
        for number in range(2, 31):
            self._item(number)
        many_count = self._dashboard_query_count()

        self.assertEqual(one_count, many_count)
        self.assertLessEqual(many_count, 20)
