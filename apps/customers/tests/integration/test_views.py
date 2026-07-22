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
