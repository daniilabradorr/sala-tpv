"""Tests unitarios de services del módulo sales."""

from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import TestCase

from apps.inventory.models import StockMovement
from apps.sales.models import (
    RequestedDocumentTypeChoices,
    SaleReturnStatusChoices,
    SaleStatusChoices,
)
from apps.sales.services import (
    add_sale_line,
    add_sale_return_line,
    calculate_sale_line_amounts,
    cancel_sale,
    cancel_sale_return,
    complete_sale,
    complete_sale_return,
    create_sale_return,
    delete_sale_line,
    open_sale,
    update_sale_line,
    update_sale_return_line,
)
from apps.sales.tests.factories import (
    create_pos_settings,
    create_sales_business,
    create_sales_inventory_item,
    create_sales_product,
    create_sales_store,
    create_sales_tax,
    create_sales_user,
)
from apps.users.models import RoleChoices


class SaleServicesTests(TestCase):
    password = "testpass123"

    def setUp(self):  # noqa: N802
        self.business = create_sales_business()
        self.store = create_sales_store(business=self.business)
        self.owner = create_sales_user(
            business=self.business,
            role=RoleChoices.OWNER,
            password=self.password,
            pin="1234",
        )
        self.pos_settings = create_pos_settings(
            business=self.business,
            require_open_cash_register=False,
            require_pin_for_sensitive_actions=False,
            enable_stock_control=True,
            allow_sale_without_stock=False,
        )
        self.tax = create_sales_tax(
            business=self.business,
            rate=Decimal("21.00"),
        )
        self.product = create_sales_product(
            business=self.business,
            tax=self.tax,
            name="Café",
            base_price=Decimal("10.00"),
            cost_price=Decimal("4.00"),
        )
        self.inventory_item = create_sales_inventory_item(
            business=self.business,
            store=self.store,
            product=self.product,
            current_stock=Decimal("20.000"),
        )

    def open_basic_sale(self):
        return open_sale(
            business=self.business,
            store=self.store,
            opened_by=self.owner,
        )

    def add_basic_line(self, sale, quantity=Decimal("1.000")):
        return add_sale_line(
            business=self.business,
            sale=sale,
            product=self.product,
            quantity=quantity,
            user=self.owner,
        )

    def assert_tax_treatment_rejected(self, **changes):
        self.tax.__class__.objects.filter(pk=self.tax.pk).update(**changes)
        sale = self.open_basic_sale()

        with self.assertRaises(ValidationError):
            self.add_basic_line(sale)

    def test_calculate_sale_line_amounts_rounds_by_line(self):
        result = calculate_sale_line_amounts(
            quantity=Decimal("1.333"),
            unit_base_price=Decimal("3.25"),
            discount_amount=Decimal("0.10"),
            tax_rate=Decimal("21.00"),
        )

        self.assertEqual(result["gross_base_amount"], Decimal("4.33"))
        self.assertEqual(result["taxable_base_amount"], Decimal("4.23"))
        self.assertEqual(result["tax_amount"], Decimal("0.89"))
        self.assertEqual(result["line_total"], Decimal("5.12"))

    def test_open_sale_creates_open_unpaid_sale_with_zero_totals(self):
        sale = self.open_basic_sale()

        self.assertEqual(sale.status, SaleStatusChoices.OPEN)
        self.assertEqual(sale.total_amount, Decimal("0.00"))
        self.assertEqual(sale.pending_amount, Decimal("0.00"))
        self.assertEqual(sale.opened_by, self.owner)

    def test_open_sale_requires_customer_for_invoice(self):
        with self.assertRaises(ValidationError):
            open_sale(
                business=self.business,
                store=self.store,
                opened_by=self.owner,
                document_type_requested=RequestedDocumentTypeChoices.INVOICE,
            )

    def test_add_line_freezes_snapshot_and_recalculates_sale(self):
        sale = self.open_basic_sale()

        line = add_sale_line(
            business=self.business,
            sale=sale,
            product=self.product,
            quantity=Decimal("2.000"),
            discount_amount=Decimal("2.00"),
            user=self.owner,
        )
        sale.refresh_from_db()

        self.assertEqual(line.product_name, "Café")
        self.assertEqual(line.tax_rate, Decimal("21.00"))
        self.assertEqual(line.tax_type, self.tax.tax_type)
        self.assertEqual(line.clave_regimen, self.tax.clave_regimen)
        self.assertEqual(line.calificacion_operacion, self.tax.calificacion_operacion)
        self.assertEqual(line.operacion_exenta, self.tax.operacion_exenta)
        self.assertEqual(
            line.has_equivalence_surcharge,
            self.tax.has_equivalence_surcharge,
        )
        self.assertEqual(
            line.equivalence_surcharge_rate,
            self.tax.equivalence_surcharge_rate,
        )
        self.assertEqual(line.tax_amount, Decimal("3.78"))
        self.assertEqual(line.line_total, Decimal("21.78"))
        self.assertEqual(sale.subtotal_amount, Decimal("20.00"))
        self.assertEqual(sale.discount_amount, Decimal("2.00"))
        self.assertEqual(sale.tax_amount, Decimal("3.78"))
        self.assertEqual(sale.total_amount, Decimal("21.78"))
        self.assertEqual(sale.pending_amount, Decimal("21.78"))

    def test_tax_and_product_changes_do_not_rewrite_line_snapshot(self):
        sale = self.open_basic_sale()
        line = self.add_basic_line(sale)
        original_snapshot = (
            line.tax_rate,
            line.tax_type,
            line.clave_regimen,
            line.calificacion_operacion,
        )

        self.tax.rate = Decimal("10.00")
        self.tax.save()
        replacement_tax = create_sales_tax(business=self.business, rate=Decimal("4.00"))
        self.product.tax = replacement_tax
        self.product.save()
        update_sale_line(
            business=self.business,
            sale=sale,
            line=line,
            quantity=Decimal("2.000"),
            user=self.owner,
        )
        line.refresh_from_db()

        self.assertEqual(
            (
                line.tax_rate,
                line.tax_type,
                line.clave_regimen,
                line.calificacion_operacion,
            ),
            original_snapshot,
        )

    def test_add_line_rejects_manual_price_when_disabled(self):
        self.pos_settings.allow_manual_price = False
        self.pos_settings.save()
        sale = self.open_basic_sale()

        with self.assertRaises(ValidationError):
            add_sale_line(
                business=self.business,
                sale=sale,
                product=self.product,
                quantity=Decimal("1.000"),
                unit_base_price=Decimal("5.00"),
                user=self.owner,
            )

    def test_add_line_rejects_discount_above_maximum(self):
        self.pos_settings.max_manual_discount_percent = Decimal("20.00")
        self.pos_settings.save()
        sale = self.open_basic_sale()

        with self.assertRaises(ValidationError):
            add_sale_line(
                business=self.business,
                sale=sale,
                product=self.product,
                quantity=Decimal("1.000"),
                discount_amount=Decimal("3.00"),
                user=self.owner,
            )

    def test_add_line_rejects_igic(self):
        self.assert_tax_treatment_rejected(tax_type="IGIC")

    def test_add_line_rejects_non_general_tax_regime(self):
        self.assert_tax_treatment_rejected(clave_regimen="02")

    def test_add_line_rejects_equivalence_surcharge(self):
        self.assert_tax_treatment_rejected(
            has_equivalence_surcharge=True,
            equivalence_surcharge_rate=Decimal("5.20"),
        )

    def test_add_line_rejects_exempt_operation(self):
        self.assert_tax_treatment_rejected(operacion_exenta="E1")

    def test_add_line_rejects_unsupported_operation_qualification(self):
        self.assert_tax_treatment_rejected(calificacion_operacion="S2")

    def test_update_and_delete_line_recalculate_sale(self):
        sale = self.open_basic_sale()
        line = self.add_basic_line(sale)

        updated = update_sale_line(
            business=self.business,
            sale=sale,
            line=line,
            quantity=Decimal("3.000"),
            discount_amount=Decimal("0.00"),
            user=self.owner,
        )
        sale.refresh_from_db()

        self.assertEqual(updated.quantity, Decimal("3.000"))
        self.assertEqual(sale.total_amount, Decimal("36.30"))

        delete_sale_line(
            business=self.business,
            sale=sale,
            line=updated,
            user=self.owner,
        )
        sale.refresh_from_db()

        self.assertEqual(sale.lines.count(), 0)
        self.assertEqual(sale.total_amount, Decimal("0.00"))

    def test_complete_sale_reduces_stock_and_creates_movement(self):
        sale = self.open_basic_sale()
        line = self.add_basic_line(sale, quantity=Decimal("2.000"))

        completed = complete_sale(
            business=self.business,
            sale=sale,
            closed_by=self.owner,
        )
        self.inventory_item.refresh_from_db()

        self.assertEqual(completed.status, SaleStatusChoices.COMPLETED)
        self.assertEqual(completed.closed_by, self.owner)
        self.assertIsNotNone(completed.completed_at)
        self.assertEqual(self.inventory_item.current_stock, Decimal("18.000"))
        movement = StockMovement.objects.get(
            business=self.business,
            movement_type=StockMovement.TYPE_SALE,
            quantity=Decimal("2.000"),
        )
        self.assertEqual(movement.sale, sale)
        self.assertEqual(movement.sale_line, line)
        self.assertEqual(movement.store, self.store)
        self.assertEqual(movement.product, self.product)
        self.assertEqual(movement.reference_type, StockMovement.REF_SALE)
        self.assertTrue(movement.reference_id)

    def test_complete_sale_is_idempotent(self):
        sale = self.open_basic_sale()
        self.add_basic_line(sale)

        complete_sale(
            business=self.business,
            sale=sale,
            closed_by=self.owner,
        )
        first_count = StockMovement.objects.filter(
            reference_type=StockMovement.REF_SALE,
        ).count()

        completed_again = complete_sale(
            business=self.business,
            sale=sale,
            closed_by=self.owner,
        )
        self.inventory_item.refresh_from_db()

        self.assertEqual(completed_again.status, SaleStatusChoices.COMPLETED)
        self.assertEqual(self.inventory_item.current_stock, Decimal("19.000"))
        self.assertEqual(
            StockMovement.objects.filter(
                reference_type=StockMovement.REF_SALE,
            ).count(),
            first_count,
        )

    def test_complete_sale_rolls_back_everything_when_one_stock_line_fails(self):
        second_product = create_sales_product(
            business=self.business,
            tax=self.tax,
            name="Producto sin inventario",
        )
        sale = self.open_basic_sale()
        self.add_basic_line(sale, quantity=Decimal("2.000"))
        add_sale_line(
            business=self.business,
            sale=sale,
            product=second_product,
            quantity=Decimal("1.000"),
            user=self.owner,
        )

        with self.assertRaises(ValidationError):
            complete_sale(
                business=self.business,
                sale=sale,
                closed_by=self.owner,
            )

        sale.refresh_from_db()
        self.inventory_item.refresh_from_db()

        self.assertEqual(sale.status, SaleStatusChoices.OPEN)
        self.assertEqual(self.inventory_item.current_stock, Decimal("20.000"))
        self.assertFalse(
            StockMovement.objects.filter(
                business=self.business,
                movement_type=StockMovement.TYPE_SALE,
            ).exists()
        )

    def test_cancel_sale_requires_owner_or_manager_and_valid_pin(self):
        self.pos_settings.require_pin_for_sensitive_actions = True
        self.pos_settings.save()
        sale = self.open_basic_sale()

        with self.assertRaises(ValidationError):
            cancel_sale(
                business=self.business,
                sale=sale,
                cancelled_by=self.owner,
                pin="9999",
            )

        cancelled = cancel_sale(
            business=self.business,
            sale=sale,
            cancelled_by=self.owner,
            pin="1234",
        )

        self.assertEqual(cancelled.status, SaleStatusChoices.CANCELLED)

    def test_cancel_sale_rejects_completed_sale(self):
        sale = self.open_basic_sale()
        self.add_basic_line(sale)
        complete_sale(
            business=self.business,
            sale=sale,
            closed_by=self.owner,
        )

        with self.assertRaises(ValidationError):
            cancel_sale(
                business=self.business,
                sale=sale,
                cancelled_by=self.owner,
            )


class SaleReturnServicesTests(TestCase):
    def setUp(self):  # noqa: N802
        self.business = create_sales_business()
        self.store = create_sales_store(business=self.business)
        self.owner = create_sales_user(
            business=self.business,
            role=RoleChoices.OWNER,
            pin="1234",
        )
        self.pos_settings = create_pos_settings(
            business=self.business,
            require_open_cash_register=False,
            require_pin_for_sensitive_actions=False,
            enable_stock_control=True,
        )
        self.tax = create_sales_tax(business=self.business)
        self.product = create_sales_product(
            business=self.business,
            tax=self.tax,
            base_price=Decimal("10.00"),
        )
        self.inventory_item = create_sales_inventory_item(
            business=self.business,
            store=self.store,
            product=self.product,
            current_stock=Decimal("10.000"),
        )
        self.sale = open_sale(
            business=self.business,
            store=self.store,
            opened_by=self.owner,
        )
        self.sale_line = add_sale_line(
            business=self.business,
            sale=self.sale,
            product=self.product,
            quantity=Decimal("2.000"),
            user=self.owner,
        )
        complete_sale(
            business=self.business,
            sale=self.sale,
            closed_by=self.owner,
        )
        self.inventory_item.refresh_from_db()

    def test_create_return_requires_completed_sale_and_reason(self):
        draft_sale = open_sale(
            business=self.business,
            store=self.store,
            opened_by=self.owner,
        )

        with self.assertRaises(ValidationError):
            create_sale_return(
                business=self.business,
                store=self.store,
                original_sale=draft_sale,
                created_by=self.owner,
                reason="Prueba",
            )

        with self.assertRaises(ValidationError):
            create_sale_return(
                business=self.business,
                store=self.store,
                original_sale=self.sale,
                created_by=self.owner,
                reason="   ",
            )

    def test_partial_return_restores_stock_but_keeps_sale_completed(self):
        return_doc = create_sale_return(
            business=self.business,
            store=self.store,
            original_sale=self.sale,
            created_by=self.owner,
            reason="Devuelve una unidad",
        )
        return_line = add_sale_return_line(
            business=self.business,
            return_doc=return_doc,
            original_line=self.sale_line,
            quantity=Decimal("1.000"),
            restock=True,
            user=self.owner,
        )

        completed = complete_sale_return(
            business=self.business,
            return_doc=return_doc,
            completed_by=self.owner,
        )
        self.sale.refresh_from_db()
        self.inventory_item.refresh_from_db()
        return_line.refresh_from_db()

        self.assertEqual(completed.status, SaleReturnStatusChoices.COMPLETED)
        self.assertEqual(completed.approved_by, self.owner)
        self.assertIsNotNone(completed.completed_at)
        self.assertEqual(return_line.amount, Decimal("12.10"))
        self.assertEqual(self.inventory_item.current_stock, Decimal("9.000"))
        self.assertEqual(self.sale.status, SaleStatusChoices.COMPLETED)
        movement = StockMovement.objects.get(
            movement_type=StockMovement.TYPE_SALE_RETURN,
            quantity=Decimal("1.000"),
        )
        self.assertEqual(movement.sale, self.sale)
        self.assertEqual(movement.sale_line, self.sale_line)
        self.assertEqual(movement.sale_return, return_doc)
        self.assertEqual(movement.sale_return_line, return_line)
        self.assertEqual(movement.reference_type, StockMovement.REF_SALE)
        self.assertTrue(movement.reference_id)

    def test_complete_return_is_idempotent_and_preserves_first_approver(self):
        return_doc = create_sale_return(
            business=self.business,
            store=self.store,
            original_sale=self.sale,
            created_by=self.owner,
            reason="Idempotencia de devolución",
        )
        add_sale_return_line(
            business=self.business,
            return_doc=return_doc,
            original_line=self.sale_line,
            quantity=Decimal("1.000"),
            restock=True,
            user=self.owner,
        )
        second_user = create_sales_user(
            business=self.business,
            role=RoleChoices.OWNER,
        )

        first_result = complete_sale_return(
            business=self.business,
            return_doc=return_doc,
            completed_by=self.owner,
        )
        first_approved_by = first_result.approved_by
        first_completed_at = first_result.completed_at
        first_movement_count = StockMovement.objects.filter(
            movement_type=StockMovement.TYPE_SALE_RETURN,
            sale_return=return_doc,
        ).count()

        self.assertEqual(first_approved_by, self.owner)
        self.assertIsNotNone(first_completed_at)
        self.assertEqual(first_movement_count, 1)

        second_result = complete_sale_return(
            business=self.business,
            return_doc=return_doc,
            completed_by=second_user,
        )
        second_result.refresh_from_db()

        self.assertEqual(second_result.approved_by, self.owner)
        self.assertNotEqual(second_result.approved_by, second_user)
        self.assertEqual(second_result.completed_at, first_completed_at)
        self.assertEqual(
            StockMovement.objects.filter(
                movement_type=StockMovement.TYPE_SALE_RETURN,
                sale_return=return_doc,
            ).count(),
            first_movement_count,
        )

    def test_full_return_marks_sale_as_returned(self):
        return_doc = create_sale_return(
            business=self.business,
            store=self.store,
            original_sale=self.sale,
            created_by=self.owner,
            reason="Devolución completa",
        )
        add_sale_return_line(
            business=self.business,
            return_doc=return_doc,
            original_line=self.sale_line,
            quantity=Decimal("2.000"),
            restock=True,
            user=self.owner,
        )

        complete_sale_return(
            business=self.business,
            return_doc=return_doc,
            completed_by=self.owner,
        )
        return_doc.refresh_from_db()
        self.sale.refresh_from_db()
        self.inventory_item.refresh_from_db()

        self.assertEqual(self.sale.status, SaleStatusChoices.RETURNED)
        self.assertEqual(self.inventory_item.current_stock, Decimal("10.000"))
        self.assertIsNotNone(return_doc.completed_at)

    def test_return_with_restock_restores_stock(self):
        return_doc = create_sale_return(
            business=self.business,
            store=self.store,
            original_sale=self.sale,
            created_by=self.owner,
            reason="Reponer producto",
        )
        return_line = add_sale_return_line(
            business=self.business,
            return_doc=return_doc,
            original_line=self.sale_line,
            quantity=Decimal("2.000"),
            restock=True,
            user=self.owner,
        )

        self.assertEqual(self.inventory_item.current_stock, Decimal("8.000"))

        complete_sale_return(
            business=self.business,
            return_doc=return_doc,
            completed_by=self.owner,
        )
        self.inventory_item.refresh_from_db()

        self.assertEqual(self.inventory_item.current_stock, Decimal("10.000"))
        self.assertTrue(
            StockMovement.objects.filter(
                movement_type=StockMovement.TYPE_SALE_RETURN,
                reference_id=f"return:{return_doc.pk}:{return_line.pk}",
            ).exists()
        )

    def test_return_without_restock_does_not_restore_stock(self):
        return_doc = create_sale_return(
            business=self.business,
            store=self.store,
            original_sale=self.sale,
            created_by=self.owner,
            reason="No repone stock",
        )
        return_line = add_sale_return_line(
            business=self.business,
            return_doc=return_doc,
            original_line=self.sale_line,
            quantity=Decimal("2.000"),
            restock=False,
            user=self.owner,
        )

        complete_sale_return(
            business=self.business,
            return_doc=return_doc,
            completed_by=self.owner,
        )
        self.inventory_item.refresh_from_db()
        self.sale.refresh_from_db()

        self.assertEqual(self.inventory_item.current_stock, Decimal("8.000"))
        self.assertEqual(self.sale.status, SaleStatusChoices.RETURNED)
        self.assertFalse(
            StockMovement.objects.filter(
                movement_type=StockMovement.TYPE_SALE_RETURN,
                reference_id=f"return:{return_doc.pk}:{return_line.pk}",
            ).exists()
        )

    def test_update_return_line_updates_restock(self):
        return_doc = create_sale_return(
            business=self.business,
            store=self.store,
            original_sale=self.sale,
            created_by=self.owner,
            reason="Cambiar reposición",
        )
        return_line = add_sale_return_line(
            business=self.business,
            return_doc=return_doc,
            original_line=self.sale_line,
            quantity=Decimal("1.000"),
            restock=True,
            user=self.owner,
        )

        updated_line = update_sale_return_line(
            business=self.business,
            return_doc=return_doc,
            line=return_line,
            quantity=Decimal("1.000"),
            restock=False,
            user=self.owner,
        )

        self.assertFalse(updated_line.restock)

    def test_second_return_cannot_exceed_remaining_quantity(self):
        first_return = create_sale_return(
            business=self.business,
            store=self.store,
            original_sale=self.sale,
            created_by=self.owner,
            reason="Primera devolución",
        )
        add_sale_return_line(
            business=self.business,
            return_doc=first_return,
            original_line=self.sale_line,
            quantity=Decimal("1.000"),
            restock=True,
            user=self.owner,
        )
        complete_sale_return(
            business=self.business,
            return_doc=first_return,
            completed_by=self.owner,
        )

        second_return = create_sale_return(
            business=self.business,
            store=self.store,
            original_sale=self.sale,
            created_by=self.owner,
            reason="Segunda devolución",
        )

        with self.assertRaises(ValidationError):
            add_sale_return_line(
                business=self.business,
                return_doc=second_return,
                original_line=self.sale_line,
                quantity=Decimal("2.000"),
                restock=True,
                user=self.owner,
            )

    def test_cancel_return_requires_sensitive_action_and_does_not_touch_stock(self):
        self.pos_settings.require_pin_for_sensitive_actions = True
        self.pos_settings.save()
        return_doc = create_sale_return(
            business=self.business,
            store=self.store,
            original_sale=self.sale,
            created_by=self.owner,
            reason="Cancelación",
        )
        add_sale_return_line(
            business=self.business,
            return_doc=return_doc,
            original_line=self.sale_line,
            quantity=Decimal("1.000"),
            restock=True,
            user=self.owner,
        )
        stock_before = self.inventory_item.current_stock

        with self.assertRaises(ValidationError):
            cancel_sale_return(
                business=self.business,
                return_doc=return_doc,
                cancelled_by=self.owner,
                pin="0000",
            )

        cancelled = cancel_sale_return(
            business=self.business,
            return_doc=return_doc,
            cancelled_by=self.owner,
            pin="1234",
        )
        self.inventory_item.refresh_from_db()

        self.assertEqual(cancelled.status, SaleReturnStatusChoices.CANCELLED)
        self.assertEqual(self.inventory_item.current_stock, stock_before)
