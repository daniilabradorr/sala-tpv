from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone

from apps.billing.models import BillingDocumentTypeChoices
from apps.billing.services import (
    activate_billing_series,
    create_billing_series,
    deactivate_billing_series,
    update_billing_series,
)
from apps.billing.tests_forms import BillingFormsFixture


class BillingSeriesAdministrationTests(BillingFormsFixture):
    def create_admin_series(self, prefix="ADMIN"):
        return create_billing_series(
            business=self.business,
            store=self.store,
            cash_register=None,
            document_type=BillingDocumentTypeChoices.F1,
            name="Serie administrativa",
            prefix=prefix,
            year=timezone.localdate().year,
            padding=5,
        )

    def test_create_forces_safe_initial_state(self):
        series = self.create_admin_series()
        self.assertEqual(series.current_number, 0)
        self.assertTrue(series.is_active)

    def test_locked_update_never_overwrites_current_number(self):
        series = self.create_admin_series()
        type(series).objects.filter(pk=series.pk).update(current_number=11)
        updated = update_billing_series(
            series_id=series.pk,
            business=self.business,
            store=self.store,
            cash_register=None,
            document_type=series.document_type,
            name="Nombre nuevo",
            prefix=series.prefix,
            year=series.year,
            padding=series.padding,
        )
        self.assertEqual(updated.current_number, 11)
        self.assertEqual(updated.name, "Nombre nuevo")

    def test_used_identity_is_rejected_but_name_is_allowed(self):
        document = self.issued_original(self.sale(), BillingDocumentTypeChoices.F2)
        series = document.series
        with self.assertRaises(ValidationError):
            update_billing_series(
                series_id=series.pk,
                business=self.business,
                store=self.store,
                cash_register=None,
                document_type=series.document_type,
                name=series.name,
                prefix="MANIPULADA",
                year=series.year,
                padding=series.padding,
            )
        updated = update_billing_series(
            series_id=series.pk,
            business=self.business,
            store=self.store,
            cash_register=None,
            document_type=series.document_type,
            name="Nombre permitido",
            prefix=series.prefix,
            year=series.year,
            padding=series.padding,
        )
        self.assertEqual(updated.name, "Nombre permitido")

    def test_activate_and_deactivate_preserve_history(self):
        series = self.create_admin_series()
        deactivate_billing_series(
            series_id=series.pk, business=self.business, store=self.store
        )
        series.refresh_from_db()
        self.assertFalse(series.is_active)
        activate_billing_series(
            series_id=series.pk, business=self.business, store=self.store
        )
        series.refresh_from_db()
        self.assertTrue(series.is_active)


class BillingSeriesNoMigrationSmokeTests(TestCase):
    def test_document_types_remain_pre_verifactu(self):
        self.assertEqual(
            set(BillingDocumentTypeChoices.values),
            {"F1", "F2", "F3", "R1", "R2", "R3", "R4", "R5"},
        )
