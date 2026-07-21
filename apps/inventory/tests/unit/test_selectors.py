"""Tests unitarios de selectors de inventory."""

from decimal import Decimal

from django.test import TestCase

from apps.inventory.selectors import (
    get_inventory_dashboard_data,
    get_inventory_items_for_business,
    get_low_stock_items,
)
from apps.inventory.tests.factories import (
    create_business,
    create_inventory_item,
    create_inventory_product,
    create_inventory_store,
)


class InventorySelectorsTests(TestCase):
    """Valida reglas de lectura de stock bajo y sin stock."""

    def setUp(self):  # noqa: N802
        self.business = create_business(
            name="Negocio Selectors",
            slug="negocio-selectors",
        )
        self.store = create_inventory_store(
            business=self.business,
            name="Tienda Selectors",
            code="INVSEL1",
        )
        self.low_product = create_inventory_product(
            business=self.business,
            name="Producto Bajo",
        )
        self.out_product = create_inventory_product(
            business=self.business,
            name="Producto Sin Stock",
        )
        self.low_item = create_inventory_item(
            business=self.business,
            store=self.store,
            product=self.low_product,
            current_stock=Decimal("10.000"),
            reserved_stock=Decimal("8.000"),
            minimum_stock=Decimal("3.000"),
        )
        self.out_item = create_inventory_item(
            business=self.business,
            store=self.store,
            product=self.out_product,
            current_stock=Decimal("2.000"),
            reserved_stock=Decimal("2.000"),
            minimum_stock=Decimal("3.000"),
        )

    def test_low_stock_uses_available_and_excludes_out_of_stock(self):
        """available=2 aparece como bajo y available=0 como sin stock."""
        low_items = list(get_low_stock_items(self.business))
        low_filtered = list(
            get_inventory_items_for_business(
                self.business,
                filters={"low_stock": True},
            )
        )
        out_filtered = list(
            get_inventory_items_for_business(
                self.business,
                filters={"out_of_stock": True},
            )
        )
        dashboard = get_inventory_dashboard_data(self.business)

        self.assertIn(self.low_item, low_items)
        self.assertIn(self.low_item, low_filtered)
        self.assertNotIn(self.out_item, low_items)
        self.assertNotIn(self.out_item, low_filtered)
        self.assertIn(self.out_item, out_filtered)
        self.assertEqual(dashboard["low_stock_products"], 1)
        self.assertEqual(dashboard["out_of_stock_products"], 1)
