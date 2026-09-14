from decimal import Decimal
from uuid import uuid4

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone

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
from apps.stores.models import Store
from apps.users.models import RoleChoices
from apps.users.tests.factories import create_user


class PurchasesModelTests(TestCase):
    def setUp(self):  # noqa: N802
        self.business = self.create_business("Principal")
        self.other_business = self.create_business("Otro")
        self.store = self.create_store(self.business)
        self.other_store = self.create_store(self.other_business)
        self.user = self.create_business_user(self.business)
        self.other_user = self.create_business_user(self.other_business)
        self.supplier = Supplier.objects.create(
            business=self.business,
            name="  Distribuciones Norte  ",
            tax_identifier=" b12345678 ",
        )
        self.other_supplier = Supplier.objects.create(
            business=self.other_business, name="Proveedor externo"
        )
        self.product = self.create_product(self.business, "Café")
        self.other_product = self.create_product(self.other_business, "Té")

    @staticmethod
    def create_business(name):
        return Business.objects.create(name=name, slug=f"{name.lower()}-{uuid4().hex}")

    @staticmethod
    def create_store(business):
        suffix = uuid4().hex[:8]
        return Store.objects.create(
            business=business, name=f"Tienda {suffix}", code=suffix.upper()
        )

    @staticmethod
    def create_business_user(business):
        return create_user(
            business=business,
            email=f"{uuid4().hex}@purchases.test",
            role=RoleChoices.OWNER,
        )

    @staticmethod
    def create_product(business, name):
        suffix = uuid4().hex[:10].upper()
        return Product.objects.create(
            business=business,
            name=name,
            sku=f"SKU_{suffix}",
            barcode=f"9{uuid4().int % 10**12:012d}",
            base_price=Decimal("2.00"),
            cost_price=Decimal("1.00"),
            unit=Product.UNIT_UNIDAD,
        )

    def create_purchase(self, **overrides):
        values = {
            "business": self.business,
            "store": self.store,
            "supplier": self.supplier,
            "created_by": self.user,
        }
        values.update(overrides)
        return Purchase.objects.create(**values)

    def create_line(self, purchase=None, product=None, **overrides):
        product = product or self.product
        values = {
            "business": self.business,
            "purchase": purchase or self.create_purchase(),
            "product": product,
            "product_name": product.name,
            "sku": product.sku,
            "unit": product.unit,
            "quantity_ordered": Decimal("10.000"),
            "unit_cost": Decimal("1.00"),
        }
        values.update(overrides)
        return PurchaseLine.objects.create(**values)

    def create_ordered_purchase(self, **overrides):
        return self.create_purchase(
            status=PurchaseStatusChoices.ORDERED,
            ordered_at=timezone.now(),
            **overrides,
        )

    def create_receipt(self, purchase=None, **overrides):
        purchase = purchase or self.create_ordered_purchase()
        values = {
            "business": purchase.business,
            "store": purchase.store,
            "purchase": purchase,
            "received_by": self.user,
            "idempotency_key": uuid4(),
            "idempotency_fingerprint": "a" * 64,
        }
        values.update(overrides)
        return PurchaseReceipt.objects.create(**values)

    def test_supplier_is_created_and_normalized_without_cross_business_uniqueness(self):
        self.assertEqual(self.supplier.name, "Distribuciones Norte")
        self.assertEqual(self.supplier.tax_identifier, "B12345678")
        Supplier.objects.create(
            business=self.other_business,
            name=self.supplier.name,
            tax_identifier=self.supplier.tax_identifier,
        )

    def test_purchase_defaults_and_state_properties(self):
        purchase = self.create_purchase()
        self.assertEqual(purchase.status, PurchaseStatusChoices.DRAFT)
        self.assertEqual(purchase.subtotal_amount, Decimal("0.00"))
        self.assertEqual(purchase.tax_amount, Decimal("0.00"))
        self.assertEqual(purchase.total_amount, Decimal("0.00"))
        self.assertTrue(purchase.is_draft)
        self.assertTrue(purchase.is_editable)

    def test_purchase_rejects_cross_business_relations(self):
        invalid_values = (
            {"store": self.other_store},
            {"supplier": self.other_supplier},
            {"created_by": self.other_user},
        )
        for overrides in invalid_values:
            with self.subTest(overrides=overrides), self.assertRaises(ValidationError):
                self.create_purchase(**overrides)

    def test_purchase_requires_valid_amounts_and_ordered_date(self):
        for overrides in (
            {"subtotal_amount": Decimal("-0.01")},
            {"tax_amount": Decimal("-0.01")},
            {"total_amount": Decimal("-0.01")},
            {"subtotal_amount": Decimal("1.00"), "total_amount": Decimal("0.00")},
            {"status": PurchaseStatusChoices.ORDERED},
            {"status": PurchaseStatusChoices.PARTIALLY_RECEIVED},
            {"status": PurchaseStatusChoices.RECEIVED},
        ):
            with self.subTest(overrides=overrides), self.assertRaises(ValidationError):
                self.create_purchase(**overrides)

    def test_purchase_line_creation_keeps_snapshot_and_allows_repeated_product(self):
        purchase = self.create_purchase()
        first = self.create_line(purchase=purchase, unit_cost=Decimal("1.00"))
        second = self.create_line(purchase=purchase, unit_cost=Decimal("1.25"))
        self.product.name = "Café renombrado"
        self.product.save()
        first.refresh_from_db()
        self.assertEqual(first.product_name, "Café")
        self.assertEqual(purchase.lines.count(), 2)
        self.assertNotEqual(first.pk, second.pk)

    def test_purchase_line_rejects_invalid_quantities_and_amounts(self):
        invalid_values = (
            {"quantity_ordered": Decimal("0.000")},
            {"quantity_received": Decimal("-0.001")},
            {"quantity_received": Decimal("10.001")},
            {"unit_cost": Decimal("-0.01")},
            {"tax_rate": Decimal("-0.01")},
            {"line_subtotal": Decimal("-0.01")},
            {"tax_amount": Decimal("-0.01")},
            {"line_total": Decimal("-0.01")},
        )
        purchase = self.create_purchase()
        for overrides in invalid_values:
            with self.subTest(overrides=overrides), self.assertRaises(ValidationError):
                self.create_line(purchase=purchase, **overrides)

    def test_purchase_line_rejects_cross_business_relations_and_empty_snapshots(self):
        purchase = self.create_purchase()
        invalid_values = (
            {"business": self.other_business},
            {"product": self.other_product},
            {"product_name": "   "},
            {"unit": "   "},
        )
        for overrides in invalid_values:
            with self.subTest(overrides=overrides), self.assertRaises(ValidationError):
                self.create_line(purchase=purchase, **overrides)

    def test_receipt_is_valid_for_ordered_and_partially_received_purchases(self):
        ordered = self.create_ordered_purchase()
        partially_received = self.create_purchase(
            status=PurchaseStatusChoices.PARTIALLY_RECEIVED,
            ordered_at=timezone.now(),
        )
        self.create_receipt(purchase=ordered)
        self.create_receipt(purchase=partially_received)
        self.assertEqual(ordered.receipts.count(), 1)
        self.assertEqual(partially_received.receipts.count(), 1)

    def test_receipt_rejects_invalid_purchase_states(self):
        for status in (
            PurchaseStatusChoices.DRAFT,
            PurchaseStatusChoices.CANCELLED,
            PurchaseStatusChoices.RECEIVED,
        ):
            values = {"status": status}
            if status == PurchaseStatusChoices.RECEIVED:
                values["ordered_at"] = timezone.now()
            purchase = self.create_purchase(**values)
            with self.subTest(status=status), self.assertRaises(ValidationError):
                self.create_receipt(purchase=purchase)

    def test_receipt_rejects_cross_business_store_and_user(self):
        purchase = self.create_ordered_purchase()
        invalid_values = (
            {"business": self.other_business},
            {"store": self.other_store},
            {"received_by": self.other_user},
        )
        for overrides in invalid_values:
            with self.subTest(overrides=overrides), self.assertRaises(ValidationError):
                self.create_receipt(purchase=purchase, **overrides)

    def test_receipt_requires_unique_business_idempotency_key(self):
        purchase = self.create_ordered_purchase()
        key = uuid4()
        self.create_receipt(purchase=purchase, idempotency_key=key)
        with self.assertRaises(ValidationError):
            self.create_receipt(purchase=purchase, idempotency_key=key)

    def test_receipt_line_rules_and_partial_receipts(self):
        purchase = self.create_ordered_purchase()
        line = self.create_line(purchase=purchase)
        first_receipt = self.create_receipt(purchase=purchase)
        second_receipt = self.create_receipt(purchase=purchase)
        PurchaseReceiptLine.objects.create(
            business=self.business,
            receipt=first_receipt,
            purchase_line=line,
            quantity_received=Decimal("6.000"),
        )
        PurchaseReceiptLine.objects.create(
            business=self.business,
            receipt=second_receipt,
            purchase_line=line,
            quantity_received=Decimal("4.000"),
        )
        self.assertEqual(line.receipt_lines.count(), 2)
        with self.assertRaises(ValidationError):
            PurchaseReceiptLine.objects.create(
                business=self.business,
                receipt=first_receipt,
                purchase_line=line,
                quantity_received=Decimal("1.000"),
            )

    def test_receipt_line_rejects_invalid_quantity_business_and_purchase(self):
        purchase = self.create_ordered_purchase()
        line = self.create_line(purchase=purchase)
        receipt = self.create_receipt(purchase=purchase)
        other_purchase = self.create_ordered_purchase()
        other_line = self.create_line(purchase=other_purchase)
        invalid_values = (
            {"quantity_received": Decimal("0.000")},
            {"quantity_received": Decimal("10.001")},
            {"business": self.other_business},
            {"purchase_line": other_line},
        )
        for overrides in invalid_values:
            values = {
                "business": self.business,
                "receipt": receipt,
                "purchase_line": line,
                "quantity_received": Decimal("1.000"),
            }
            values.update(overrides)
            with self.subTest(overrides=overrides), self.assertRaises(ValidationError):
                PurchaseReceiptLine.objects.create(**values)

    def test_creating_purchase_domain_objects_is_stock_neutral(self):
        inventory_item = InventoryItem.objects.create(
            business=self.business,
            store=self.store,
            product=self.product,
            current_stock=Decimal("7.000"),
        )
        movements_before = StockMovement.objects.count()
        purchase = self.create_ordered_purchase()
        line = self.create_line(purchase=purchase)
        receipt = self.create_receipt(purchase=purchase)
        PurchaseReceiptLine.objects.create(
            business=self.business,
            receipt=receipt,
            purchase_line=line,
            quantity_received=Decimal("3.000"),
        )
        inventory_item.refresh_from_db()
        line.refresh_from_db()
        self.assertEqual(inventory_item.current_stock, Decimal("7.000"))
        self.assertEqual(StockMovement.objects.count(), movements_before)
        self.assertEqual(line.quantity_received, Decimal("0.000"))
