from datetime import date, timedelta
from decimal import Decimal
from unittest.mock import patch
from zoneinfo import ZoneInfo

from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone
from django.db import connection

from apps.audit.models import AuditEvent
from apps.cash_register.models import CashRegister, CashSession
from apps.core.dashboard import build_dashboard_context, resolve_dashboard_period
from apps.inventory.tests.factories import (
    create_inventory_item,
    create_inventory_product,
)
from apps.onboarding.services import OnboardingService
from apps.purchases.models import Purchase, PurchaseStatusChoices, Supplier
from apps.reports.selectors import dashboard_summary
from apps.sales.models import (
    Sale,
    SaleReturn,
    SaleReturnStatusChoices,
    SaleStatusChoices,
)
from apps.sales.tests.factories import (
    create_sale,
    create_sale_line,
    create_sale_return,
    create_sale_return_line,
    create_sales_product,
)
from apps.users.models import CustomUser, RoleChoices
from apps.users.tests.factories import (
    create_business,
    create_store,
    create_store_access,
    create_user,
)


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
        cls.business = result.business
        cls.store = result.store
        cls.cash_register = result.cash_register

    def setUp(self):
        self.client.force_login(self.owner)

    def _completed_sale_and_return(self, *, return_amount):
        product = create_sales_product(
            business=self.business,
            name=f"Producto {return_amount}",
            base_price=Decimal("100.00"),
        )
        sale = create_sale(
            business=self.business,
            store=self.store,
            opened_by=self.owner,
            status=SaleStatusChoices.COMPLETED,
        )
        line = create_sale_line(
            business=self.business,
            sale=sale,
            product=product,
            unit_base_price=Decimal("100.00"),
            tax_rate=Decimal("0.00"),
        )
        sale_return = create_sale_return(
            business=self.business,
            store=self.store,
            original_sale=sale,
            created_by=self.owner,
        )
        create_sale_return_line(
            business=self.business,
            return_doc=sale_return,
            original_line=line,
            amount=Decimal(return_amount),
        )
        SaleReturn.objects.filter(pk=sale_return.pk).update(
            status=SaleReturnStatusChoices.COMPLETED,
            completed_at=timezone.now(),
        )
        return sale

    def test_business_home_renders_operational_empty_dashboard(self):
        response = self.client.get(reverse("core:home"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Resumen de Centro")
        self.assertContains(response, "Ventas netas")
        self.assertContains(response, "Stock crítico")
        self.assertEqual(len(response.context["trend"]), 7)
        self.assertEqual(response.context["stock_attention"], 0)

    def test_kpis_match_reports_for_real_completed_sale_and_return(self):
        self._completed_sale_and_return(return_amount="20.00")

        response = self.client.get(reverse("core:home"))
        expected = dashboard_summary(
            business=self.business,
            store=self.store,
            period=resolve_dashboard_period("today")[1],
        )["sales"]

        self.assertEqual(response.context["dashboard"]["sales"], expected)
        self.assertEqual(
            response.context["sales"]["ticket_count"], expected["ticket_count"]
        )
        self.assertContains(response, response.context["sales"]["net_sales"])
        self.assertContains(response, response.context["sales"]["average_ticket"])

    def test_net_zero_activity_does_not_render_false_empty_state(self):
        self._completed_sale_and_return(return_amount="100.00")

        response = self.client.get(reverse("core:home"))

        self.assertTrue(response.context["trend_has_activity"])
        self.assertNotContains(response, "No hay ventas en este periodo")

    def test_historical_sale_returned_today_produces_negative_trend_value(self):
        sale = self._completed_sale_and_return(return_amount="20.00")
        Sale.objects.filter(pk=sale.pk).update(
            completed_at=timezone.now() - timedelta(days=10)
        )

        response = self.client.get(reverse("core:home"))

        today_row = response.context["trend"][-1]
        self.assertEqual(Decimal(today_row["amount"]), Decimal("-20.00"))
        self.assertTrue(response.context["trend_has_activity"])

    def test_inventory_attention_and_rows_match_reports_store_scope(self):
        other_store = create_store(
            self.business, name="Inventario ajeno", code="INV-OTHER"
        )
        cases = (
            ("Agotado dashboard", "0", "2", True, self.store),
            ("Bajo dashboard", "1", "2", True, self.store),
            ("Sano dashboard", "5", "2", True, self.store),
            ("Inactivo dashboard", "0", "2", False, self.store),
            ("Crítico otra tienda", "0", "2", True, other_store),
        )
        for index, (name, current, minimum, active, store) in enumerate(cases):
            product = create_inventory_product(
                business=self.business, name=f"{name} {index}"
            )
            create_inventory_item(
                business=self.business,
                store=store,
                product=product,
                current_stock=Decimal(current),
                minimum_stock=Decimal(minimum),
                is_active=active,
            )

        response = self.client.get(reverse("core:home"))
        inventory = response.context["dashboard"]["inventory"]

        self.assertEqual(
            response.context["stock_attention"],
            inventory["out_of_stock_count"] + inventory["low_stock_count"],
        )
        self.assertContains(response, "Agotado dashboard")
        self.assertContains(response, "Bajo dashboard")
        self.assertNotContains(response, "Sano dashboard")
        self.assertNotContains(response, "Inactivo dashboard")
        self.assertNotContains(response, "Crítico otra tienda")

    def test_pending_purchases_are_status_store_limit_and_role_scoped(self):
        supplier = Supplier.objects.create(
            business=self.business, name="Proveedor dashboard"
        )
        for index, status in enumerate(
            (
                PurchaseStatusChoices.DRAFT,
                PurchaseStatusChoices.ORDERED,
                PurchaseStatusChoices.PARTIALLY_RECEIVED,
                PurchaseStatusChoices.RECEIVED,
                PurchaseStatusChoices.CANCELLED,
            )
        ):
            Purchase.objects.create(
                business=self.business,
                store=self.store,
                supplier=supplier,
                created_by=self.owner,
                status=status,
                reference=f"PUR-{status}",
                ordered_at=(
                    None
                    if status
                    in (PurchaseStatusChoices.DRAFT, PurchaseStatusChoices.CANCELLED)
                    else timezone.now()
                ),
            )
        for index in range(6):
            Purchase.objects.create(
                business=self.business,
                store=self.store,
                supplier=supplier,
                created_by=self.owner,
                status=PurchaseStatusChoices.ORDERED,
                reference=f"PUR-LIMIT-{index}",
                ordered_at=timezone.now(),
            )

        response = self.client.get(reverse("core:home"))

        self.assertEqual(len(response.context["pending_purchases"]), 5)
        statuses = {
            purchase.status for purchase in response.context["pending_purchases"]
        }
        self.assertLessEqual(
            statuses,
            {
                PurchaseStatusChoices.ORDERED,
                PurchaseStatusChoices.PARTIALLY_RECEIVED,
            },
        )
        cashier = create_user(
            self.business,
            email="dashboard-cashier@example.com",
            role=RoleChoices.CASHIER,
        )
        create_store_access(self.business, cashier, self.store)
        self.client.force_login(cashier)
        cashier_response = self.client.get(reverse("core:home"))
        self.assertFalse(cashier_response.context["show_management_blocks"])
        self.assertNotContains(cashier_response, "Compras pendientes")

    def test_dashboard_composer_query_count_does_not_scale_with_rows(self):
        def query_count():
            with CaptureQueriesContext(connection) as queries:
                build_dashboard_context(
                    business=self.business,
                    store=self.store,
                    user=self.owner,
                    period_key="today",
                )
            return len(queries)

        small_count = query_count()
        for index in range(12):
            product = create_inventory_product(
                business=self.business, name=f"Healthy {index}"
            )
            create_inventory_item(
                business=self.business,
                store=self.store,
                product=product,
                current_stock=Decimal("10"),
                minimum_stock=Decimal("1"),
            )
            CashRegister.objects.create(
                business=self.business,
                store=self.store,
                name=f"Caja perf {index}",
                code=f"PERF-{index}",
            )
            AuditEvent.objects.create(
                business=self.business,
                store=self.store,
                user=self.owner,
                event_type="dashboard.performance",
                module="core",
                message=f"Performance {index}",
            )

        many_count = query_count()

        self.assertLessEqual(abs(many_count - small_count), 1)

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

    def test_system_audit_event_is_rendered_without_nullable_user_error(self):
        AuditEvent.objects.create(
            business=self.business,
            store=self.store,
            user=None,
            event_type="dashboard.system",
            module="core",
            message="Proceso automático completado",
        )

        response = self.client.get(reverse("core:home"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Sistema")
        self.assertContains(response, "Proceso automático completado")

    def test_audit_is_store_scoped_limited_and_redacts_technical_payloads(self):
        other_store = create_store(self.business, name="Audit otra", code="AUDIT-X")
        other_business = create_business(
            name="Audit foreign", slug="audit-foreign-dashboard"
        )
        AuditEvent.objects.create(
            business=self.business,
            store=other_store,
            user=self.owner,
            event_type="dashboard.other",
            module="core",
            message="EVENTO OTRA TIENDA",
        )
        AuditEvent.objects.create(
            business=other_business,
            store=None,
            user=None,
            event_type="dashboard.foreign",
            module="core",
            message="EVENTO OTRO BUSINESS",
        )
        AuditEvent.objects.create(
            business=self.business,
            store=None,
            user=None,
            event_type="dashboard.business",
            module="core",
            message="EVENTO EMPRESA",
        )
        business_event_response = self.client.get(reverse("core:home"))
        self.assertContains(business_event_response, "EVENTO EMPRESA")
        self.assertContains(business_event_response, "Sistema")
        for index in range(5):
            AuditEvent.objects.create(
                business=self.business,
                store=self.store,
                user=self.owner,
                event_type="dashboard.active",
                module="core",
                message=f"EVENTO ACTIVO {index}",
                old_payload={"secret-old": index},
                new_payload={"secret-new": index},
                metadata={"secret-metadata": index},
                ip_address="192.0.2.1",
            )

        response = self.client.get(reverse("core:home"))
        content = response.content.decode()

        self.assertNotIn("EVENTO OTRA TIENDA", content)
        self.assertNotIn("EVENTO OTRO BUSINESS", content)
        self.assertIn("EVENTO ACTIVO 4", content)
        self.assertNotIn("EVENTO ACTIVO 0", content)
        self.assertEqual(len(response.context["recent_activity"]), 4)
        for secret in ("secret-old", "secret-new", "secret-metadata", "192.0.2.1"):
            self.assertNotIn(secret, content)

    def test_open_cash_session_uses_the_users_human_string(self):
        self.owner.first_name = "Daniel"
        self.owner.last_name = "Labrador"
        self.owner.save(update_fields=["first_name", "last_name", "updated_at"])
        CashSession.objects.create(
            business=self.business,
            store=self.store,
            cash_register=self.cash_register,
            opened_by=self.owner,
            opening_amount="25.00",
            expected_cash_amount="31.50",
        )

        response = self.client.get(reverse("core:home"))

        self.assertContains(response, "Sesión abierta")
        self.assertContains(response, self.cash_register.name)
        self.assertContains(response, "Daniel Labrador")
        self.assertContains(response, "31,50 €")

    def test_cash_states_are_active_register_and_store_scoped(self):
        self.cash_register.is_active = False
        self.cash_register.save(update_fields=["is_active", "updated_at"])
        self.assertContains(
            self.client.get(reverse("core:home")), "No hay cajas configuradas"
        )

        self.cash_register.is_active = True
        self.cash_register.save(update_fields=["is_active", "updated_at"])
        self.assertContains(self.client.get(reverse("core:home")), "Caja cerrada")
        closed_register = CashRegister.objects.create(
            business=self.business,
            store=self.store,
            name="Caja cerrada histórica",
            code="DASH-CLOSED",
        )
        CashSession.objects.create(
            business=self.business,
            store=self.store,
            cash_register=closed_register,
            status=CashSession.Status.CLOSED,
            opened_by=self.owner,
            closed_by=self.owner,
            opened_at=timezone.now() - timedelta(hours=1),
            opening_amount="8.00",
            expected_cash_amount="8.00",
            counted_cash_amount="8.00",
            difference_amount="0.00",
            closed_at=timezone.now(),
        )
        closed_response = self.client.get(reverse("core:home"))
        self.assertContains(closed_response, "Caja cerrada")
        self.assertNotContains(closed_response, "Sesión abierta")
        CashSession.objects.create(
            business=self.business,
            store=self.store,
            cash_register=self.cash_register,
            opened_by=self.owner,
            opening_amount="10.00",
            expected_cash_amount="15.00",
        )
        second_register = CashRegister.objects.create(
            business=self.business,
            store=self.store,
            name="Caja secundaria",
            code="DASH-02",
        )
        CashSession.objects.create(
            business=self.business,
            store=self.store,
            cash_register=second_register,
            opened_by=self.owner,
            opening_amount="20.00",
            expected_cash_amount="27.00",
        )
        foreign_store = create_store(
            self.business, name="Otra tienda", code="DASH-OTHER"
        )
        foreign_register = CashRegister.objects.create(
            business=self.business,
            store=foreign_store,
            name="Caja ajena",
            code="DASH-X",
        )
        CashSession.objects.create(
            business=self.business,
            store=foreign_store,
            cash_register=foreign_register,
            opened_by=self.owner,
            opening_amount="999.00",
            expected_cash_amount="999.00",
        )

        response = self.client.get(reverse("core:home"))

        self.assertContains(response, "2 cajas abiertas")
        self.assertContains(response, "Caja secundaria")
        self.assertNotContains(response, "Caja ajena")
        self.assertNotContains(response, "42,00")

    @patch("apps.core.views.build_dashboard_context")
    def test_superuser_without_business_keeps_administrative_mode(self, composer):
        admin = CustomUser.objects.create_superuser(
            email="admin-dashboard@example.com",
            password="safe-password",
            role=RoleChoices.OWNER,
            first_name="Admin",
            last_name="Dashboard",
            phone="600000099",
        )
        self.client.force_login(admin)

        response = self.client.get(reverse("core:home"))

        self.assertContains(response, "Acceso administrativo sin una empresa asignada")
        composer.assert_not_called()

    def test_admin_htmx_request_keeps_the_complete_administrative_home(self):
        admin = CustomUser.objects.create_superuser(
            email="admin-htmx@example.com",
            password="safe-password",
            role=RoleChoices.OWNER,
            first_name="Admin",
            last_name="HTMX",
            phone="600000098",
        )
        self.client.force_login(admin)

        response = self.client.get(reverse("core:home"), HTTP_HX_REQUEST="true")

        self.assertTemplateUsed(response, "core/home.html")
        self.assertNotContains(response, 'id="dashboard-content"')
        self.assertContains(response, "Administración")
