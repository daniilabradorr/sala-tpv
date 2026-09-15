from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from django.test import TestCase

from apps.catalog.models import Category
from apps.reports.periods import ReportPeriod
from apps.reports.selectors import (
    sales_by_category,
    sales_by_product,
    sales_by_store,
    sales_summary,
    sales_timeseries,
)
from apps.sales.models import (
    Sale,
    SaleLine,
    SaleReturn,
    SaleReturnStatusChoices,
    SaleStatusChoices,
)
from apps.sales.tests.factories import (
    create_sale,
    create_sale_line,
    create_sale_return,
    create_sale_return_line,
    create_sales_business,
    create_sales_product,
    create_sales_store,
    create_sales_user,
)

UTC = ZoneInfo("UTC")


class SalesReportTests(TestCase):
    def setUp(self):
        self.business = create_sales_business()
        self.store = create_sales_store(business=self.business, name="Centro")
        self.user = create_sales_user(business=self.business)
        self.product = create_sales_product(
            business=self.business, tax=None, name="Café", sku="CAFE"
        )
        self.period = self._period(1, 4)

    def _period(self, start_day, end_day, tz=UTC):
        return ReportPeriod(
            datetime(2026, 9, start_day, tzinfo=tz),
            datetime(2026, 9, end_day, tzinfo=tz),
        )

    def _sale(
        self,
        *,
        status=SaleStatusChoices.COMPLETED,
        when=None,
        store=None,
        product=None,
        quantity="1.000",
        price="10.00",
    ):
        sale = create_sale(
            business=self.business,
            store=store or self.store,
            opened_by=self.user,
            status=SaleStatusChoices.COMPLETED,
        )
        line = create_sale_line(
            business=self.business,
            sale=sale,
            product=product or self.product,
            quantity=Decimal(quantity),
            unit_base_price=Decimal(price),
            tax_rate=Decimal("0.00"),
        )
        Sale.objects.filter(pk=sale.pk).update(
            status=status, completed_at=when or datetime(2026, 9, 1, 10, tzinfo=UTC)
        )
        sale.refresh_from_db()
        return sale, line

    def _return(
        self,
        sale,
        line,
        *,
        status=SaleReturnStatusChoices.COMPLETED,
        when=None,
        quantity="1.000",
        amount=None,
    ):
        document = create_sale_return(
            business=self.business,
            store=sale.store,
            original_sale=sale,
            created_by=self.user,
        )
        return_line = create_sale_return_line(
            business=self.business,
            return_doc=document,
            original_line=line,
            quantity=Decimal(quantity),
            amount=Decimal(amount) if amount else None,
        )
        SaleReturn.objects.filter(pk=document.pk).update(
            status=status, completed_at=when or datetime(2026, 9, 2, 10, tzinfo=UTC)
        )
        document.refresh_from_db()
        return document, return_line

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

    def test_summary_statuses_returns_counts_average_and_units(self):
        completed, line = self._sale(quantity="2.500", price="8.00")
        returned, _ = self._sale(
            status=SaleStatusChoices.RETURNED,
            when=datetime(2026, 9, 2, 9, tzinfo=UTC),
            price="10.00",
        )
        self._return(completed, line, quantity="0.500", amount="4.00")
        for status in (
            SaleStatusChoices.DRAFT,
            SaleStatusChoices.OPEN,
            SaleStatusChoices.CANCELLED,
        ):
            self._sale(status=status, price="100.00")
        for status in (
            SaleReturnStatusChoices.DRAFT,
            SaleReturnStatusChoices.CANCELLED,
        ):
            self._return(returned, returned.lines.get(), status=status, amount="3.00")

        result = sales_summary(business=self.business, period=self.period)
        self.assertEqual(
            result,
            {
                "gross_sales": Decimal("30.00"),
                "returns_amount": Decimal("4.00"),
                "net_sales": Decimal("26.00"),
                "ticket_count": 2,
                "average_ticket": Decimal("15.00"),
                "units_sold": Decimal("3.500"),
                "units_returned": Decimal("0.500"),
            },
        )

    def test_return_in_current_period_uses_its_date_not_old_sale_date(self):
        sale, line = self._sale(when=datetime(2026, 8, 20, tzinfo=UTC))
        self._return(sale, line, when=datetime(2026, 9, 2, tzinfo=UTC), amount="10.00")
        result = sales_summary(business=self.business, period=self.period)
        self.assertEqual(result["gross_sales"], Decimal("0.00"))
        self.assertEqual(result["ticket_count"], 0)
        self.assertEqual(result["returns_amount"], Decimal("10.00"))
        self.assertEqual(result["net_sales"], Decimal("-10.00"))

    def test_half_open_bounds_store_filter_and_business_isolation(self):
        other_store = create_sales_store(business=self.business, name="Norte")
        self._sale(when=self.period.start, price="10.00")
        self._sale(when=self.period.end, price="100.00")
        self._sale(store=other_store, price="20.00")
        other_business = create_sales_business()
        foreign_store = create_sales_store(business=other_business)
        foreign_user = create_sales_user(business=other_business)
        foreign_product = create_sales_product(business=other_business, tax=None)
        sale = create_sale(
            business=other_business,
            store=foreign_store,
            opened_by=foreign_user,
            status=SaleStatusChoices.COMPLETED,
        )
        create_sale_line(
            business=other_business,
            sale=sale,
            product=foreign_product,
            tax_rate=Decimal("0.00"),
        )
        Sale.objects.filter(pk=sale.pk).update(completed_at=self.period.start)
        self.assertEqual(
            sales_summary(business=self.business, period=self.period)["gross_sales"],
            Decimal("30.00"),
        )
        self.assertEqual(
            sales_summary(business=self.business, period=self.period, store=self.store)[
                "gross_sales"
            ],
            Decimal("10.00"),
        )
        with self.assertRaisesRegex(ValueError, "store must belong"):
            sales_summary(
                business=self.business, period=self.period, store=foreign_store
            )

    def test_timeseries_orders_days_keeps_return_only_day_and_uses_local_timezone(self):
        sale, line = self._sale(
            when=datetime(2026, 9, 1, 23, 30, tzinfo=UTC), quantity="2"
        )
        self._return(
            sale,
            line,
            when=datetime(2026, 9, 3, 8, tzinfo=UTC),
            quantity="1",
            amount="10",
        )
        madrid_period = ReportPeriod(
            datetime(2026, 9, 1, tzinfo=ZoneInfo("Europe/Madrid")),
            datetime(2026, 9, 4, tzinfo=ZoneInfo("Europe/Madrid")),
        )
        rows = sales_timeseries(business=self.business, period=madrid_period)
        self.assertEqual([row["day"].day for row in rows], [2, 3])
        self.assertEqual(rows[0]["gross_sales"], Decimal("20.00"))
        self.assertEqual(rows[1]["gross_sales"], Decimal("0.00"))
        self.assertEqual(rows[1]["returns_amount"], Decimal("10.00"))
        with self.assertRaisesRegex(ValueError, "Only the 'day'"):
            sales_timeseries(
                business=self.business, period=self.period, interval="week"
            )

    def test_by_store_combines_each_store_and_honours_filter(self):
        second = create_sales_store(business=self.business, name="Norte")
        first_sale, first_line = self._sale(quantity="2", price="10")
        self._return(first_sale, first_line, quantity="1", amount="10")
        self._sale(store=second, quantity="3", price="5")
        rows = sales_by_store(business=self.business, period=self.period)
        by_id = {row["store_id"]: row for row in rows}
        self.assertEqual(by_id[self.store.pk]["net_sales"], Decimal("10.00"))
        self.assertEqual(by_id[self.store.pk]["units_returned"], Decimal("1"))
        self.assertEqual(by_id[second.pk]["ticket_count"], 1)
        self.assertEqual(
            len(
                sales_by_store(business=self.business, period=self.period, store=second)
            ),
            1,
        )

    def test_product_breakdown_uses_line_snapshots_and_does_not_repeat_sale_total(self):
        second_product = create_sales_product(
            business=self.business,
            tax=None,
            name="Té",
            sku="TE",
            base_price=Decimal("5"),
        )
        sale, coffee_line = self._sale(price="10")
        tea_line = create_sale_line(
            business=self.business,
            sale=sale,
            product=second_product,
            unit_base_price=Decimal("5"),
            tax_rate=Decimal("0"),
        )
        SaleLine.objects.filter(pk=coffee_line.pk).update(
            product_name="Café histórico", sku="OLD"
        )
        self.product.name = "Café nuevo"
        self.product.sku = "NEW"
        self.product.save()
        self._return(sale, coffee_line, amount="4")
        rows = sales_by_product(business=self.business, period=self.period)
        by_sku = {row["sku"]: row for row in rows}
        self.assertEqual(set(by_sku), {"OLD", tea_line.sku})
        self.assertEqual(by_sku["OLD"]["product_name"], "Café histórico")
        self.assertEqual(by_sku["OLD"]["gross_sales"], Decimal("10.00"))
        self.assertEqual(by_sku["OLD"]["returns_amount"], Decimal("4.00"))
        self.assertEqual(by_sku[tea_line.sku]["gross_sales"], Decimal("5.00"))

    def test_category_breakdown_uses_snapshot_return_and_keeps_unknown(self):
        old = Category.objects.create(
            business=self.business, name="Bebidas", slug="bebidas"
        )
        new = Category.objects.create(
            business=self.business, name="Otros", slug="otros"
        )
        self.product.category = old
        self.product.save()
        sale, line = self._sale(quantity="2")
        SaleLine.objects.filter(pk=line.pk).update(
            category_source_id=old.pk,
            category_name="Bebidas históricas",
            category_slug="bebidas-old",
        )
        self.product.category = new
        self.product.save()
        self._return(sale, line, quantity="1", amount="10")
        unknown_product = create_sales_product(
            business=self.business, tax=None, name="Antiguo", sku="OLD2"
        )
        self._sale(product=unknown_product, price="3")
        rows = sales_by_category(business=self.business, period=self.period)
        by_key = {
            (row["category_source_id"], row["category_name"], row["category_slug"]): row
            for row in rows
        }
        historical = by_key[(old.pk, "Bebidas históricas", "bebidas-old")]
        self.assertEqual(historical["gross_sales"], Decimal("20.00"))
        self.assertEqual(historical["returns_amount"], Decimal("10.00"))
        self.assertIn((None, "", ""), by_key)
