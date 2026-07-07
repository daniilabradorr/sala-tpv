"""Tests unitarios de urls de inventory."""

from django.test import SimpleTestCase
from django.urls import resolve, reverse

from apps.inventory import views


class InventoryUrlsTests(SimpleTestCase):
    """Valida nombres y resolucion de rutas principales de inventory."""

    def test_inventory_dashboard_url_resolves(self):
        """La ruta dashboard debe resolver a InventoryDashboardView."""
        url = reverse("inventory:dashboard")
        match = resolve(url)

        self.assertEqual(match.func.view_class, views.InventoryDashboardView)

    def test_inventory_item_create_url_resolves(self):
        """La ruta de creacion de item debe resolver correctamente."""
        url = reverse("inventory:item_create")
        match = resolve(url)

        self.assertEqual(match.func.view_class, views.InventoryItemCreateView)

    def test_inventory_stock_adjustment_detail_url_contains_pk(self):
        """La ruta de detalle de ajuste debe aceptar pk."""
        url = reverse("inventory:stock_adjustment_detail", kwargs={"pk": 10})
        match = resolve(url)

        self.assertEqual(match.func.view_class, views.StockAdjustmentDetailView)
        self.assertEqual(match.kwargs["pk"], 10)

    def test_inventory_adjustment_line_edit_url_contains_adjustment_and_line(self):
        """La ruta de edicion de linea debe incluir adjustment_pk y line_pk."""
        url = reverse(
            "inventory:stock_adjustment_line_update",
            kwargs={"adjustment_pk": 3, "line_pk": 9},
        )
        match = resolve(url)

        self.assertEqual(match.func.view_class, views.StockAdjustmentLineUpdateView)
        self.assertEqual(match.kwargs["adjustment_pk"], 3)
        self.assertEqual(match.kwargs["line_pk"], 9)

    def test_inventory_adjustment_confirm_url_resolves(self):
        """La ruta de confirmar ajuste debe resolver correctamente."""
        url = reverse("inventory:stock_adjustment_confirm", kwargs={"pk": 1})
        match = resolve(url)

        self.assertEqual(match.func.view_class, views.StockAdjustmentConfirmView)
