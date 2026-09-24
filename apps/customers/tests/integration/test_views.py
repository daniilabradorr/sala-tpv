from decimal import Decimal

from django.test import TestCase
from django.urls import reverse, resolve

from apps.customers.models import Customer
from apps.customers.tests.factories import (
    create_account,
    create_customer_user,
    create_entry,
)
from apps.users.models import RoleChoices
from apps.users.tests.factories import create_business
from apps.users.tests.factories import create_store, create_store_access
from apps.core.shell import ACTIVE_STORE_SESSION_KEY
from apps.sales.tests.factories import create_sale
from apps.sales.models import SaleStatusChoices


class CustomerViewTests(TestCase):
    def setUp(self):
        self.business = create_business(slug="views")
        self.other_business = create_business(name="Other", slug="views2")
        self.cashier = create_customer_user(
            business=self.business, role=RoleChoices.CASHIER
        )
        self.manager = create_customer_user(
            business=self.business, role=RoleChoices.MANAGER
        )
        self.owner = create_customer_user(
            business=self.business, role=RoleChoices.OWNER
        )
        self.account = create_account(business=self.business)
        self.other_account = create_account(business=self.other_business)

    def test_auth_list_detail_and_create(self):
        url = reverse("customers:customer_list")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 302)
        self.client.force_login(self.cashier)
        response = self.client.get(url)
        self.assertContains(response, self.account.customer.name)
        self.assertContains(
            response, "Una ficha global para todas las tiendas del negocio."
        )
        self.assertContains(response, 'class="customer-table table-scroll"', html=False)
        self.assertNotContains(response, self.other_account.customer.name)
        self.assertEqual(
            self.client.get(
                reverse(
                    "customers:customer_detail", args=[self.other_account.customer.pk]
                )
            ).status_code,
            404,
        )
        self.assertEqual(
            self.client.get(reverse("customers:customer_create")).status_code, 200
        )
        response = self.client.post(
            reverse("customers:customer_create"),
            {"customer_type": "person", "name": "Nuevo", "country_code": "ES"},
        )
        self.assertEqual(response.status_code, 302)
        c = Customer.objects.get(name="Nuevo")
        self.assertEqual(c.account.credit_limit, Decimal("0.00"))
        self.assertFalse(c.account.is_blocked)

    def test_empty_list_has_a_useful_create_action(self):
        empty_business = create_business(name="Empty", slug="empty-customers")
        empty_owner = create_customer_user(
            business=empty_business, role=RoleChoices.OWNER
        )
        self.client.force_login(empty_owner)

        response = self.client.get(reverse("customers:customer_list"))

        self.assertContains(response, "No hay clientes con estos filtros.")
        self.assertContains(response, reverse("customers:customer_create"))
        self.assertNotContains(response, self.account.customer.name)
        self.assertNotContains(response, self.other_account.customer.name)

    def test_list_htmx_returns_only_results_and_varies(self):
        self.client.force_login(self.owner)
        response = self.client.get(
            reverse("customers:customer_list"),
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'id="customer-results"', count=1)
        self.assertNotContains(response, "<html")
        self.assertIn("HX-Request", response.headers["Vary"])

    def test_mobile_filters_use_dialog_and_tabs_swap_navigation_with_panel(self):
        self.client.force_login(self.owner)
        response = self.client.get(reverse("customers:customer_list"))
        self.assertContains(response, '<dialog id="customer-filters"', html=False)
        self.assertContains(response, "data-nx-drawer")

        detail_url = reverse(
            "customers:customer_detail", args=[self.account.customer.pk]
        )
        response = self.client.get(
            detail_url,
            {"tab": "account"},
            HTTP_HX_REQUEST="true",
        )
        self.assertContains(response, 'id="customer-workspace-content"', count=1)
        self.assertContains(
            response,
            'role="tab" aria-selected="true" href="?tab=account"',
            html=False,
        )
        self.assertContains(response, 'id="customer-tab-panel"', count=1)

    def test_new_sale_prefers_sellable_active_store_and_falls_back(self):
        store_a = create_store(self.business, name="Tienda A", code="A")
        store_b = create_store(self.business, name="Tienda B", code="B")
        detail_url = reverse(
            "customers:customer_detail", args=[self.account.customer.pk]
        )

        self.client.force_login(self.owner)
        session = self.client.session
        session[ACTIVE_STORE_SESSION_KEY] = store_b.pk
        session.save()
        response = self.client.get(detail_url)
        self.assertContains(
            response,
            reverse("sales:sale_open", kwargs={"store_id": store_b.pk}),
        )

        create_store_access(self.business, self.manager, store_a, can_sell=True)
        create_store_access(self.business, self.manager, store_b, can_sell=False)
        self.client.force_login(self.manager)
        session = self.client.session
        session[ACTIVE_STORE_SESSION_KEY] = store_b.pk
        session.save()
        response = self.client.get(detail_url)
        self.assertContains(
            response,
            reverse("sales:sale_open", kwargs={"store_id": store_a.pk}),
        )
        self.assertNotContains(
            response,
            f"{reverse('sales:sale_open', kwargs={'store_id': store_b.pk})}?customer=",
        )

    def test_pending_debt_cta_requires_can_sell_but_history_only_requires_access(self):
        read_store = create_store(self.business, name="Solo lectura", code="READ")
        sell_store = create_store(self.business, name="Vendible", code="SELL")
        create_store_access(self.business, self.manager, read_store, can_sell=False)
        create_store_access(self.business, self.manager, sell_store, can_sell=True)
        read_sale = create_sale(
            business=self.business,
            store=read_store,
            opened_by=self.owner,
            customer=self.account.customer,
            status=SaleStatusChoices.COMPLETED,
            total_amount=Decimal("40.00"),
        )
        sell_sale = create_sale(
            business=self.business,
            store=sell_store,
            opened_by=self.owner,
            customer=self.account.customer,
            status=SaleStatusChoices.COMPLETED,
            total_amount=Decimal("60.00"),
        )
        for sale in (read_sale, sell_sale):
            create_entry(
                business=self.business,
                account=self.account,
                amount=sale.total_amount,
                balance_after=sale.total_amount,
                sale=sale,
            )
        self.client.force_login(self.manager)
        detail = reverse("customers:customer_detail", args=[self.account.customer.pk])
        history = self.client.get(detail, {"tab": "sales"})
        self.assertContains(history, f">#{read_sale.pk}</a>", html=False)
        account = self.client.get(detail, {"tab": "account"})
        self.assertNotContains(
            account,
            reverse("payments:create", args=[read_store.pk, read_sale.pk]),
        )
        self.assertContains(
            account,
            reverse("payments:create", args=[sell_store.pk, sell_sale.pk]),
        )

    def test_sales_tab_rejects_malformed_dates_without_server_error(self):
        self.client.force_login(self.owner)
        url = reverse("customers:customer_detail", args=[self.account.customer.pk])
        for value in ("texto", "2026-02-31"):
            with self.subTest(value=value):
                response = self.client.get(
                    url, {"tab": "sales", "date_from": value, "date_to": value}
                )
                self.assertEqual(response.status_code, 200)
                self.assertTrue(response.context["sales_filter_errors"])

    def test_permissions_and_post_actions(self):
        self.client.force_login(self.cashier)
        for name in ["customer_update", "customer_account_settings"]:
            self.assertEqual(
                self.client.get(
                    reverse(f"customers:{name}", args=[self.account.customer.pk])
                ).status_code,
                403,
            )
        for name in ["customer_deactivate", "customer_reactivate"]:
            self.assertEqual(
                self.client.post(
                    reverse(f"customers:{name}", args=[self.account.customer.pk])
                ).status_code,
                403,
            )
        self.client.force_login(self.manager)
        self.assertEqual(
            self.client.get(
                reverse("customers:customer_update", args=[self.account.customer.pk])
            ).status_code,
            200,
        )
        response = self.client.post(
            reverse(
                "customers:customer_account_settings", args=[self.account.customer.pk]
            ),
            {"credit_limit": "25.00", "is_blocked": "on"},
        )
        self.assertEqual(response.status_code, 302)
        self.account.refresh_from_db()
        self.assertEqual(self.account.balance, Decimal("0.00"))
        self.assertTrue(self.account.is_blocked)
        self.assertEqual(
            self.client.get(
                reverse(
                    "customers:customer_deactivate", args=[self.account.customer.pk]
                )
            ).status_code,
            405,
        )
        self.assertEqual(
            self.client.post(
                reverse(
                    "customers:customer_deactivate", args=[self.account.customer.pk]
                )
            ).status_code,
            302,
        )
        self.account.customer.refresh_from_db()
        self.assertFalse(self.account.customer.is_active)
        create_entry(business=self.business, account=self.account)
        self.assertTrue(self.account.entries.exists())
        self.assertEqual(
            self.client.post(
                reverse(
                    "customers:customer_reactivate", args=[self.account.customer.pk]
                )
            ).status_code,
            302,
        )
        self.account.customer.refresh_from_db()
        self.assertTrue(self.account.customer.is_active)

    def test_routes_config_and_templates(self):
        import config.urls

        self.assertTrue(
            any(
                getattr(p.pattern, "_route", "") == "customers/"
                for p in config.urls.urlpatterns
            )
        )
        for name in [
            "customer_list",
            "customer_create",
            "customer_detail",
            "customer_update",
            "customer_deactivate",
            "customer_reactivate",
            "customer_account_settings",
        ]:
            args = (
                []
                if name in ["customer_list", "customer_create"]
                else [self.account.customer.pk]
            )
            self.assertEqual(
                resolve(reverse(f"customers:{name}", args=args)).namespace, "customers"
            )
        self.client.force_login(self.owner)
        self.assertEqual(
            self.client.post(
                reverse("customers:customer_create"),
                {"customer_type": "person", "name": "", "country_code": "ES"},
            ).status_code,
            200,
        )
        self.assertEqual(
            self.client.get(
                reverse("customers:customer_detail", args=[self.account.customer.pk])
            ).status_code,
            200,
        )
        self.assertEqual(
            self.client.get(
                reverse(
                    "customers:customer_account_settings",
                    args=[self.account.customer.pk],
                )
            ).status_code,
            200,
        )
