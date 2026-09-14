from decimal import Decimal
from uuid import uuid4

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone

from apps.business_config.models import POSSettings
from apps.catalog.models import Product
from apps.core.models import Business
from apps.inventory.models import InventoryItem, StockMovement
from apps.purchases.models import (
    Purchase,
    PurchaseLine,
    PurchaseReceipt,
    PurchaseReceiptLine,
    PurchaseStatusChoices,
    Supplier,
)
from apps.purchases.services import (
    add_purchase_line,
    calculate_purchase_line_amounts,
    cancel_purchase,
    create_purchase,
    create_supplier,
    delete_purchase_line,
    order_purchase,
    register_purchase_receipt,
    update_purchase_header,
    update_purchase_line,
    update_supplier,
)
from apps.stores.models import Store
from apps.users.models import RoleChoices, UserStoreAccess
from apps.users.tests.factories import create_user


class PurchasesServiceTests(TestCase):
    def setUp(self):  # noqa: N802
        self.business = self.make_business("Principal")
        self.other_business = self.make_business("Otro")
        self.store = self.make_store(self.business, "MAIN")
        self.other_store = self.make_store(self.other_business, "OTHER")
        self.owner = self.make_user(self.business, RoleChoices.OWNER)
        self.manager = self.make_user(self.business, RoleChoices.MANAGER)
        self.manager_without_access = self.make_user(self.business, RoleChoices.MANAGER)
        self.cashier = self.make_user(self.business, RoleChoices.CASHIER)
        self.other_owner = self.make_user(self.other_business, RoleChoices.OWNER)
        UserStoreAccess.objects.create(
            business=self.business, user=self.manager, store=self.store
        )
        self.supplier = Supplier.objects.create(
            business=self.business, name="Proveedor"
        )
        self.other_supplier = Supplier.objects.create(
            business=self.other_business, name="Proveedor ajeno"
        )
        self.product = self.make_product(self.business, "Café", "CAFE")
        self.other_product = self.make_product(self.other_business, "Té", "TE")
        POSSettings.objects.create(business=self.business, enable_stock_control=True)

    @staticmethod
    def make_business(name):
        return Business.objects.create(name=name, slug=f"{name.lower()}-{uuid4().hex}")

    @staticmethod
    def make_store(business, code, *, is_active=True):
        return Store.objects.create(
            business=business,
            name=f"Tienda {code}-{uuid4().hex[:6]}",
            code=f"{code}{uuid4().hex[:5]}".upper(),
            is_active=is_active,
        )

    @staticmethod
    def make_user(business, role):
        return create_user(
            business=business,
            email=f"{uuid4().hex}@services.test",
            role=role,
        )

    @staticmethod
    def make_product(
        business, name, sku, *, is_active=True, track_stock=True, cost_price="3.00"
    ):
        return Product.objects.create(
            business=business,
            name=name,
            sku=f"{sku}-{uuid4().hex[:6]}",
            barcode=f"9{uuid4().int % 10**12:012d}",
            base_price=Decimal("4.00"),
            cost_price=Decimal(cost_price),
            unit=Product.UNIT_KG,
            is_active=is_active,
            track_stock=track_stock,
        )

    def make_purchase(self, *, user=None, store=None, supplier=None):
        return create_purchase(
            business=self.business,
            store=store or self.store,
            supplier=supplier or self.supplier,
            created_by=user or self.owner,
        )

    def add_line(self, purchase, **overrides):
        values = {
            "business": self.business,
            "purchase": purchase,
            "product": self.product,
            "quantity": Decimal("2"),
            "unit_cost": Decimal("5"),
            "tax_rate": Decimal("21"),
            "user": self.owner,
        }
        values.update(overrides)
        return add_purchase_line(**values)

    def test_supplier_permissions_normalization_and_deactivation(self):
        owner_supplier = create_supplier(
            business=self.business,
            user=self.owner,
            name="  Norte  ",
            tax_identifier=" b123 ",
            email=" SALES@EXAMPLE.COM ",
        )
        manager_supplier = create_supplier(
            business=self.business, user=self.manager, name="Manager supplier"
        )
        self.assertEqual(owner_supplier.name, "Norte")
        self.assertEqual(owner_supplier.tax_identifier, "B123")
        self.assertEqual(owner_supplier.email, "sales@example.com")
        self.assertTrue(manager_supplier.pk)

        with self.assertRaises(ValidationError):
            create_supplier(business=self.business, user=self.cashier, name="No")
        with self.assertRaises(ValidationError):
            create_supplier(business=self.business, user=self.other_owner, name="No")

        updated = update_supplier(
            business=self.business,
            supplier=owner_supplier,
            user=self.owner,
            email=" NEW@EXAMPLE.COM ",
            is_active=False,
        )
        self.assertFalse(updated.is_active)
        self.assertEqual(updated.email, "new@example.com")
        self.assertTrue(Supplier.objects.filter(pk=updated.pk).exists())

    def test_update_supplier_is_tenant_scoped(self):
        with self.assertRaises(ValidationError):
            update_supplier(
                business=self.business,
                supplier=self.other_supplier,
                user=self.owner,
                name="Secuestrado",
            )
        self.other_supplier.refresh_from_db()
        self.assertEqual(self.other_supplier.name, "Proveedor ajeno")

    def test_create_purchase_permissions_relations_and_defaults(self):
        owner_purchase = self.make_purchase()
        manager_purchase = self.make_purchase(user=self.manager)
        for purchase in (owner_purchase, manager_purchase):
            self.assertEqual(purchase.status, PurchaseStatusChoices.DRAFT)
            self.assertIsNone(purchase.ordered_at)
            self.assertEqual(purchase.subtotal_amount, Decimal("0.00"))
            self.assertEqual(purchase.tax_amount, Decimal("0.00"))
            self.assertEqual(purchase.total_amount, Decimal("0.00"))

        for user in (self.manager_without_access, self.cashier):
            with self.subTest(role=user.role), self.assertRaises(ValidationError):
                self.make_purchase(user=user)
        with self.assertRaises(ValidationError):
            self.make_purchase(store=self.other_store)
        with self.assertRaises(ValidationError):
            self.make_purchase(supplier=self.other_supplier)

    def test_create_purchase_rejects_inactive_store_and_supplier(self):
        inactive_store = self.make_store(self.business, "OFF", is_active=False)
        inactive_supplier = Supplier.objects.create(
            business=self.business, name="Inactivo", is_active=False
        )
        with self.assertRaises(ValidationError):
            self.make_purchase(store=inactive_store)
        with self.assertRaises(ValidationError):
            self.make_purchase(supplier=inactive_supplier)

    def test_update_header_requires_draft_and_access_to_both_stores(self):
        purchase = self.make_purchase()
        destination = self.make_store(self.business, "DEST")
        updated = update_purchase_header(
            business=self.business,
            purchase=purchase,
            user=self.owner,
            store=destination,
            reference="  REF  ",
            notes="  nota  ",
        )
        self.assertEqual(updated.store, destination)
        self.assertEqual(updated.reference, "REF")
        self.assertEqual(updated.notes, "nota")

        inaccessible = self.make_purchase()
        with self.assertRaises(ValidationError):
            update_purchase_header(
                business=self.business,
                purchase=inaccessible,
                user=self.manager_without_access,
                store=destination,
            )
        inaccessible.status = PurchaseStatusChoices.ORDERED
        inaccessible.ordered_at = updated.updated_at
        inaccessible.save()
        with self.assertRaises(ValidationError):
            update_purchase_header(
                business=self.business,
                purchase=inaccessible,
                user=self.owner,
                reference="no",
            )

    def test_line_calculation_rounds_half_up_exactly(self):
        calculated = calculate_purchase_line_amounts(
            quantity="1.2345", unit_cost="2.345", tax_rate="10.005"
        )
        self.assertEqual(calculated["quantity_ordered"], Decimal("1.235"))
        self.assertEqual(calculated["unit_cost"], Decimal("2.35"))
        self.assertEqual(calculated["tax_rate"], Decimal("10.01"))
        self.assertEqual(calculated["line_subtotal"], Decimal("2.90"))
        self.assertEqual(calculated["tax_amount"], Decimal("0.29"))
        self.assertEqual(calculated["line_total"], Decimal("3.19"))

    def test_line_calculation_rejects_invalid_values(self):
        invalid = (
            {"quantity": "0", "unit_cost": "1", "tax_rate": "0"},
            {"quantity": "-1", "unit_cost": "1", "tax_rate": "0"},
            {"quantity": "1", "unit_cost": "-0.01", "tax_rate": "0"},
            {"quantity": "1", "unit_cost": "1", "tax_rate": "-0.01"},
        )
        for values in invalid:
            with self.subTest(values=values), self.assertRaises(ValidationError):
                calculate_purchase_line_amounts(**values)

    def test_add_line_snapshots_and_recalculates_and_allows_duplicates(self):
        purchase = self.make_purchase()
        first = self.add_line(
            purchase,
            quantity="1.2345",
            unit_cost="2.345",
            tax_rate="10.005",
        )
        second = self.add_line(purchase, unit_cost="1.00", tax_rate="0")
        self.assertEqual(first.product_name, self.product.name)
        self.assertEqual(first.sku, self.product.sku.strip().upper())
        self.assertEqual(first.unit, self.product.unit)
        self.assertEqual(first.quantity_received, Decimal("0.000"))
        self.assertNotEqual(first.pk, second.pk)
        purchase.refresh_from_db()
        self.assertEqual(purchase.lines.count(), 2)
        self.assertEqual(purchase.subtotal_amount, Decimal("4.90"))
        self.assertEqual(purchase.tax_amount, Decimal("0.29"))
        self.assertEqual(purchase.total_amount, Decimal("5.19"))

    def test_add_line_rejects_cross_tenant_and_inactive_products(self):
        purchase = self.make_purchase()
        inactive = self.make_product(self.business, "Inactivo", "OFF", is_active=False)
        for product in (self.other_product, inactive):
            with self.subTest(product=product), self.assertRaises(ValidationError):
                self.add_line(purchase, product=product)

    def test_update_line_recalculates_without_changing_snapshot_or_received(self):
        purchase = self.make_purchase()
        line = self.add_line(purchase)
        snapshot = (line.product_id, line.product_name, line.sku, line.unit)
        PurchaseLine.objects.filter(pk=line.pk).update(
            quantity_received=Decimal("0.500")
        )
        updated = update_purchase_line(
            business=self.business,
            purchase=purchase,
            line=line,
            quantity="3",
            unit_cost="2",
            tax_rate="10",
            user=self.owner,
        )
        self.assertEqual(
            (updated.product_id, updated.product_name, updated.sku, updated.unit),
            snapshot,
        )
        self.assertEqual(updated.quantity_received, Decimal("0.500"))
        purchase.refresh_from_db()
        self.assertEqual(purchase.total_amount, Decimal("6.60"))

    def test_update_line_rejects_wrong_purchase_ordered_and_missing_access(self):
        purchase = self.make_purchase()
        other_purchase = self.make_purchase()
        line = self.add_line(purchase)
        common = {
            "business": self.business,
            "line": line,
            "quantity": "1",
            "unit_cost": "1",
            "tax_rate": "0",
        }
        with self.assertRaises(ValidationError):
            update_purchase_line(purchase=other_purchase, user=self.owner, **common)
        with self.assertRaises(ValidationError):
            update_purchase_line(
                purchase=purchase, user=self.manager_without_access, **common
            )
        order_purchase(business=self.business, purchase=purchase, ordered_by=self.owner)
        with self.assertRaises(ValidationError):
            update_purchase_line(purchase=purchase, user=self.owner, **common)

    def test_delete_line_recalculates_and_enforces_state_and_tenant(self):
        purchase = self.make_purchase()
        first = self.add_line(purchase)
        second = self.add_line(purchase, unit_cost="1", tax_rate="0")
        delete_purchase_line(
            business=self.business, purchase=purchase, line=second, user=self.owner
        )
        purchase.refresh_from_db()
        self.assertEqual(purchase.total_amount, first.line_total)
        with self.assertRaises(ValidationError):
            delete_purchase_line(
                business=self.other_business,
                purchase=purchase,
                line=first,
                user=self.other_owner,
            )
        order_purchase(business=self.business, purchase=purchase, ordered_by=self.owner)
        with self.assertRaises(ValidationError):
            delete_purchase_line(
                business=self.business,
                purchase=purchase,
                line=first,
                user=self.owner,
            )

    def test_order_valid_purchase_and_retry_are_idempotent(self):
        purchase = self.make_purchase()
        self.add_line(purchase, unit_cost="0", tax_rate="150")
        ordered = order_purchase(
            business=self.business, purchase=purchase, ordered_by=self.owner
        )
        first_ordered_at = ordered.ordered_at
        retried = order_purchase(
            business=self.business, purchase=purchase, ordered_by=self.owner
        )
        self.assertEqual(retried.status, PurchaseStatusChoices.ORDERED)
        self.assertIsNotNone(retried.ordered_at)
        self.assertEqual(retried.ordered_at, first_ordered_at)

    def test_order_rejects_missing_lines_and_inactive_relations(self):
        empty = self.make_purchase()
        with self.assertRaises(ValidationError):
            order_purchase(
                business=self.business, purchase=empty, ordered_by=self.owner
            )

        cases = ("supplier", "store", "product")
        for relation in cases:
            purchase = self.make_purchase()
            self.add_line(purchase)
            obj = getattr(purchase, relation) if relation != "product" else self.product
            obj.is_active = False
            obj.save()
            with self.subTest(relation=relation), self.assertRaises(ValidationError):
                order_purchase(
                    business=self.business, purchase=purchase, ordered_by=self.owner
                )
            obj.is_active = True
            obj.save()

    def test_order_rejects_tampering_cashier_no_access_and_wrong_tenant(self):
        purchase = self.make_purchase()
        line = self.add_line(purchase)
        PurchaseLine.objects.filter(pk=line.pk).update(line_total=Decimal("99.00"))
        with self.assertRaises(ValidationError):
            order_purchase(
                business=self.business, purchase=purchase, ordered_by=self.owner
            )
        PurchaseLine.objects.filter(pk=line.pk).update(line_total=line.line_total)
        for actor in (self.cashier, self.manager_without_access):
            with self.subTest(actor=actor), self.assertRaises(ValidationError):
                order_purchase(
                    business=self.business, purchase=purchase, ordered_by=actor
                )
        with self.assertRaises(ValidationError):
            order_purchase(
                business=self.other_business,
                purchase=purchase,
                ordered_by=self.other_owner,
            )

    def test_cancel_draft_ordered_and_retry(self):
        draft = self.make_purchase()
        cancelled = cancel_purchase(
            business=self.business, purchase=draft, cancelled_by=self.owner
        )
        self.assertEqual(cancelled.status, PurchaseStatusChoices.CANCELLED)
        retried = cancel_purchase(
            business=self.business, purchase=draft, cancelled_by=self.owner
        )
        self.assertEqual(retried.status, PurchaseStatusChoices.CANCELLED)

        ordered = self.make_purchase()
        self.add_line(ordered)
        ordered = order_purchase(
            business=self.business, purchase=ordered, ordered_by=self.owner
        )
        ordered_at = ordered.ordered_at
        cancelled = cancel_purchase(
            business=self.business, purchase=ordered, cancelled_by=self.owner
        )
        self.assertEqual(cancelled.status, PurchaseStatusChoices.CANCELLED)
        self.assertEqual(cancelled.ordered_at, ordered_at)

    def test_cancel_rejects_received_states_receipts_and_received_quantity(self):
        for status in (
            PurchaseStatusChoices.PARTIALLY_RECEIVED,
            PurchaseStatusChoices.RECEIVED,
        ):
            purchase = Purchase.objects.create(
                business=self.business,
                store=self.store,
                supplier=self.supplier,
                created_by=self.owner,
                status=status,
                ordered_at=self.owner.date_joined,
            )
            with self.subTest(status=status), self.assertRaises(ValidationError):
                cancel_purchase(
                    business=self.business,
                    purchase=purchase,
                    cancelled_by=self.owner,
                )

        purchase = self.make_purchase()
        line = self.add_line(purchase)
        ordered = order_purchase(
            business=self.business, purchase=purchase, ordered_by=self.owner
        )
        PurchaseReceipt.objects.create(
            business=self.business,
            store=self.store,
            purchase=ordered,
            received_by=self.owner,
            idempotency_key=uuid4(),
            idempotency_fingerprint="a" * 64,
        )
        with self.assertRaises(ValidationError):
            cancel_purchase(
                business=self.business, purchase=ordered, cancelled_by=self.owner
            )
        ordered.receipts.all().delete()
        PurchaseLine.objects.filter(pk=line.pk).update(
            quantity_received=Decimal("0.001")
        )
        with self.assertRaises(ValidationError):
            cancel_purchase(
                business=self.business, purchase=ordered, cancelled_by=self.owner
            )

    def test_cancel_allows_inactive_store_but_enforces_permission_and_tenant(self):
        purchase = self.make_purchase()
        self.store.is_active = False
        self.store.save()
        cancelled = cancel_purchase(
            business=self.business, purchase=purchase, cancelled_by=self.manager
        )
        self.assertEqual(cancelled.status, PurchaseStatusChoices.CANCELLED)

        another = Purchase.objects.create(
            business=self.business,
            store=self.store,
            supplier=self.supplier,
            created_by=self.owner,
        )
        for actor in (self.cashier, self.manager_without_access):
            with self.subTest(actor=actor), self.assertRaises(ValidationError):
                cancel_purchase(
                    business=self.business, purchase=another, cancelled_by=actor
                )
        with self.assertRaises(ValidationError):
            cancel_purchase(
                business=self.other_business,
                purchase=another,
                cancelled_by=self.other_owner,
            )

    def test_purchase_lifecycle_is_stock_neutral(self):
        inventory = InventoryItem.objects.create(
            business=self.business,
            store=self.store,
            product=self.product,
            current_stock=Decimal("7.000"),
        )
        movement_count = StockMovement.objects.count()
        purchase = self.make_purchase()
        self.add_line(purchase)
        order_purchase(business=self.business, purchase=purchase, ordered_by=self.owner)
        cancel_purchase(
            business=self.business, purchase=purchase, cancelled_by=self.owner
        )
        inventory.refresh_from_db()
        self.product.refresh_from_db()
        self.assertEqual(inventory.current_stock, Decimal("7.000"))
        self.assertEqual(StockMovement.objects.count(), movement_count)
        self.assertEqual(self.product.cost_price, Decimal("3.00"))

    def receive(self, purchase, lines, *, key=None, user=None, **kwargs):
        return register_purchase_receipt(
            business=self.business,
            purchase=purchase,
            received_by=user or self.owner,
            lines=lines,
            idempotency_key=key or uuid4(),
            **kwargs,
        )

    def test_complete_receipt_integrates_inventory_and_historical_cost(self):
        purchase = self.make_purchase()
        line = self.add_line(purchase, quantity="5", unit_cost="5")
        order_purchase(business=self.business, purchase=purchase, ordered_by=self.owner)
        inventory = InventoryItem.objects.create(
            business=self.business,
            store=self.store,
            product=self.product,
            current_stock=Decimal("2.000"),
        )
        occurred_at = timezone.now().replace(microsecond=0)

        receipt = self.receive(
            purchase,
            [{"purchase_line": line, "quantity_received": "5"}],
            received_at=occurred_at,
        )

        line.refresh_from_db()
        purchase.refresh_from_db()
        inventory.refresh_from_db()
        self.product.refresh_from_db()
        receipt_line = PurchaseReceiptLine.objects.get(receipt=receipt)
        movement = StockMovement.objects.get(purchase_receipt_line=receipt_line)
        self.assertEqual(line.quantity_received, Decimal("5.000"))
        self.assertEqual(purchase.status, PurchaseStatusChoices.RECEIVED)
        self.assertEqual(inventory.current_stock, Decimal("7.000"))
        self.assertEqual(movement.stock_before, Decimal("2.000"))
        self.assertEqual(movement.stock_after, Decimal("7.000"))
        self.assertEqual(movement.unit_cost, line.unit_cost)
        self.assertEqual(movement.occurred_at, occurred_at)
        self.assertEqual(movement.purchase, purchase)
        self.assertEqual(movement.purchase_line, line)
        self.assertEqual(movement.purchase_receipt, receipt)
        self.assertEqual(movement.purchase_receipt_line, receipt_line)
        self.assertEqual(self.product.cost_price, Decimal("3.00"))
        self.assertRegex(receipt.idempotency_fingerprint, r"^[0-9a-f]{64}$")

    def test_partial_then_final_receipt_is_idempotent(self):
        purchase = self.make_purchase()
        line = self.add_line(purchase, quantity="10")
        order_purchase(business=self.business, purchase=purchase, ordered_by=self.owner)
        first_key = uuid4()
        first = self.receive(
            purchase,
            [{"purchase_line": line, "quantity_received": 4}],
            key=first_key,
            notes="primera",
        )
        retry = self.receive(
            purchase,
            [{"purchase_line": line, "quantity_received": Decimal("4.000")}],
            key=first_key,
            notes="ignorada",
        )
        self.assertEqual(retry.pk, first.pk)
        line.refresh_from_db()
        purchase.refresh_from_db()
        self.assertEqual(line.quantity_received, Decimal("4.000"))
        self.assertEqual(purchase.status, PurchaseStatusChoices.PARTIALLY_RECEIVED)

        self.receive(purchase, [{"purchase_line": line, "quantity_received": "6.0"}])
        line.refresh_from_db()
        purchase.refresh_from_db()
        self.assertEqual(line.quantity_received, Decimal("10.000"))
        self.assertEqual(purchase.status, PurchaseStatusChoices.RECEIVED)
        self.assertEqual(PurchaseReceipt.objects.filter(purchase=purchase).count(), 2)
        self.assertEqual(StockMovement.objects.filter(purchase=purchase).count(), 2)
        self.assertEqual(
            line.quantity_received,
            sum(line.receipt_lines.values_list("quantity_received", flat=True)),
        )

    def test_receipt_rejects_invalid_payload_over_receive_and_conflict(self):
        purchase = self.make_purchase()
        line = self.add_line(purchase, quantity="3")
        order_purchase(business=self.business, purchase=purchase, ordered_by=self.owner)
        for payload in (
            None,
            [],
            [
                {"purchase_line": line, "quantity_received": 1},
                {"purchase_line": line, "quantity_received": 1},
            ],
        ):
            with self.subTest(payload=payload), self.assertRaises(ValidationError):
                self.receive(purchase, payload)
        key = uuid4()
        self.receive(
            purchase, [{"purchase_line": line, "quantity_received": "2"}], key=key
        )
        with self.assertRaises(ValidationError) as context:
            self.receive(
                purchase,
                [{"purchase_line": line, "quantity_received": "1"}],
                key=key,
            )
        self.assertIn("idempotency_key", context.exception.message_dict)
        with self.assertRaises(ValidationError):
            self.receive(purchase, [{"purchase_line": line, "quantity_received": "2"}])
        self.assertEqual(PurchaseReceipt.objects.filter(purchase=purchase).count(), 1)

    def test_non_stock_receipts_and_inactive_parties(self):
        purchase = self.make_purchase()
        line = self.add_line(purchase)
        order_purchase(business=self.business, purchase=purchase, ordered_by=self.owner)
        self.product.is_active = False
        self.product.save()
        self.supplier.is_active = False
        self.supplier.save()
        self.receive(purchase, [{"purchase_line": line, "quantity_received": "2"}])
        self.assertEqual(StockMovement.objects.filter(purchase=purchase).count(), 1)
        self.supplier.is_active = True
        self.supplier.save()

        product = self.make_product(
            self.business, "Servicio", "SERV", track_stock=False
        )
        second = self.make_purchase()
        second_line = self.add_line(second, product=product)
        order_purchase(business=self.business, purchase=second, ordered_by=self.owner)
        self.receive(second, [{"purchase_line": second_line, "quantity_received": "2"}])
        self.assertFalse(InventoryItem.objects.filter(product=product).exists())

        POSSettings.objects.filter(business=self.business).update(
            enable_stock_control=False
        )
        third_product = self.make_product(self.business, "Sin stock", "OFF")
        third = self.make_purchase()
        third_line = self.add_line(third, product=third_product)
        order_purchase(business=self.business, purchase=third, ordered_by=self.owner)
        self.receive(third, [{"purchase_line": third_line, "quantity_received": "2"}])
        self.assertFalse(InventoryItem.objects.filter(product=third_product).exists())
        self.assertFalse(StockMovement.objects.filter(purchase=third).exists())

    def test_inventory_resolution_failure_rolls_back_all_lines(self):
        second_product = self.make_product(self.business, "Té", "TEA")
        purchase = self.make_purchase()
        first_line = self.add_line(purchase)
        second_line = self.add_line(purchase, product=second_product)
        order_purchase(business=self.business, purchase=purchase, ordered_by=self.owner)
        inactive = InventoryItem.objects.create(
            business=self.business,
            store=self.store,
            product=second_product,
            current_stock=Decimal("8.000"),
            is_active=False,
        )
        with self.assertRaises(ValidationError):
            self.receive(
                purchase,
                [
                    {"purchase_line": first_line, "quantity_received": 1},
                    {"purchase_line": second_line, "quantity_received": 1},
                ],
            )
        self.assertFalse(InventoryItem.objects.filter(product=self.product).exists())
        inactive.refresh_from_db()
        first_line.refresh_from_db()
        second_line.refresh_from_db()
        purchase.refresh_from_db()
        self.assertEqual(inactive.current_stock, Decimal("8.000"))
        self.assertEqual(first_line.quantity_received, Decimal("0.000"))
        self.assertEqual(second_line.quantity_received, Decimal("0.000"))
        self.assertEqual(purchase.status, PurchaseStatusChoices.ORDERED)
        self.assertFalse(PurchaseReceipt.objects.filter(purchase=purchase).exists())
        self.assertFalse(StockMovement.objects.filter(purchase=purchase).exists())

    def test_corrupt_historical_aggregate_and_cross_purchase_line_are_rejected(self):
        purchase = self.make_purchase()
        line = self.add_line(purchase)
        order_purchase(business=self.business, purchase=purchase, ordered_by=self.owner)
        PurchaseLine.objects.filter(pk=line.pk).update(quantity_received="1.000")
        with self.assertRaises(ValidationError):
            self.receive(purchase, [{"purchase_line": line, "quantity_received": 1}])

        other = self.make_purchase()
        self.add_line(other)
        order_purchase(business=self.business, purchase=other, ordered_by=self.owner)
        with self.assertRaises(ValidationError):
            self.receive(other, [{"purchase_line": line, "quantity_received": 1}])
        self.assertFalse(PurchaseReceipt.objects.exists())
