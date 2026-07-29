"""Tests unitarios de modelos del módulo sales."""

from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import TestCase

from apps.sales.models import (
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
    create_sales_tax,
    create_sales_user,
)


class SaleModelTests(TestCase):
    def setUp(self):  # noqa: N802
        self.business = create_sales_business()
        self.store = create_sales_store(business=self.business)
        self.user = create_sales_user(business=self.business)
        self.tax = create_sales_tax(business=self.business)
        self.product = create_sales_product(
            business=self.business,
            tax=self.tax,
            name="Café",
            base_price=Decimal("2.00"),
        )

    def test_sale_state_properties_follow_status(self):
        sale = create_sale(
            business=self.business,
            store=self.store,
            opened_by=self.user,
            status=SaleStatusChoices.OPEN,
        )

        self.assertTrue(sale.is_open)
        self.assertTrue(sale.is_editable)
        self.assertFalse(sale.is_completed)

        sale.status = SaleStatusChoices.COMPLETED
        sale.closed_by = self.user
        from django.utils import timezone

        sale.completed_at = timezone.now()
        sale.save()

        self.assertTrue(sale.is_completed)
        self.assertFalse(sale.is_editable)

    def test_sale_rejects_store_from_another_business(self):
        other_business = create_sales_business(name="Otro negocio")
        other_store = create_sales_store(business=other_business)

        sale = create_sale(
            business=self.business,
            store=self.store,
            opened_by=self.user,
        )
        sale.store = other_store

        with self.assertRaises(ValidationError):
            sale.save()

    def test_sale_line_keeps_historical_snapshot_after_product_changes(self):
        sale = create_sale(
            business=self.business,
            store=self.store,
            opened_by=self.user,
        )
        line = create_sale_line(
            business=self.business,
            sale=sale,
            product=self.product,
            quantity=Decimal("2.000"),
        )

        self.product.name = "Café nuevo"
        self.product.base_price = Decimal("5.00")
        self.product.save()

        line.refresh_from_db()

        self.assertEqual(line.product_name, "Café")
        self.assertEqual(line.unit_base_price, Decimal("2.00"))
        self.assertEqual(line.quantity, Decimal("2.000"))

    def test_sale_line_rejects_business_different_from_sale(self):
        sale = create_sale(
            business=self.business,
            store=self.store,
            opened_by=self.user,
        )
        other_business = create_sales_business(name="Empresa secundaria")

        from apps.sales.models import SaleLine

        line = SaleLine(
            business=other_business,
            sale=sale,
            product=self.product,
            product_name=self.product.name,
            sku=self.product.sku,
            quantity=Decimal("1.000"),
            unit=self.product.unit,
            unit_base_price=Decimal("2.00"),
            discount_amount=Decimal("0.00"),
            tax_rate=Decimal("21.00"),
            tax_amount=Decimal("0.42"),
            line_total=Decimal("2.42"),
        )

        with self.assertRaises(ValidationError):
            line.save()


class SaleReturnModelTests(TestCase):
    def setUp(self):  # noqa: N802
        self.business = create_sales_business()
        self.store = create_sales_store(business=self.business)
        self.user = create_sales_user(business=self.business)
        self.tax = create_sales_tax(business=self.business)
        self.product = create_sales_product(business=self.business, tax=self.tax)
        self.sale = create_sale(
            business=self.business,
            store=self.store,
            opened_by=self.user,
            status=SaleStatusChoices.COMPLETED,
        )
        self.sale_line = create_sale_line(
            business=self.business,
            sale=self.sale,
            product=self.product,
            quantity=Decimal("2.000"),
        )

    def test_return_is_only_editable_in_draft(self):
        return_doc = create_sale_return(
            business=self.business,
            store=self.store,
            original_sale=self.sale,
            created_by=self.user,
        )

        self.assertTrue(return_doc.is_editable)

        return_doc.status = SaleReturnStatusChoices.CANCELLED
        return_doc.save()

        self.assertFalse(return_doc.is_editable)
        self.assertTrue(return_doc.is_cancelled)

    def test_return_line_rejects_quantity_above_original_line(self):
        return_doc = create_sale_return(
            business=self.business,
            store=self.store,
            original_sale=self.sale,
            created_by=self.user,
        )

        from apps.sales.models import SaleReturnLine

        line = SaleReturnLine(
            business=self.business,
            return_doc=return_doc,
            original_line=self.sale_line,
            quantity=Decimal("3.000"),
            amount=Decimal("36.30"),
        )

        with self.assertRaises(ValidationError):
            line.save()

    def test_return_line_rejects_line_from_another_sale(self):
        other_sale = create_sale(
            business=self.business,
            store=self.store,
            opened_by=self.user,
            status=SaleStatusChoices.COMPLETED,
        )
        other_line = create_sale_line(
            business=self.business,
            sale=other_sale,
            product=self.product,
        )
        return_doc = create_sale_return(
            business=self.business,
            store=self.store,
            original_sale=self.sale,
            created_by=self.user,
        )

        from apps.sales.models import SaleReturnLine

        invalid = SaleReturnLine(
            business=self.business,
            return_doc=return_doc,
            original_line=other_line,
            quantity=Decimal("1.000"),
            amount=other_line.line_total,
        )

        with self.assertRaises(ValidationError):
            invalid.save()

    def test_return_line_unique_per_return_and_original_line(self):
        return_doc = create_sale_return(
            business=self.business,
            store=self.store,
            original_sale=self.sale,
            created_by=self.user,
        )
        create_sale_return_line(
            business=self.business,
            return_doc=return_doc,
            original_line=self.sale_line,
        )

        with self.assertRaises(ValidationError):
            create_sale_return_line(
                business=self.business,
                return_doc=return_doc,
                original_line=self.sale_line,
            )
