"""Tests de integracion para vistas de inventory."""

from decimal import Decimal

from django.test import TestCase, override_settings
from django.urls import reverse

from apps.inventory.models import InventoryItem, StockAdjustment, StockMovement
from apps.inventory.services import add_stock_adjustment_line, create_stock_adjustment
from apps.inventory.tests.factories import (
    create_business,
    create_inventory_cashier,
    create_inventory_item,
    create_inventory_owner,
    create_inventory_product,
    create_inventory_store,
)


TEST_TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "APP_DIRS": False,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
            "loaders": [
                (
                    "django.template.loaders.locmem.Loader",
                    {
                        "inventory/dashboard.html": "dashboard",
                        "inventory/item_list.html": (
                            "{% for i in inventory_items %}{{ i.id }} {% endfor %}"
                        ),
                        "inventory/item_detail.html": "{{ inventory_item.id }}",
                        "inventory/item_form.html": "{{ form.errors }}",
                        "inventory/initial_stock_form.html": "{{ form.errors }}",
                        "inventory/stock_movement_list.html": (
                            "{% for m in stock_movements %}{{ m.id }} {% endfor %}"
                        ),
                        "inventory/stock_movement_detail.html": "{{ stock_movement.id }}",
                        "inventory/stock_adjustment_list.html": (
                            "{% for a in stock_adjustments %}{{ a.id }} {% endfor %}"
                        ),
                        "inventory/stock_adjustment_detail.html": "{{ stock_adjustment.id }}",
                        "inventory/stock_adjustment_form.html": "{{ form.errors }}",
                        "inventory/stock_adjustment_line_form.html": "{{ form.errors }}",
                    },
                )
            ],
        },
    }
]


@override_settings(
    TEMPLATES=TEST_TEMPLATES,
    LOGIN_URL="/users/login/",
)
class InventoryViewsIntegrationTests(TestCase):
    """Valida flujos principales HTTP del modulo inventory."""

    password = "testpass123"

    def setUp(self):  # noqa: N802
        """Prepara negocio, usuarios y catalogo base para las pruebas."""
        self.business = create_business(
            name="Negocio Inv A",
            slug="negocio-inv-a",
        )
        self.other_business = create_business(
            name="Negocio Inv B",
            slug="negocio-inv-b",
        )

        self.owner = create_inventory_owner(
            business=self.business,
            password=self.password,
        )
        self.cashier = create_inventory_cashier(
            business=self.business,
            password=self.password,
        )

        self.store = create_inventory_store(
            business=self.business,
            name="Tienda A",
            code="INVA01",
        )
        self.other_store = create_inventory_store(
            business=self.other_business,
            name="Tienda B",
            code="INVB01",
        )

        self.product = create_inventory_product(
            business=self.business,
            name="Producto A",
        )
        self.other_product = create_inventory_product(
            business=self.other_business,
            name="Producto B",
        )

    def login_as(self, user):
        """Inicia sesion con autenticacion basada en email."""
        logged_in = self.client.login(
            email=user.email,
            password=self.password,
        )
        self.assertTrue(logged_in)

    def test_owner_can_create_inventory_item_and_manipulated_business_is_ignored(self):
        """Owner crea item y business manipulado en POST se ignora."""
        self.login_as(self.owner)

        response = self.client.post(
            reverse("inventory:item_create"),
            data={
                "store": self.store.pk,
                "product": self.product.pk,
                "minimum_stock": "2.000",
                "maximum_stock": "25.000",
                "location": "Pasillo 1",
                "business": self.other_business.pk,
            },
        )

        item = InventoryItem.objects.get(
            business=self.business,
            store=self.store,
            product=self.product,
        )

        self.assertRedirects(
            response,
            reverse("inventory:item_detail", kwargs={"pk": item.pk}),
            fetch_redirect_response=False,
        )
        self.assertEqual(item.business, self.business)

    def test_cashier_cannot_create_inventory_item(self):
        """Un cashier no puede acceder a la creacion de inventario."""
        self.login_as(self.cashier)

        response = self.client.post(
            reverse("inventory:item_create"),
            data={
                "store": self.store.pk,
                "product": self.product.pk,
                "minimum_stock": "1.000",
            },
        )

        self.assertEqual(response.status_code, 403)

    def test_owner_can_confirm_stock_adjustment_and_stock_changes(self):
        """Confirmar ajuste debe actualizar stock y crear movimiento."""
        self.login_as(self.owner)

        item = create_inventory_item(
            business=self.business,
            store=self.store,
            product=self.product,
            current_stock=Decimal("4.000"),
            minimum_stock=Decimal("1.000"),
        )

        adjustment = create_stock_adjustment(
            business=self.business,
            store=self.store,
            reason=StockAdjustment.REASON_STOCKTAKE,
            user=self.owner,
        )

        add_stock_adjustment_line(
            adjustment=adjustment,
            inventory_item=item,
            counted_stock=Decimal("7.000"),
            notes="Recuento",
        )

        response = self.client.post(
            reverse("inventory:stock_adjustment_confirm", kwargs={"pk": adjustment.pk}),
            data={"confirm": "on"},
        )

        item.refresh_from_db()
        adjustment.refresh_from_db()

        self.assertRedirects(
            response,
            reverse("inventory:stock_adjustment_detail", kwargs={"pk": adjustment.pk}),
            fetch_redirect_response=False,
        )
        self.assertEqual(adjustment.status, StockAdjustment.STATUS_CONFIRMED)
        self.assertEqual(item.current_stock, Decimal("7.000"))
        self.assertTrue(
            StockMovement.objects.filter(
                business=self.business,
                movement_type=StockMovement.TYPE_ADJUSTMENT_IN,
                quantity=Decimal("3.000"),
            ).exists()
        )

    def test_owner_cannot_confirm_adjustment_without_checkbox(self):
        """Sin checkbox de confirmacion, el ajuste debe seguir en borrador."""
        self.login_as(self.owner)

        item = create_inventory_item(
            business=self.business,
            store=self.store,
            product=self.product,
            current_stock=Decimal("4.000"),
        )
        adjustment = create_stock_adjustment(
            business=self.business,
            store=self.store,
            reason=StockAdjustment.REASON_STOCKTAKE,
            user=self.owner,
        )
        add_stock_adjustment_line(
            adjustment=adjustment,
            inventory_item=item,
            counted_stock=Decimal("4.000"),
        )

        response = self.client.post(
            reverse("inventory:stock_adjustment_confirm", kwargs={"pk": adjustment.pk}),
            data={},
        )

        adjustment.refresh_from_db()
        self.assertRedirects(
            response,
            reverse("inventory:stock_adjustment_detail", kwargs={"pk": adjustment.pk}),
            fetch_redirect_response=False,
        )
        self.assertEqual(adjustment.status, StockAdjustment.STATUS_DRAFT)

    def test_owner_can_cancel_draft_adjustment(self):
        """Cancelar ajuste en borrador debe dejarlo en estado cancelado."""
        self.login_as(self.owner)

        adjustment = create_stock_adjustment(
            business=self.business,
            store=self.store,
            reason=StockAdjustment.REASON_OTHER,
            user=self.owner,
        )

        response = self.client.post(
            reverse("inventory:stock_adjustment_cancel", kwargs={"pk": adjustment.pk}),
            data={},
        )

        adjustment.refresh_from_db()
        self.assertRedirects(
            response,
            reverse("inventory:stock_adjustment_detail", kwargs={"pk": adjustment.pk}),
            fetch_redirect_response=False,
        )
        self.assertEqual(adjustment.status, StockAdjustment.STATUS_CANCELLED)

    def test_cashier_cannot_confirm_adjustment(self):
        """Usuarios cashier no deben tener permiso para confirmar ajustes."""
        self.login_as(self.cashier)

        adjustment = create_stock_adjustment(
            business=self.business,
            store=self.store,
            reason=StockAdjustment.REASON_STOCKTAKE,
            user=self.owner,
        )

        response = self.client.post(
            reverse("inventory:stock_adjustment_confirm", kwargs={"pk": adjustment.pk}),
            data={"confirm": "on"},
        )

        self.assertEqual(response.status_code, 403)

    def test_unauthenticated_user_is_redirected_from_dashboard(self):
        """Sin login, el dashboard de inventory debe redirigir a login."""
        response = self.client.get(reverse("inventory:dashboard"))

        self.assertEqual(response.status_code, 302)
        self.assertIn("/users/login/", response.url)

    def test_item_list_only_shows_items_from_current_business(self):
        """Listado de items debe respetar aislamiento por negocio."""
        self.login_as(self.owner)

        create_inventory_item(
            business=self.business,
            store=self.store,
            product=self.product,
        )
        create_inventory_item(
            business=self.other_business,
            store=self.other_store,
            product=self.other_product,
        )

        response = self.client.get(reverse("inventory:item_list"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.context["inventory_items"]), 1)

    def test_owner_can_update_inventory_item_settings(self):
        """Owner debe poder editar configuracion de item sin tocar stock."""
        self.login_as(self.owner)

        item = create_inventory_item(
            business=self.business,
            store=self.store,
            product=self.product,
            minimum_stock=Decimal("1.000"),
        )

        response = self.client.post(
            reverse("inventory:item_update", kwargs={"pk": item.pk}),
            data={
                "minimum_stock": "3.000",
                "maximum_stock": "30.000",
                "location": "Almacen 2",
                "is_active": "on",
            },
        )

        item.refresh_from_db()
        self.assertRedirects(
            response,
            reverse("inventory:item_detail", kwargs={"pk": item.pk}),
            fetch_redirect_response=False,
        )
        self.assertEqual(item.minimum_stock, Decimal("3.000"))
        self.assertEqual(item.location, "Almacen 2")

    def test_owner_can_load_initial_stock_from_view(self):
        """POST de stock inicial debe crear movimiento inicial y actualizar stock."""
        self.login_as(self.owner)

        item = create_inventory_item(
            business=self.business,
            store=self.store,
            product=self.product,
            current_stock=Decimal("0.000"),
        )

        response = self.client.post(
            reverse("inventory:item_initial_stock", kwargs={"pk": item.pk}),
            data={
                "quantity": "5.000",
                "unit_cost": "1.50",
                "reason": "Apertura",
                "notes": "Carga inicial",
            },
        )

        item.refresh_from_db()
        self.assertRedirects(
            response,
            reverse("inventory:item_detail", kwargs={"pk": item.pk}),
            fetch_redirect_response=False,
        )
        self.assertEqual(item.current_stock, Decimal("5.000"))
        self.assertTrue(
            StockMovement.objects.filter(
                inventory_item=item,
                movement_type=StockMovement.TYPE_INITIAL,
            ).exists()
        )

    def test_owner_can_create_adjustment_and_line_from_views(self):
        """Debe permitir crear cabecera de ajuste y luego una linea."""
        self.login_as(self.owner)

        item = create_inventory_item(
            business=self.business,
            store=self.store,
            product=self.product,
            current_stock=Decimal("2.000"),
        )

        create_response = self.client.post(
            reverse("inventory:stock_adjustment_create"),
            data={
                "store": self.store.pk,
                "reason": StockAdjustment.REASON_STOCKTAKE,
                "notes": "Ajuste semanal",
            },
        )

        adjustment = StockAdjustment.objects.latest("id")
        self.assertRedirects(
            create_response,
            reverse("inventory:stock_adjustment_detail", kwargs={"pk": adjustment.pk}),
            fetch_redirect_response=False,
        )

        line_response = self.client.post(
            reverse(
                "inventory:stock_adjustment_line_create",
                kwargs={"adjustment_pk": adjustment.pk},
            ),
            data={
                "inventory_item": item.pk,
                "counted_stock": "3.000",
                "notes": "Conteo real",
            },
        )

        self.assertRedirects(
            line_response,
            reverse("inventory:stock_adjustment_detail", kwargs={"pk": adjustment.pk}),
            fetch_redirect_response=False,
        )
        self.assertEqual(adjustment.lines.count(), 1)

    def test_owner_can_update_and_delete_adjustment_line_from_views(self):
        """Debe permitir editar y eliminar lineas de ajustes en borrador."""
        self.login_as(self.owner)

        item = create_inventory_item(
            business=self.business,
            store=self.store,
            product=self.product,
            current_stock=Decimal("6.000"),
        )
        adjustment = create_stock_adjustment(
            business=self.business,
            store=self.store,
            reason=StockAdjustment.REASON_STOCKTAKE,
            user=self.owner,
        )
        line = add_stock_adjustment_line(
            adjustment=adjustment,
            inventory_item=item,
            counted_stock=Decimal("7.000"),
        )

        update_response = self.client.post(
            reverse(
                "inventory:stock_adjustment_line_update",
                kwargs={"adjustment_pk": adjustment.pk, "line_pk": line.pk},
            ),
            data={
                "inventory_item": item.pk,
                "counted_stock": "8.000",
                "notes": "Reconteo",
            },
        )

        line.refresh_from_db()
        self.assertRedirects(
            update_response,
            reverse("inventory:stock_adjustment_detail", kwargs={"pk": adjustment.pk}),
            fetch_redirect_response=False,
        )
        self.assertEqual(line.counted_stock, Decimal("8.000"))

        delete_response = self.client.post(
            reverse(
                "inventory:stock_adjustment_line_delete",
                kwargs={"adjustment_pk": adjustment.pk, "line_pk": line.pk},
            ),
        )

        self.assertRedirects(
            delete_response,
            reverse("inventory:stock_adjustment_detail", kwargs={"pk": adjustment.pk}),
            fetch_redirect_response=False,
        )
        self.assertFalse(adjustment.lines.filter(pk=line.pk).exists())

    def test_confirm_adjustment_without_lines_stays_draft(self):
        """Confirmar ajuste sin lineas debe fallar y mantener borrador."""
        self.login_as(self.owner)

        adjustment = create_stock_adjustment(
            business=self.business,
            store=self.store,
            reason=StockAdjustment.REASON_STOCKTAKE,
            user=self.owner,
        )

        response = self.client.post(
            reverse("inventory:stock_adjustment_confirm", kwargs={"pk": adjustment.pk}),
            data={"confirm": "on"},
        )

        adjustment.refresh_from_db()
        self.assertRedirects(
            response,
            reverse("inventory:stock_adjustment_detail", kwargs={"pk": adjustment.pk}),
            fetch_redirect_response=False,
        )
        self.assertEqual(adjustment.status, StockAdjustment.STATUS_DRAFT)
