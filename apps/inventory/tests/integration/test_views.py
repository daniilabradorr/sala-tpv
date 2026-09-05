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
    create_inventory_manager,
    create_inventory_owner,
    create_inventory_product,
    create_inventory_store,
)
from apps.users.tests.factories import create_store_access


@override_settings(LOGIN_URL="/users/login/")
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
        self.assertTemplateUsed(response, "inventory/item_list.html")
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


@override_settings(LOGIN_URL="/users/login/")
class InventoryStoreScopingIntegrationTests(TestCase):
    """Verifica autorización por tienda en todas las superficies de Inventory."""

    password = "testpass123"

    def setUp(self):  # noqa: N802
        self.business = create_business("Business A", "inventory-scope-a")
        self.other_business = create_business("Business B", "inventory-scope-b")
        self.store_a1 = create_inventory_store(
            business=self.business, name="Store A1", code="SCOPEA1"
        )
        self.store_a2 = create_inventory_store(
            business=self.business, name="Store A2", code="SCOPEA2"
        )
        self.store_b = create_inventory_store(
            business=self.other_business, name="Store B", code="SCOPEB"
        )
        self.owner = create_inventory_owner(
            business=self.business, password=self.password
        )
        self.manager = create_inventory_manager(
            business=self.business, password=self.password
        )
        self.cashier = create_inventory_cashier(
            business=self.business, password=self.password
        )
        create_store_access(self.business, self.cashier, self.store_a1)
        self.item_a1 = self._item(self.business, self.store_a1, "Producto A1", "10")
        self.item_a2 = self._item(self.business, self.store_a2, "Producto A2", "2")
        self.item_b = self._item(self.other_business, self.store_b, "Producto B", "8")

    def _item(self, business, store, name, stock, minimum="0"):
        product = create_inventory_product(business=business, name=name)
        return create_inventory_item(
            business=business,
            store=store,
            product=product,
            current_stock=Decimal(stock),
            minimum_stock=Decimal(minimum),
        )

    def _movement(self, item):
        is_empty = item.current_stock == 0
        return StockMovement.objects.create(
            business=item.business,
            inventory_item=item,
            store=item.store,
            product=item.product,
            movement_type=(
                StockMovement.TYPE_STOCKTAKE if is_empty else StockMovement.TYPE_INITIAL
            ),
            quantity=Decimal("1") if is_empty else item.current_stock,
            stock_before=Decimal("1") if is_empty else Decimal("0"),
            stock_after=item.current_stock,
            reference_type=StockMovement.REF_MANUAL,
            created_by=self.owner,
        )

    def _adjustment(self, store):
        return create_stock_adjustment(
            business=self.business,
            store=store,
            reason=StockAdjustment.REASON_STOCKTAKE,
            user=self.owner,
        )

    def login_as(self, user):
        self.assertTrue(self.client.login(email=user.email, password=self.password))

    def test_item_lists_follow_role_store_scope(self):
        for user, expected in (
            (self.owner, {self.item_a1, self.item_a2}),
            (self.manager, {self.item_a1, self.item_a2}),
            (self.cashier, {self.item_a1}),
        ):
            self.login_as(user)
            response = self.client.get(reverse("inventory:item_list"))
            self.assertEqual(response.status_code, 200)
            self.assertSetEqual(set(response.context["inventory_items"]), expected)
            self.assertNotIn(self.item_b, response.context["inventory_items"])
            self.client.logout()

    def test_cashier_item_details_are_scoped(self):
        self.login_as(self.cashier)
        allowed = self.client.get(
            reverse("inventory:item_detail", kwargs={"pk": self.item_a1.pk})
        )
        denied = self.client.get(
            reverse("inventory:item_detail", kwargs={"pk": self.item_a2.pk})
        )
        cross_business = self.client.get(
            reverse("inventory:item_detail", kwargs={"pk": self.item_b.pk})
        )
        self.assertEqual(allowed.status_code, 200)
        self.assertEqual(denied.status_code, 404)
        self.assertEqual(cross_business.status_code, 404)

    def test_movement_lists_and_details_follow_store_scope(self):
        movement_a1 = self._movement(self.item_a1)
        movement_a2 = self._movement(self.item_a2)
        self.login_as(self.cashier)
        response = self.client.get(reverse("inventory:stock_movement_list"))
        self.assertSetEqual(set(response.context["stock_movements"]), {movement_a1})
        self.assertEqual(
            self.client.get(
                reverse(
                    "inventory:stock_movement_detail", kwargs={"pk": movement_a1.pk}
                )
            ).status_code,
            200,
        )
        self.assertEqual(
            self.client.get(
                reverse(
                    "inventory:stock_movement_detail", kwargs={"pk": movement_a2.pk}
                )
            ).status_code,
            404,
        )
        self.client.logout()
        self.login_as(self.manager)
        response = self.client.get(reverse("inventory:stock_movement_list"))
        self.assertSetEqual(
            set(response.context["stock_movements"]), {movement_a1, movement_a2}
        )

    def test_adjustment_lists_and_details_follow_store_scope(self):
        adjustment_a1 = self._adjustment(self.store_a1)
        adjustment_a2 = self._adjustment(self.store_a2)
        self.login_as(self.cashier)
        response = self.client.get(reverse("inventory:stock_adjustment_list"))
        self.assertSetEqual(set(response.context["stock_adjustments"]), {adjustment_a1})
        self.assertEqual(
            self.client.get(
                reverse(
                    "inventory:stock_adjustment_detail",
                    kwargs={"pk": adjustment_a1.pk},
                )
            ).status_code,
            200,
        )
        self.assertEqual(
            self.client.get(
                reverse(
                    "inventory:stock_adjustment_detail",
                    kwargs={"pk": adjustment_a2.pk},
                )
            ).status_code,
            404,
        )
        self.client.logout()
        self.login_as(self.manager)
        response = self.client.get(reverse("inventory:stock_adjustment_list"))
        self.assertSetEqual(
            set(response.context["stock_adjustments"]),
            {adjustment_a1, adjustment_a2},
        )

    def test_cashier_dashboard_aggregates_only_accessible_stores(self):
        self.item_a1.minimum_stock = Decimal("5")
        self.item_a1.save(update_fields=["minimum_stock", "updated_at"])
        self.item_a2.minimum_stock = Decimal("3")
        self.item_a2.save(update_fields=["minimum_stock", "updated_at"])
        self._item(self.business, self.store_a2, "Producto A2 sin stock", "0")
        movement_a1 = self._movement(self.item_a1)
        movement_a2 = self._movement(self.item_a2)
        adjustment_a1 = self._adjustment(self.store_a1)
        adjustment_a2 = self._adjustment(self.store_a2)
        self.login_as(self.cashier)

        response = self.client.get(reverse("inventory:dashboard"))

        self.assertEqual(response.context["total_products_with_stock"], 1)
        self.assertEqual(response.context["low_stock_products"], 0)
        self.assertEqual(response.context["out_of_stock_products"], 0)
        self.assertSequenceEqual(
            list(response.context["latest_movements"]), [movement_a1]
        )
        self.assertSequenceEqual(
            list(response.context["latest_adjustments"]), [adjustment_a1]
        )
        self.assertNotIn(movement_a2, response.context["latest_movements"])
        self.assertNotIn(adjustment_a2, response.context["latest_adjustments"])

    def test_filter_store_querysets_follow_role_scope(self):
        routes = (
            ("inventory:item_list", "form"),
            ("inventory:stock_movement_list", "form"),
            ("inventory:stock_adjustment_list", "form"),
        )
        for user, expected in (
            (self.owner, {self.store_a1, self.store_a2}),
            (self.manager, {self.store_a1, self.store_a2}),
            (self.cashier, {self.store_a1}),
        ):
            self.login_as(user)
            for route, context_name in routes:
                response = self.client.get(reverse(route))
                stores = response.context[context_name].fields["store"].queryset
                self.assertSetEqual(set(stores), expected)
                self.assertNotIn(self.store_b, stores)
            self.client.logout()

    def test_cashier_cannot_use_any_inventory_mutation(self):
        adjustment = self._adjustment(self.store_a1)
        line = add_stock_adjustment_line(
            adjustment=adjustment,
            inventory_item=self.item_a1,
            counted_stock=self.item_a1.current_stock,
        )
        self.login_as(self.cashier)
        endpoints = (
            reverse("inventory:item_create"),
            reverse("inventory:item_update", kwargs={"pk": self.item_a1.pk}),
            reverse("inventory:item_initial_stock", kwargs={"pk": self.item_a1.pk}),
            reverse("inventory:stock_adjustment_create"),
            reverse(
                "inventory:stock_adjustment_line_create",
                kwargs={"adjustment_pk": adjustment.pk},
            ),
            reverse(
                "inventory:stock_adjustment_line_update",
                kwargs={"adjustment_pk": adjustment.pk, "line_pk": line.pk},
            ),
            reverse(
                "inventory:stock_adjustment_line_delete",
                kwargs={"adjustment_pk": adjustment.pk, "line_pk": line.pk},
            ),
            reverse("inventory:stock_adjustment_confirm", kwargs={"pk": adjustment.pk}),
            reverse("inventory:stock_adjustment_cancel", kwargs={"pk": adjustment.pk}),
        )
        for endpoint in endpoints:
            with self.subTest(endpoint=endpoint):
                self.assertEqual(self.client.post(endpoint).status_code, 403)

    def test_initial_stock_action_visibility(self):
        empty_item = self._item(self.business, self.store_a1, "Producto inicial", "0")
        for user in (self.owner, self.manager):
            self.login_as(user)
            response = self.client.get(
                reverse("inventory:item_detail", kwargs={"pk": empty_item.pk})
            )
            self.assertIs(response.context["can_load_initial_stock"], True)
            self.assertContains(response, "Cargar stock inicial")
            self.client.logout()
        self._movement(empty_item)
        self.login_as(self.owner)
        response = self.client.get(
            reverse("inventory:item_detail", kwargs={"pk": empty_item.pk})
        )
        self.assertIs(response.context["can_load_initial_stock"], False)
        self.client.logout()
        self.login_as(self.cashier)
        response = self.client.get(
            reverse("inventory:item_detail", kwargs={"pk": empty_item.pk})
        )
        self.assertIs(response.context["can_load_initial_stock"], False)
        self.assertNotContains(response, "Cargar stock inicial")

    def test_post_only_action_endpoints_reject_get(self):
        adjustment = self._adjustment(self.store_a1)
        line = add_stock_adjustment_line(
            adjustment=adjustment,
            inventory_item=self.item_a1,
            counted_stock=self.item_a1.current_stock,
        )
        self.login_as(self.owner)
        endpoints = (
            reverse(
                "inventory:stock_adjustment_line_delete",
                kwargs={"adjustment_pk": adjustment.pk, "line_pk": line.pk},
            ),
            reverse("inventory:stock_adjustment_confirm", kwargs={"pk": adjustment.pk}),
            reverse("inventory:stock_adjustment_cancel", kwargs={"pk": adjustment.pk}),
        )
        for endpoint in endpoints:
            with self.subTest(endpoint=endpoint):
                self.assertEqual(self.client.get(endpoint).status_code, 405)
