import uuid
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

from django.core.exceptions import ValidationError
from django.db import connections
from django.test import TransactionTestCase, skipUnlessDBFeature
from django.utils import timezone

from apps.billing.models import (
    BillingDocument,
    BillingDocumentTypeChoices,
    BillingSeries,
)
from apps.billing.services import (
    BillingAlreadyIssued,
    BillingIdempotencyConflict,
    issue_sale_document,
)
from apps.business_config.models import BusinessProfile
from apps.sales.models import SaleStatusChoices
from apps.sales.tests.factories import (
    create_sale,
    create_sale_line,
    create_sales_business,
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
        profile = BusinessProfile.objects.get(business=self.business)
        profile.legal_name = "Netxodo SL"
        profile.tax_identifier = "B12345678"
        profile.phone = "600000000"
        profile.email = "billing@example.test"
        profile.address_line_1 = "Calle Mayor 1"
        profile.postal_code = "28001"
        profile.city = "Madrid"
        profile.province = "Madrid"
        profile.country_code = "ES"
        profile.save()
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
