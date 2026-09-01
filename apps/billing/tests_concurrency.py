import uuid
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

from django.core.exceptions import ValidationError
from django.db import connections
from django.test import TransactionTestCase, skipUnlessDBFeature
from django.utils import timezone

from apps.billing.models import (
    BillingDocument,
    BillingDocumentRelation,
    BillingDocumentRelationTypeChoices,
    BillingDocumentStatusChoices,
    BillingDocumentTypeChoices,
    BillingSeries,
)
from apps.billing.services import (
    BillingAlreadyIssued,
    BillingIdempotencyConflict,
    issue_sale_document,
    issue_sale_return_rectification,
    substitute_simplified_document,
)
from apps.business_config.services import create_business_configuration
from apps.sales.models import SaleReturnStatusChoices, SaleStatusChoices
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


class BillingEmissionConcurrencyTests(TransactionTestCase):
    reset_sequences = True

    def setUp(self):
        self.business = create_sales_business()
        self.store = create_sales_store(business=self.business)
        self.user = create_sales_user(business=self.business)
        create_business_configuration(
            business=self.business,
            legal_name="Netxodo SL",
            tax_identifier="B12345678",
            phone="600000000",
            email="billing@example.test",
            address_line_1="Calle Mayor 1",
            postal_code="28001",
            city="Madrid",
            province="Madrid",
        )
        tax = create_sales_tax(business=self.business)
        self.product = create_sales_product(business=self.business, tax=tax)
        self.series = BillingSeries.objects.create(
            business=self.business,
            store=self.store,
            name="Tickets",
            document_type=BillingDocumentTypeChoices.F2,
            prefix="TCK",
            year=timezone.localdate().year,
        )

    def make_sale(self):
        sale = create_sale(
            business=self.business,
            store=self.store,
            opened_by=self.user,
            status=SaleStatusChoices.COMPLETED,
        )
        create_sale_line(business=self.business, sale=sale, product=self.product)
        return sale

    def run_threads(self, operations):
        barrier = Barrier(len(operations))

        def execute(operation):
            connections.close_all()
            try:
                barrier.wait()
                return (True, operation().pk)
            except ValidationError as exc:
                return (False, exc)
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=len(operations)) as executor:
            return list(executor.map(execute, operations))

    def operation(self, sale, key):
        return lambda: issue_sale_document(
            business=self.business,
            sale_id=sale.pk,
            series_id=self.series.pk,
            issued_by=self.user,
            idempotency_key=key,
        )

    @skipUnlessDBFeature("has_select_for_update")
    def test_same_sale_different_keys_issues_once(self):
        sale = self.make_sale()
        results = self.run_threads(
            [self.operation(sale, uuid.uuid4()), self.operation(sale, uuid.uuid4())]
        )
        self.assertEqual(sum(success for success, _ in results), 1)
        failure = next(value for success, value in results if not success)
        self.assertIsInstance(failure, BillingAlreadyIssued)
        self.assertEqual(BillingDocument.objects.count(), 1)
        self.series.refresh_from_db()
        self.assertEqual(self.series.current_number, 1)

    @skipUnlessDBFeature("has_select_for_update")
    def test_distinct_sales_same_series_receive_consecutive_numbers(self):
        first_sale, second_sale = self.make_sale(), self.make_sale()
        results = self.run_threads(
            [
                self.operation(first_sale, uuid.uuid4()),
                self.operation(second_sale, uuid.uuid4()),
            ]
        )
        self.assertTrue(all(success for success, _ in results))
        self.assertEqual(
            set(BillingDocument.objects.values_list("number", flat=True)), {1, 2}
        )
        self.series.refresh_from_db()
        self.assertEqual(self.series.current_number, 2)

    @skipUnlessDBFeature("has_select_for_update")
    def test_same_sale_same_key_returns_same_document(self):
        sale = self.make_sale()
        key = uuid.uuid4()
        results = self.run_threads(
            [self.operation(sale, key), self.operation(sale, key)]
        )
        self.assertTrue(all(success for success, _ in results))
        self.assertEqual(
            {result for _, result in results}, {BillingDocument.objects.get().pk}
        )
        self.series.refresh_from_db()
        self.assertEqual(self.series.current_number, 1)

    @skipUnlessDBFeature("has_select_for_update")
    def test_distinct_sales_same_key_has_one_controlled_winner(self):
        first_sale, second_sale = self.make_sale(), self.make_sale()
        key = uuid.uuid4()
        results = self.run_threads(
            [self.operation(first_sale, key), self.operation(second_sale, key)]
        )
        successes = [value for success, value in results if success]
        failures = [value for success, value in results if not success]
        self.assertEqual(len(successes), 1)
        self.assertEqual(len(failures), 1)
        self.assertIsInstance(failures[0], BillingIdempotencyConflict)
        self.assertEqual(BillingDocument.objects.count(), 1)
        self.series.refresh_from_db()
        self.assertEqual(self.series.current_number, 1)


class BillingRectificationConcurrencyTests(TransactionTestCase):
    reset_sequences = True
    make_sale = BillingEmissionConcurrencyTests.make_sale
    run_threads = BillingEmissionConcurrencyTests.run_threads

    def setUp(self):
        BillingEmissionConcurrencyTests.setUp(self)
        self.rectification_series = BillingSeries.objects.create(
            business=self.business,
            store=self.store,
            name="Rectificativas simplificadas",
            document_type=BillingDocumentTypeChoices.R5,
            prefix="R5",
            year=timezone.localdate().year,
        )

    def make_return(self):
        sale = self.make_sale()
        issue_sale_document(
            business=self.business,
            sale_id=sale.pk,
            series_id=self.series.pk,
            issued_by=self.user,
            idempotency_key=uuid.uuid4(),
        )
        return_doc = create_sale_return(
            business=self.business,
            store=self.store,
            original_sale=sale,
            created_by=self.user,
        )
        create_sale_return_line(
            business=self.business,
            return_doc=return_doc,
            original_line=sale.lines.get(),
        )
        return_doc.status = SaleReturnStatusChoices.COMPLETED
        return_doc.completed_at = timezone.now()
        return_doc.save()
        return return_doc

    def rectification_operation(self, return_doc, key):
        return lambda: issue_sale_return_rectification(
            business=self.business,
            sale_return_id=return_doc.pk,
            series_id=self.rectification_series.pk,
            issued_by=self.user,
            idempotency_key=key,
        )

    @skipUnlessDBFeature("has_select_for_update")
    def test_same_return_same_key_is_concurrently_idempotent(self):
        return_doc = self.make_return()
        key = uuid.uuid4()
        results = self.run_threads([self.rectification_operation(return_doc, key)] * 2)
        self.assertTrue(all(success for success, _ in results))
        self.assertEqual(len({value for _, value in results}), 1)
        self.assertEqual(
            BillingDocument.objects.filter(sale_return=return_doc).count(), 1
        )
        self.rectification_series.refresh_from_db()
        self.assertEqual(self.rectification_series.current_number, 1)

    @skipUnlessDBFeature("has_select_for_update")
    def test_same_return_different_keys_issues_once(self):
        return_doc = self.make_return()
        results = self.run_threads(
            [
                self.rectification_operation(return_doc, uuid.uuid4()),
                self.rectification_operation(return_doc, uuid.uuid4()),
            ]
        )
        self.assertEqual(sum(success for success, _ in results), 1)
        failure = next(value for success, value in results if not success)
        self.assertIsInstance(failure, BillingAlreadyIssued)
        self.rectification_series.refresh_from_db()
        self.assertEqual(self.rectification_series.current_number, 1)

    @skipUnlessDBFeature("has_select_for_update")
    def test_distinct_returns_share_series_with_consecutive_numbers(self):
        first, second = self.make_return(), self.make_return()
        results = self.run_threads(
            [
                self.rectification_operation(first, uuid.uuid4()),
                self.rectification_operation(second, uuid.uuid4()),
            ]
        )
        self.assertTrue(all(success for success, _ in results))
        numbers = BillingDocument.objects.filter(sale_return__isnull=False).values_list(
            "number", flat=True
        )
        self.assertEqual(set(numbers), {1, 2})

    @skipUnlessDBFeature("has_select_for_update")
    def test_distinct_returns_same_key_has_one_controlled_winner(self):
        first, second = self.make_return(), self.make_return()
        key = uuid.uuid4()
        results = self.run_threads(
            [
                self.rectification_operation(first, key),
                self.rectification_operation(second, key),
            ]
        )
        self.assertEqual(sum(success for success, _ in results), 1)
        failure = next(value for success, value in results if not success)
        self.assertIsInstance(failure, BillingIdempotencyConflict)
        self.assertEqual(
            BillingDocument.objects.filter(sale_return__isnull=False).count(), 1
        )

    @skipUnlessDBFeature("has_select_for_update")
    def test_same_return_companion_f3_is_concurrently_idempotent(self):
        sale = self.make_sale()
        original = issue_sale_document(
            business=self.business,
            sale_id=sale.pk,
            series_id=self.series.pk,
            issued_by=self.user,
            idempotency_key=uuid.uuid4(),
        )
        customer = create_sales_customer(
            business=self.business,
            legal_name="Concurrent Recipient SL",
            tax_identifier="B99887766",
        )
        initial_f3_series = BillingSeries.objects.create(
            business=self.business,
            store=self.store,
            name="Initial F3",
            document_type=BillingDocumentTypeChoices.F3,
            prefix="F3I",
            year=timezone.localdate().year,
        )
        substitute_simplified_document(
            business=self.business,
            sale_id=sale.pk,
            customer=customer,
            series_id=initial_f3_series.pk,
            issued_by=self.user,
            idempotency_key=uuid.uuid4(),
        )
        return_doc = create_sale_return(
            business=self.business,
            store=self.store,
            original_sale=sale,
            created_by=self.user,
        )
        create_sale_return_line(
            business=self.business,
            return_doc=return_doc,
            original_line=sale.lines.get(),
        )
        return_doc.status = SaleReturnStatusChoices.COMPLETED
        return_doc.completed_at = timezone.now()
        return_doc.save()
        companion_series = BillingSeries.objects.create(
            business=self.business,
            store=self.store,
            name="Companion F3",
            document_type=BillingDocumentTypeChoices.F3,
            prefix="F3C",
            year=timezone.localdate().year,
        )
        key = uuid.uuid4()

        def operation():
            return issue_sale_return_rectification(
                business=self.business,
                sale_return_id=return_doc.pk,
                series_id=self.rectification_series.pk,
                companion_f3_series_id=companion_series.pk,
                issued_by=self.user,
                idempotency_key=key,
            )

        results = self.run_threads([operation, operation])
        self.assertTrue(all(success for success, _ in results))
        self.assertEqual(len({value for _, value in results}), 1)
        r5 = BillingDocument.objects.get(
            sale_return=return_doc, document_type=BillingDocumentTypeChoices.R5
        )
        companion = BillingDocument.objects.get(
            sale_return=return_doc, document_type=BillingDocumentTypeChoices.F3
        )
        self.assertEqual(
            BillingDocumentRelation.objects.filter(
                source_document=r5,
                target_document=original,
                relation_type=BillingDocumentRelationTypeChoices.RECTIFIES,
            ).count(),
            1,
        )
        self.assertEqual(
            BillingDocumentRelation.objects.filter(
                source_document=companion,
                target_document=r5,
                relation_type=BillingDocumentRelationTypeChoices.SUBSTITUTES,
            ).count(),
            1,
        )
        self.rectification_series.refresh_from_db()
        companion_series.refresh_from_db()
        self.assertEqual(
            (self.rectification_series.current_number, companion_series.current_number),
            (1, 1),
        )
        self.assertFalse(
            BillingDocument.objects.filter(
                status=BillingDocumentStatusChoices.DRAFT
            ).exists()
        )

    @skipUnlessDBFeature("has_select_for_update")
    def test_distinct_returns_same_sale_serialize_without_deadlock(self):
        sale = self.make_sale()
        issue_sale_document(
            business=self.business,
            sale_id=sale.pk,
            series_id=self.series.pk,
            issued_by=self.user,
            idempotency_key=uuid.uuid4(),
        )
        sale_line = sale.lines.get()
        first = create_sale_return(
            business=self.business,
            store=self.store,
            original_sale=sale,
            created_by=self.user,
        )
        second = create_sale_return(
            business=self.business,
            store=self.store,
            original_sale=sale,
            created_by=self.user,
        )
        for return_doc in (first, second):
            create_sale_return_line(
                business=self.business,
                return_doc=return_doc,
                original_line=sale_line,
                quantity="0.500",
            )
            return_doc.status = SaleReturnStatusChoices.COMPLETED
            return_doc.completed_at = timezone.now()
            return_doc.save()
        results = self.run_threads(
            [
                self.rectification_operation(first, uuid.uuid4()),
                self.rectification_operation(second, uuid.uuid4()),
            ]
        )
        self.assertTrue(all(success for success, _ in results))
        self.assertEqual(
            BillingDocument.objects.filter(sale_return__in=[first, second]).count(), 2
        )
