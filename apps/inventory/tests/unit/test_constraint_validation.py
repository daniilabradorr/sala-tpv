"""Grouped validation must preserve Django's checks, excludes and errors."""

from decimal import Decimal
from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.db import DatabaseError, connection, models
from django.test import TestCase
from django.test.utils import CaptureQueriesContext

from apps.inventory.models import InventoryItem, StockMovement
from tests.performance.dataset import Dataset


def outcome(validate):
    try:
        validate()
    except ValidationError as error:
        return error.message_dict, {
            field: [item.code for item in errors]
            for field, errors in error.error_dict.items()
        }
    return None


class StockConstraintValidationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.dataset = Dataset(1, label="stock-constraints")

    def item(self):
        return InventoryItem.objects.get(product=self.dataset.products[0])

    def movement(self, **values):
        return StockMovement(
            business=self.dataset.business,
            store=self.dataset.store,
            inventory_item=self.item(),
            product=self.dataset.products[0],
            movement_type=StockMovement.TYPE_SALE,
            quantity=Decimal("1"),
            stock_before=Decimal("10"),
            stock_after=Decimal("9"),
            **values,
        )

    def equivalent(self, instance, exclude=None):
        expected = outcome(
            lambda: models.Model.validate_constraints(instance, exclude=exclude)
        )
        actual = outcome(lambda: instance.validate_constraints(exclude=exclude))
        self.assertEqual(actual, expected)
        return actual

    def test_inventory_check_boundaries_and_excludes_match_django(self):
        for reserved in (None, Decimal("-1"), Decimal("0"), Decimal("1")):
            for minimum in (None, Decimal("-1"), Decimal("0")):
                for maximum in (None, Decimal("-1"), Decimal("0")):
                    for exclude in (None, {"reserved_stock"}, {"maximum_stock"}):
                        with self.subTest(
                            reserved=reserved,
                            minimum=minimum,
                            maximum=maximum,
                            exclude=exclude,
                        ):
                            item = self.item()
                            (
                                item.reserved_stock,
                                item.minimum_stock,
                                item.maximum_stock,
                            ) = reserved, minimum, maximum
                            self.equivalent(item, exclude)

    def test_movement_check_boundaries_and_excludes_match_django(self):
        for quantity in (Decimal("-1"), Decimal("0"), Decimal("1")):
            for cost in (None, Decimal("-1"), Decimal("0")):
                for exclude in (None, {"quantity"}, {"unit_cost"}):
                    with self.subTest(quantity=quantity, cost=cost, exclude=exclude):
                        movement = self.movement(unit_cost=cost)
                        movement.quantity = quantity
                        self.equivalent(movement, exclude)

    def test_inventory_unique_constraint_still_runs(self):
        item = self.item()
        item.pk = None
        self.assertIsNotNone(self.equivalent(item))

    def test_fk_validation_and_model_clean_are_not_bypassed(self):
        movement = self.movement()
        movement.sale_id = 999999
        with self.assertRaises(ValidationError):
            movement.clean_fields()
        movement = self.movement()
        movement.stock_after = Decimal("8")
        with self.assertRaises(ValidationError):
            movement.full_clean()

    def test_grouped_checks_reduce_sql_without_omitting_constraints(self):
        item = self.item()
        with CaptureQueriesContext(connection) as before:
            models.Model.validate_constraints(item)
        with CaptureQueriesContext(connection) as after:
            item.validate_constraints()
        self.assertLess(len(after), len(before))
        item.reserved_stock = Decimal("-1")
        item.minimum_stock = Decimal("-1")
        errors = self.equivalent(item)
        self.assertIn("chk_invitem_res_gte_0", str(errors))
        self.assertIn("chk_invitem_min_gte_0", str(errors))

    def test_movement_checks_also_share_one_successful_probe(self):
        movement = self.movement()
        with CaptureQueriesContext(connection) as before:
            models.Model.validate_constraints(movement)
        with CaptureQueriesContext(connection) as after:
            movement.validate_constraints()
        self.assertLess(len(after), len(before))

    def test_group_query_error_does_not_approve_invalid_checks(self):
        item = self.item()
        item.reserved_stock = Decimal("-1")
        failed = False

        def fail_first_select(execute, sql, params, many, context):
            nonlocal failed
            if not failed and sql.startswith("SELECT"):
                failed = True
                raise DatabaseError("synthetic group SQL failure")
            return execute(sql, params, many, context)

        with connection.execute_wrapper(fail_first_select):
            result = outcome(item.validate_constraints)
        self.assertTrue(failed)
        self.assertIn("chk_invitem_res_gte_0", str(result))

    def test_grouped_database_error_falls_back_to_individual_checks(self):
        item = self.item()
        with patch(
            "apps.inventory.validation._check_conditions",
            side_effect=DatabaseError("synthetic diagnostic error"),
        ):
            self.assertIsNone(outcome(item.validate_constraints))

    def test_grouped_fetch_error_does_not_approve_invalid_checks(self):
        from django.db.models.sql.compiler import SQLCompiler

        item = self.item()
        item.reserved_stock = Decimal("-1")
        original = SQLCompiler.execute_sql
        failed = False

        def fail_first(compiler, *args, **kwargs):
            nonlocal failed
            if not failed:
                failed = True
                raise DatabaseError("synthetic fetch failure")
            return original(compiler, *args, **kwargs)

        with patch.object(SQLCompiler, "execute_sql", fail_first):
            result = outcome(item.validate_constraints)
        self.assertTrue(failed)
        self.assertIn("chk_invitem_res_gte_0", str(result))
