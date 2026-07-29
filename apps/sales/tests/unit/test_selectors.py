"""Tests unitarios de selectors del módulo sales."""

from decimal import Decimal

from django.http import Http404
from django.test import TestCase

from apps.sales.models import SaleReturnStatusChoices, SaleStatusChoices
from apps.sales.selectors import (
    get_returnable_sale_lines,
    get_sale_detail,
    get_sale_returns_for_business,
    get_sales_for_business,
)
from apps.sales.tests.factories import (
    create_sale,
    create_sale_line,
    create_sale_return,
    create_sale_return_line,
    create_sales_business,
    create_sales_customer,
    create_sales_product,
    create_sales_store,
    create_sales_tax,
    create_sales_user,
)


class SaleSelectorsTests(TestCase):
    def setUp(self):  # noqa: N802
        self.business = create_sales_business(name="Empresa A")
        self.other_business = create_sales_business(name="Empresa B")
        self.store = create_sales_store(business=self.business, name="Tienda A")
        self.other_store = create_sales_store(
            business=self.other_business,
            name="Tienda B",
        )
        self.user = create_sales_user(business=self.business)
        self.other_user = create_sales_user(business=self.other_business)
        self.customer = create_sales_customer(
            business=self.business,
            name="Ana Cliente",
        )
        self.tax = create_sales_tax(business=self.business)
        self.other_tax = create_sales_tax(business=self.other_business)
        self.product = create_sales_product(business=self.business, tax=self.tax)
        self.other_product = create_sales_product(
            business=self.other_business,
            tax=self.other_tax,
        )

    def test_sales_selector_isolates_business(self):
        own_sale = create_sale(
            business=self.business,
            store=self.store,
            opened_by=self.user,
            customer=self.customer,
        )
        create_sale(
            business=self.other_business,
            store=self.other_store,
            opened_by=self.other_user,
        )

        result = get_sales_for_business(
            business=self.business,
            filters={},
        )

        self.assertEqual(list(result), [own_sale])

    def test_sales_selector_filters_status_and_query(self):
        matching = create_sale(
            business=self.business,
            store=self.store,
            opened_by=self.user,
            customer=self.customer,
            status=SaleStatusChoices.OPEN,
        )
        create_sale(
            business=self.business,
            store=self.store,
            opened_by=self.user,
            status=SaleStatusChoices.CANCELLED,
        )

        result = get_sales_for_business(
            business=self.business,
            filters={
                "status": SaleStatusChoices.OPEN,
                "query": "Ana",
            },
        )

        self.assertEqual(list(result), [matching])

    def test_sale_detail_prefetches_lines_and_rejects_other_business(self):
        sale = create_sale(
            business=self.business,
            store=self.store,
            opened_by=self.user,
        )
        line = create_sale_line(
            business=self.business,
            sale=sale,
            product=self.product,
        )

        detail = get_sale_detail(
            business=self.business,
            pk=sale.pk,
        )

        self.assertEqual(detail.pk, sale.pk)
        self.assertEqual(list(detail.lines.all()), [line])

        with self.assertRaises(Http404):
            get_sale_detail(
                business=self.other_business,
                pk=sale.pk,
            )

    def test_returnable_lines_subtract_only_completed_returns(self):
        sale = create_sale(
            business=self.business,
            store=self.store,
            opened_by=self.user,
            status=SaleStatusChoices.COMPLETED,
        )
        line = create_sale_line(
            business=self.business,
            sale=sale,
            product=self.product,
            quantity=Decimal("5.000"),
        )

        completed_return = create_sale_return(
            business=self.business,
            store=self.store,
            original_sale=sale,
            created_by=self.user,
            status=SaleReturnStatusChoices.COMPLETED,
        )
        create_sale_return_line(
            business=self.business,
            return_doc=completed_return,
            original_line=line,
            quantity=Decimal("2.000"),
        )

        draft_return = create_sale_return(
            business=self.business,
            store=self.store,
            original_sale=sale,
            created_by=self.user,
            status=SaleReturnStatusChoices.DRAFT,
        )
        create_sale_return_line(
            business=self.business,
            return_doc=draft_return,
            original_line=line,
            quantity=Decimal("1.000"),
        )

        result = get_returnable_sale_lines(
            business=self.business,
            sale=sale,
        ).get(pk=line.pk)

        self.assertEqual(result.returned_quantity, Decimal("2.000"))
        self.assertEqual(result.returnable_quantity, Decimal("3.000"))

    def test_return_selector_isolates_business_and_filters_status(self):
        sale = create_sale(
            business=self.business,
            store=self.store,
            opened_by=self.user,
            status=SaleStatusChoices.COMPLETED,
        )
        own_return = create_sale_return(
            business=self.business,
            store=self.store,
            original_sale=sale,
            created_by=self.user,
            status=SaleReturnStatusChoices.DRAFT,
        )

        other_sale = create_sale(
            business=self.other_business,
            store=self.other_store,
            opened_by=self.other_user,
            status=SaleStatusChoices.COMPLETED,
        )
        create_sale_return(
            business=self.other_business,
            store=self.other_store,
            original_sale=other_sale,
            created_by=self.other_user,
            status=SaleReturnStatusChoices.DRAFT,
        )

        result = get_sale_returns_for_business(
            business=self.business,
            filters={"status": SaleReturnStatusChoices.DRAFT},
        )

        self.assertEqual(list(result), [own_return])
