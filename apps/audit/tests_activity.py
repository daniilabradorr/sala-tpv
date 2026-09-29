from datetime import timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.audit.constants import AuditEventType, AuditModule
from apps.audit.forms import ActivityFilterForm
from apps.audit.models import AuditEvent
from apps.audit.presentation import payload_diff
from apps.audit.selectors import get_audit_events
from apps.audit.services import log_event
from apps.core.models import Business
from apps.reports.periods import report_period_from_dates
from apps.stores.models import Store
from apps.users.models import CustomUser, RoleChoices, UserStoreAccess


class ActivityFixture(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.business = Business.objects.create(name="Activity Business")
        cls.other_business = Business.objects.create(name="Other Activity Business")
        cls.store_a = Store.objects.create(
            business=cls.business, name="Centro", code="ACT-A"
        )
        cls.store_b = Store.objects.create(
            business=cls.business, name="Norte", code="ACT-B"
        )
        cls.other_store = Store.objects.create(
            business=cls.other_business, name="Otra", code="OTHER"
        )
        cls.owner = CustomUser.objects.create_user(
            business=cls.business,
            email="activity-owner@example.com",
            password="password",
            role=RoleChoices.OWNER,
        )
        cls.manager = CustomUser.objects.create_user(
            business=cls.business,
            email="activity-manager@example.com",
            password="password",
            role=RoleChoices.MANAGER,
        )
        cls.cashier = CustomUser.objects.create_user(
            business=cls.business,
            email="activity-cashier@example.com",
            password="password",
            role=RoleChoices.CASHIER,
        )
        cls.other_owner = CustomUser.objects.create_user(
            business=cls.other_business,
            email="other-activity-owner@example.com",
            password="password",
            role=RoleChoices.OWNER,
        )
        UserStoreAccess.objects.create(
            business=cls.business, user=cls.manager, store=cls.store_a
        )

    @classmethod
    def event(cls, *, store=None, user=None, message="Venta completada", **extra):
        return log_event(
            business=cls.business,
            store=store,
            user=user,
            event_type=extra.pop("event_type", AuditEventType.SALE_COMPLETED),
            module=extra.pop("module", AuditModule.SALES),
            message=message,
            **extra,
        )


class ActivitySelectorAndFormTests(ActivityFixture):
    def test_selector_keeps_backward_compatibility_and_filters(self):
        own = self.event(
            store=self.store_a,
            user=self.owner,
            message="Venta especial 123",
            entity_type="sales.sale",
            entity_id="123",
        )
        self.event(store=self.store_b, user=self.manager, message="Otro evento")
        log_event(
            business=self.other_business,
            store=self.other_store,
            user=self.other_owner,
            event_type=AuditEventType.SALE_COMPLETED,
            module=AuditModule.SALES,
            message="Evento ajeno",
        )
        self.assertEqual(get_audit_events(business=self.business).count(), 2)
        period = report_period_from_dates(
            date_from=timezone.localdate() - timedelta(days=1),
            date_to=timezone.localdate(),
        )
        filtered = get_audit_events(
            business=self.business,
            stores=[self.store_a],
            store=self.store_a,
            user=self.owner,
            module=AuditModule.SALES,
            event_type=AuditEventType.SALE_COMPLETED,
            period=period,
            query="123",
        )
        self.assertEqual(list(filtered), [own])

    def test_form_rejects_unauthorized_store_user_and_event_pair(self):
        data = {
            "period": "30d",
            "store": self.store_b.pk,
            "user": self.other_owner.pk,
            "module": AuditModule.PAYMENTS,
            "event_type": AuditEventType.SALE_COMPLETED,
        }
        form = ActivityFilterForm(data, business=self.business, user=self.manager)
        self.assertFalse(form.is_valid())
        self.assertIn("store", form.errors)
        self.assertIn("user", form.errors)
        self.assertIn("event_type", form.errors)

    def test_form_custom_period_is_inclusive_ui_and_exclusive_backend(self):
        today = timezone.localdate()
        form = ActivityFilterForm(
            {
                "period": "custom",
                "date_from": today.isoformat(),
                "date_to": today.isoformat(),
            },
            business=self.business,
            user=self.owner,
        )
        self.assertTrue(form.is_valid(), form.errors)
        period = form.cleaned_data["period_range"]
        self.assertEqual(period.start.date(), today)
        self.assertEqual(period.end.date(), today + timedelta(days=1))


class ActivityHTTPTests(ActivityFixture):
    def setUp(self):
        self.event(store=self.store_a, user=self.owner, message="Visible A")
        self.event(store=self.store_b, user=self.owner, message="Oculta B")
        self.global_event = self.event(
            store=None,
            user=None,
            message="Cambio global",
            event_type=AuditEventType.BUSINESS_CONFIG_CHANGED,
            module=AuditModule.BUSINESS_CONFIG,
        )

    def test_owner_manager_cashier_and_anonymous_contract(self):
        url = reverse("audit:activity")
        self.client.force_login(self.owner)
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Cambio global")

        self.client.force_login(self.manager)
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Visible A")
        self.assertNotContains(response, "Oculta B")
        self.assertNotContains(response, "Cambio global")
        response = self.client.get(url, {"period": "30d", "store": self.store_b.pk})
        self.assertEqual(response.status_code, 422)
        self.assertNotContains(response, "Oculta B")

        self.client.force_login(self.cashier)
        self.assertEqual(self.client.get(url).status_code, 403)
        self.client.logout()
        self.assertEqual(self.client.get(url).status_code, 302)

    def test_get_only_and_htmx_invalid_filter_contract(self):
        self.client.force_login(self.owner)
        url = reverse("audit:activity")
        for method in (
            self.client.post,
            self.client.put,
            self.client.patch,
            self.client.delete,
        ):
            self.assertEqual(method(url).status_code, 405)
        response = self.client.get(
            url,
            {"period": "custom"},
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.headers["HX-Retarget"], "#activity-filters")
        self.assertEqual(response.headers["HX-Reswap"], "outerHTML")

    def test_detail_uses_snapshots_redacts_secrets_and_hides_manager_ip(self):
        event = self.event(
            store=self.store_a,
            user=None,
            message="Snapshot",
            old_payload={"amount": "10.00", "password": "real-password"},
            new_payload={"amount": "20.00", "token": "real-token"},
            ip_address="192.0.2.20",
        )
        url = reverse("audit:activity_detail", kwargs={"pk": event.pk})
        self.client.force_login(self.owner)
        response = self.client.get(url)
        self.assertContains(response, "Sistema")
        self.assertContains(response, "Dato protegido")
        self.assertContains(response, "192.0.2.20")
        self.assertNotContains(response, "real-password")
        self.assertNotContains(response, "real-token")
        self.client.force_login(self.manager)
        response = self.client.get(url)
        self.assertNotContains(response, "192.0.2.20")

    def test_payload_diff_never_exposes_unsanitized_secret_defensively(self):
        event = AuditEvent(
            business=self.business,
            event_type=AuditEventType.SALE_COMPLETED,
            module=AuditModule.SALES,
            message="Defensive presentation",
            old_payload={"password": "unsafe-old"},
            new_payload={"password": "unsafe-new"},
        )
        rows = payload_diff(event)
        self.assertEqual(rows[0]["before"], "Dato protegido")
        self.assertEqual(rows[0]["after"], "Dato protegido")
