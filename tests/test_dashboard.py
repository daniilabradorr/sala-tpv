from datetime import date
from unittest.mock import patch
from zoneinfo import ZoneInfo

from django.test import TestCase
from django.urls import reverse

from apps.core.dashboard import resolve_dashboard_period
from apps.onboarding.services import OnboardingService
from apps.users.models import CustomUser


class DashboardPeriodTests(TestCase):
    def test_supported_periods_and_unknown_fallback_use_local_half_open_bounds(self):
        today = date(2026, 9, 16)
        tz = ZoneInfo("Europe/Madrid")
        expectations = {None: 1, "today": 1, "7d": 7, "30d": 30, "garbage": 1}

        for value, days in expectations.items():
            with self.subTest(value=value):
                key, period = resolve_dashboard_period(value, today=today, tz=tz)
                self.assertEqual(
                    key, value if value in {"today", "7d", "30d"} else "today"
                )
                self.assertEqual((period.end - period.start).days, days)
                self.assertEqual(period.end.date(), date(2026, 9, 17))
                self.assertEqual(period.start.tzinfo, tz)


class DashboardViewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        result = OnboardingService.create_business(
            legal_name="Dashboard SL",
            trade_name="Dashboard",
            tax_identifier="B12345670",
            phone="923000000",
            email="dashboard-business@example.com",
            address_line_1="Calle Dashboard 1",
            postal_code="37001",
            city="Salamanca",
            province="Salamanca",
            country_code="ES",
            store_name="Centro",
            owner_first_name="Daniel",
            owner_last_name="Dashboard",
            owner_email="dashboard-owner@example.com",
            owner_phone="600000010",
            owner_password="Safe-Dashboard-Password-123!",
            owner_pin="1234",
        )
        cls.owner = result.owner

    def setUp(self):
        self.client.force_login(self.owner)

    def test_business_home_renders_operational_empty_dashboard(self):
        response = self.client.get(reverse("core:home"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Resumen de Centro")
        self.assertContains(response, "Ventas netas")
        self.assertContains(response, "Stock crítico")
        self.assertEqual(len(response.context["trend"]), 7)
        self.assertEqual(response.context["stock_attention"], 0)

    def test_htmx_period_response_is_only_the_stable_region(self):
        response = self.client.get(
            reverse("core:home"), {"period": "7d"}, HTTP_HX_REQUEST="true"
        )

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "core/partials/_dashboard_content.html")
        self.assertContains(response, 'id="dashboard-content"')
        self.assertNotContains(response, "<html")
        self.assertNotContains(response, "data-app-shell")
        self.assertEqual(response.context["period_key"], "7d")

    @patch("apps.core.views.build_dashboard_context")
    def test_superuser_without_business_keeps_administrative_mode(self, composer):
        admin = CustomUser.objects.create_superuser(
            email="admin-dashboard@example.com", password="safe-password"
        )
        self.client.force_login(admin)

        response = self.client.get(reverse("core:home"))

        self.assertContains(response, "Acceso administrativo sin una empresa asignada")
        composer.assert_not_called()
