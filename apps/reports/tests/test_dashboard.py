from datetime import datetime
from decimal import Decimal
from unittest.mock import patch
from zoneinfo import ZoneInfo

from django.test import TestCase

from apps.inventory.tests.factories import (
    create_business,
    create_inventory_item,
    create_inventory_product,
    create_inventory_store,
)
from apps.reports.periods import ReportPeriod
from apps.reports.selectors import dashboard_summary

UTC = ZoneInfo("UTC")


class DashboardReportTests(TestCase):
    def setUp(self):
        self.business = create_business()
        self.store = create_inventory_store(business=self.business)
        self.period = ReportPeriod(
            datetime(2026, 9, 15, tzinfo=UTC),
            datetime(2026, 9, 16, tzinfo=UTC),
        )
        self.trend_period = ReportPeriod(
            datetime(2026, 9, 9, tzinfo=UTC), self.period.end
        )

    def test_empty_dashboard_has_the_complete_stable_contract(self):
        result = dashboard_summary(business=self.business, period=self.period)
        self.assertEqual(
            list(result),
            [
                "scope",
                "period",
                "trend_period",
                "sales",
                "sales_timeseries",
                "payments",
                "payments_by_method",
                "cash",
                "tax",
                "inventory",
                "purchases",
            ],
        )
        self.assertEqual(
            result["scope"], {"business_id": self.business.pk, "store_id": None}
        )
        self.assertEqual(result["sales_timeseries"], [])
        self.assertEqual(result["payments_by_method"], [])
        self.assertEqual(
            result["inventory"],
            {
                "tracked_items_count": 0,
                "out_of_stock_count": 0,
                "low_stock_count": 0,
                "healthy_stock_count": 0,
            },
        )
        self.assertFalse(
            {"customer_count", "profit", "margin", "cash_on_hand"} & result.keys()
        )

    @patch("apps.reports.selectors.purchase_summary")
    @patch("apps.reports.selectors.tax_summary")
    @patch("apps.reports.selectors.cash_summary")
    @patch("apps.reports.selectors.payments_by_method")
    @patch("apps.reports.selectors.payment_summary")
    @patch("apps.reports.selectors.sales_timeseries")
    @patch("apps.reports.selectors.sales_summary")
    def test_composes_public_contracts_and_only_trend_uses_trend_period(
        self, sales, timeseries, payments, by_method, cash, tax, purchases
    ):
        contracts = {
            sales: {"gross_sales": Decimal("100"), "returns_amount": Decimal("20")},
            timeseries: [{"day": self.period.start.date()}],
            payments: {
                "collected_amount": Decimal("70"),
                "refunded_amount": Decimal("5"),
            },
            by_method: [{"method_code": "card"}],
            cash: {"cash_sales": Decimal("0")},
            tax: {"net_tax_amount": Decimal("12")},
            purchases: {"total_amount": Decimal("30")},
        }
        for mock, value in contracts.items():
            mock.return_value = value

        result = dashboard_summary(
            business=self.business,
            period=self.period,
            store=self.store,
            trend_period=self.trend_period,
        )

        self.assertIs(result["sales"], contracts[sales])
        self.assertIs(result["sales_timeseries"], contracts[timeseries])
        self.assertEqual(result["cash"]["cash_sales"], Decimal("0"))
        timeseries.assert_called_once_with(
            business=self.business, period=self.trend_period, store=self.store
        )
        for selector in (sales, payments, by_method, cash, tax, purchases):
            selector.assert_called_once_with(
                business=self.business, period=self.period, store=self.store
            )

    def test_current_inventory_counts_are_period_independent_and_exclude_inactive(self):
        values = (("0", "0"), ("3", "5"), ("6", "5"), ("100", "5"))
        for number, (stock, minimum) in enumerate(values):
            product = create_inventory_product(
                business=self.business, name=f"Product {number}"
            )
            create_inventory_item(
                business=self.business,
                store=self.store,
                product=product,
                current_stock=Decimal(stock),
                minimum_stock=Decimal(minimum),
                is_active=number != 3,
            )
        result = dashboard_summary(
            business=self.business, period=self.period, store=self.store
        )
        self.assertEqual(
            result["inventory"],
            {
                "tracked_items_count": 3,
                "out_of_stock_count": 1,
                "low_stock_count": 1,
                "healthy_stock_count": 1,
            },
        )

    def test_default_trend_store_validation_and_business_isolation(self):
        result = dashboard_summary(business=self.business, period=self.period)
        self.assertEqual(result["trend_period"], result["period"])
        foreign_business = create_business(name="Other", slug="other")
        foreign_store = create_inventory_store(business=foreign_business)
        with self.assertRaisesRegex(ValueError, "store must belong"):
            dashboard_summary(
                business=self.business, period=self.period, store=foreign_store
            )
        self.assertEqual(
            dashboard_summary(business=foreign_business, period=self.period)[
                "inventory"
            ]["tracked_items_count"],
            0,
        )
