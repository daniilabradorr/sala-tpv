from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.billing.models import BillingDocumentTypeChoices
from apps.billing.services import (
    activate_billing_series,
    create_billing_series,
    deactivate_billing_series,
    update_billing_series,
)
from apps.billing.tests_forms import BillingFormsFixture
from apps.sales.tests.factories import create_sales_store, create_sales_user
from apps.users.models import RoleChoices
from apps.users.tests.factories import create_store_access


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


class BillingSeriesHTTPPermissionTests(BillingFormsFixture):
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

    def setUp(self):
        super().setUp()
        self.series_obj = self.series(BillingDocumentTypeChoices.F1)

    def url(self, name, **kwargs):
        values = {"store_id": self.store.pk, **kwargs}
        return reverse(f"billing:{name}", kwargs=values)

    def test_owner_can_list_series(self):
        self.client.force_login(self.user)
        self.assertEqual(self.client.get(self.url("series_list")).status_code, 200)

    def test_manager_requires_active_store_access(self):
        manager = create_sales_user(business=self.business, role=RoleChoices.MANAGER)
        self.client.force_login(manager)
        self.assertEqual(self.client.get(self.url("series_list")).status_code, 403)
        create_store_access(self.business, manager, self.store)
        self.assertEqual(self.client.get(self.url("series_list")).status_code, 200)

    def test_cashier_is_forbidden_for_every_series_endpoint(self):
        cashier = create_sales_user(business=self.business, role=RoleChoices.CASHIER)
        create_store_access(self.business, cashier, self.store)
        self.client.force_login(cashier)
        endpoints = [
            ("get", self.url("series_list"), None),
            ("get", self.url("series_create"), None),
            ("get", self.url("series_detail", series_pk=self.series_obj.pk), None),
            ("post", self.url("series_create"), {}),
            (
                "post",
                self.url("series_edit", series_pk=self.series_obj.pk),
                {"name": "Manipulada"},
            ),
            (
                "post",
                self.url(
                    "series_toggle",
                    series_pk=self.series_obj.pk,
                    action="deactivate",
                ),
                {},
            ),
        ]
        for method, url, data in endpoints:
            with self.subTest(url=url):
                response = getattr(self.client, method)(url, data or {})
                self.assertEqual(response.status_code, 403)

    def test_cross_business_store_is_denied(self):
        self.client.force_login(self.user)
        foreign_store = create_sales_store(business=self.other_business)
        url = reverse("billing:series_list", kwargs={"store_id": foreign_store.pk})
        self.assertEqual(self.client.get(url).status_code, 403)

    def test_invalid_hx_filter_retargets_series_form_without_losing_scope(self):
        self.client.force_login(self.user)
        response = self.client.get(
            self.url("series_list"),
            {"year": "not-a-year"},
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response["HX-Retarget"], "#billing-series-filters")
        self.assertEqual(response["HX-Reswap"], "outerHTML")
        self.assertContains(
            response,
            'id="billing-series-filters"',
            count=1,
            status_code=422,
        )
        self.assertContains(response, "Introduzca un número entero", status_code=422)
        self.assertNotContains(response, "<html", status_code=422)
        self.assertNotContains(response, 'id="billing-series-results"', status_code=422)

    def test_used_series_tampered_identity_post_is_rejected(self):
        self.client.force_login(self.user)
        document = self.issued_original(self.sale(), BillingDocumentTypeChoices.F2)
        series = document.series
        response = self.client.post(
            self.url("series_edit", series_pk=series.pk),
            {
                "name": "Nombre permitido",
                "prefix": "MANIPULADA",
                "current_number": 999999,
            },
        )
        self.assertEqual(response.status_code, 200)
        series.refresh_from_db()
        self.assertNotEqual(series.prefix, "MANIPULADA")
        self.assertEqual(series.current_number, 1)
        self.assertNotEqual(series.name, "Nombre permitido")

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
