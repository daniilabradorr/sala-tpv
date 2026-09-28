from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from apps.onboarding.services import OnboardingService
from apps.reports.forms import ReportFilterForm
from apps.stores.models import Store
from apps.users.models import CustomUser, RoleChoices, UserStoreAccess


class ReportFilterFormTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        result = OnboardingService.create_business(
            legal_name="Reports Forms SL",
            tax_identifier="B10000001",
            phone="923000001",
            email="reports-forms@example.com",
            address_line_1="Calle Uno",
            postal_code="37001",
            city="Salamanca",
            province="Salamanca",
            country_code="ES",
            store_name="Centro",
            owner_first_name="Owner",
            owner_last_name="Reports",
            owner_email="reports-owner@example.com",
            owner_phone="600000001",
            owner_password="Safe-Reports-123!",
            owner_pin="1234",
        )
        cls.business, cls.owner, cls.store = result.business, result.owner, result.store
        cls.other_store = Store.objects.create(
            business=cls.business, name="Norte", code="NORTH"
        )
        cls.manager = CustomUser.objects.create_user(
            email="reports-manager@example.com",
            password="Safe-Reports-123!",
            business=cls.business,
            role=RoleChoices.MANAGER,
        )
        UserStoreAccess.objects.create(
            business=cls.business, user=cls.manager, store=cls.store
        )

    def form(self, data, user=None):
        return ReportFilterForm(
            data,
            business=self.business,
            user=user or self.owner,
            active_store=self.store,
        )

    def test_presets_resolve_inclusive_dates_to_half_open_period(self):
        today = timezone.localdate()
        for key, start in (
            ("today", today),
            ("7d", today - timedelta(days=6)),
            ("30d", today - timedelta(days=29)),
            ("month", today.replace(day=1)),
        ):
            with self.subTest(key=key):
                form = self.form({"period": key, "store": self.store.pk})
                self.assertTrue(form.is_valid(), form.errors)
                self.assertEqual(form.cleaned_data["date_from"], start)
                self.assertEqual(
                    form.cleaned_data["report_period"].end.date(),
                    today + timedelta(days=1),
                )

    def test_custom_requires_ordered_dates(self):
        missing = self.form({"period": "custom", "store": self.store.pk})
        self.assertFalse(missing.is_valid())
        reversed_dates = self.form(
            {
                "period": "custom",
                "date_from": "2026-09-28",
                "date_to": "2026-09-01",
                "store": self.store.pk,
            }
        )
        self.assertFalse(reversed_dates.is_valid())

    def test_partial_manager_cannot_select_all_or_unauthorized_store(self):
        for store_value in ("all", str(self.other_store.pk)):
            form = self.form(
                {"period": "today", "store": store_value}, user=self.manager
            )
            self.assertFalse(form.is_valid())
        self.assertNotIn(
            ("all", "Todas las tiendas"),
            self.form({"period": "today", "store": self.store.pk}, user=self.manager)
            .fields["store"]
            .choices,
        )
