from datetime import date
from unittest.mock import patch

from django.test import Client, TestCase
from django.template.loader import render_to_string
from django.urls import reverse

from apps.onboarding.services import OnboardingService
from apps.stores.models import Store
from apps.users.models import CustomUser, RoleChoices, UserStoreAccess


class ReportsViewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        result = OnboardingService.create_business(
            legal_name="Reports Views SL",
            tax_identifier="B10000002",
            phone="923000002",
            email="reports-views@example.com",
            address_line_1="Calle Dos",
            postal_code="37002",
            city="Salamanca",
            province="Salamanca",
            country_code="ES",
            store_name="Centro",
            owner_first_name="Owner",
            owner_last_name="Views",
            owner_email="views-owner@example.com",
            owner_phone="600000002",
            owner_password="Safe-Reports-123!",
            owner_pin="1234",
        )
        cls.business, cls.owner, cls.store = result.business, result.owner, result.store
        cls.second_store = Store.objects.create(
            business=cls.business, name="Sur", code="SOUTH"
        )
        cls.manager = CustomUser.objects.create_user(
            email="views-manager@example.com",
            password="Safe-Reports-123!",
            business=cls.business,
            role=RoleChoices.MANAGER,
        )
        cls.cashier = CustomUser.objects.create_user(
            email="views-cashier@example.com",
            password="Safe-Reports-123!",
            business=cls.business,
            role=RoleChoices.CASHIER,
        )
        UserStoreAccess.objects.create(
            business=cls.business, user=cls.manager, store=cls.store
        )

    def setUp(self):
        self.url = reverse("reports:overview")
        self.client.force_login(self.owner)

    def test_permissions_and_public_route(self):
        self.assertEqual(self.client.get(self.url).status_code, 200)
        self.client.force_login(self.manager)
        self.assertEqual(self.client.get(self.url).status_code, 200)
        self.client.force_login(self.cashier)
        self.assertEqual(self.client.get(self.url).status_code, 403)
        self.assertEqual(Client().get(self.url).status_code, 302)

    def test_sales_chart_has_equivalent_accessible_data_table(self):
        html = render_to_string(
            "reports/partials/_sales.html",
            {
                "sales_export_url": "/reports/export/",
                "report_data": {
                    "sales": {
                        "gross_sales": 10,
                        "returns_amount": 2,
                        "net_sales": 8,
                        "ticket_count": 1,
                        "average_ticket": 10,
                        "units_sold": 1,
                        "units_returned": 0,
                    },
                    "sales_timeseries": [
                        {
                            "day": date(2026, 9, 30),
                            "gross_sales": 10,
                            "returns_amount": 2,
                            "gross_sales_height": 100,
                            "returns_amount_height": 20,
                        }
                    ],
                    "sales_products": [],
                    "sales_categories": [],
                    "sales_stores": [],
                },
            },
        )

        self.assertIn(
            'class="reports-chart reports-chart--paired" aria-hidden="true"', html
        )
        self.assertIn("Datos de ventas brutas y devoluciones por día", html)
        self.assertIn("30/09/2026", html)
        self.assertIn("10,00 €", html)

    def test_invalid_tab_falls_back_to_general(self):
        response = self.client.get(
            self.url, {"tab": "unknown", "period": "today", "store": self.store.pk}
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["tab"], "general")

    def test_partial_manager_rejects_all_and_foreign_store(self):
        self.client.force_login(self.manager)
        self.assertEqual(
            self.client.get(self.url, {"period": "today", "store": "all"}).status_code,
            400,
        )
        other = OnboardingService.create_business(
            legal_name="Foreign Reports SL",
            tax_identifier="B10000003",
            phone="923000003",
            email="foreign@example.com",
            address_line_1="Calle Tres",
            postal_code="37003",
            city="Salamanca",
            province="Salamanca",
            country_code="ES",
            store_name="Foreign",
            owner_first_name="Other",
            owner_last_name="Owner",
            owner_email="foreign-owner@example.com",
            owner_phone="600000003",
            owner_password="Safe-Reports-123!",
            owner_pin="1234",
        )
        self.assertEqual(
            self.client.get(
                self.url, {"period": "today", "store": other.store.pk}
            ).status_code,
            400,
        )

    def test_invalid_htmx_filter_returns_only_form_with_422_contract(self):
        response = self.client.get(
            self.url,
            {"tab": "sales", "period": "custom", "store": self.store.pk},
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.headers["HX-Retarget"], "#reports-filters")
        self.assertEqual(response.headers["HX-Reswap"], "outerHTML")
        self.assertContains(response, 'id="reports-filters"', status_code=422)
        self.assertNotContains(response, 'id="reports-workspace"', status_code=422)

    def test_sales_tab_calls_only_sales_selectors(self):
        empty_summary = {
            "gross_sales": 0,
            "returns_amount": 0,
            "net_sales": 0,
            "ticket_count": 0,
            "average_ticket": 0,
            "units_sold": 0,
            "units_returned": 0,
        }
        with (
            patch(
                "apps.reports.views.selectors.sales_summary", return_value=empty_summary
            ) as summary,
            patch("apps.reports.views.selectors.sales_timeseries", return_value=[]),
            patch("apps.reports.views.selectors.sales_by_product", return_value=[]),
            patch("apps.reports.views.selectors.sales_by_category", return_value=[]),
            patch(
                "apps.reports.views.selectors.sales_by_store", return_value=[]
            ) as by_store,
            patch("apps.reports.views.selectors.cash_summary") as cash,
            patch("apps.reports.views.selectors.tax_summary") as tax,
            patch("apps.reports.views.selectors.purchase_summary") as purchases,
        ):
            response = self.client.get(
                self.url, {"tab": "sales", "period": "today", "store": self.store.pk}
            )
        self.assertEqual(response.status_code, 200)
        summary.assert_called_once()
        by_store.assert_not_called()
        cash.assert_not_called()
        tax.assert_not_called()
        purchases.assert_not_called()

    def test_htmx_tabs_return_one_workspace_and_keep_filters(self):
        response = self.client.get(
            self.url,
            {"tab": "payments", "period": "7d", "store": self.store.pk},
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content.decode().count('id="reports-workspace"'), 1)
        self.assertContains(response, "period=7d")
