"""Smoke tests con plantillas reales del modulo sales."""

from decimal import Decimal

from django.test import TestCase, override_settings
from django.urls import reverse

from apps.sales.models import SaleReturnStatusChoices, SaleStatusChoices
from apps.sales.services import (
    add_sale_line,
    add_sale_return_line,
    complete_sale,
    open_sale,
)
from apps.sales.tests.factories import (
    create_pos_settings,
    create_sale_return,
    create_sales_business,
    create_sales_inventory_item,
    create_sales_product,
    create_sales_store,
    create_sales_tax,
    create_sales_user,
)
from apps.users.models import RoleChoices


@override_settings(
    ROOT_URLCONF="config.urls",
    LOGIN_URL="/users/login/",
)
class SaleTemplatesSmokeIntegrationTests(TestCase):
    password = "testpass123"

    def setUp(self):  # noqa: N802
        self.business = create_sales_business(name="Negocio templates")
        self.store = create_sales_store(business=self.business, name="Tienda templates")
        self.owner = create_sales_user(
            business=self.business,
            role=RoleChoices.OWNER,
            password=self.password,
        )
        self.pos_settings = create_pos_settings(
            business=self.business,
            require_open_cash_register=False,
            require_pin_for_sensitive_actions=False,
            enable_stock_control=True,
        )
        self.tax = create_sales_tax(business=self.business)
        self.product = create_sales_product(
            business=self.business,
            tax=self.tax,
            name="Producto templates",
            base_price=Decimal("10.00"),
        )
        self.inventory_item = create_sales_inventory_item(
            business=self.business,
            store=self.store,
            product=self.product,
            current_stock=Decimal("10.000"),
        )

    def login_as_owner(self):
        logged_in = self.client.login(
            email=self.owner.email,
            password=self.password,
        )
        self.assertTrue(logged_in)

    def _create_completed_sale_with_line(self):
        sale = open_sale(
            business=self.business,
            store=self.store,
            opened_by=self.owner,
        )
        line = add_sale_line(
            business=self.business,
            sale=sale,
            product=self.product,
            quantity=Decimal("2.000"),
            user=self.owner,
        )
        complete_sale(
            business=self.business,
            sale=sale,
            closed_by=self.owner,
        )
        sale.refresh_from_db()
        self.assertEqual(sale.status, SaleStatusChoices.COMPLETED)
        return sale, line

    def _create_draft_return_with_line(self, *, sale, line, restock=True):
        return_doc = create_sale_return(
            business=self.business,
            store=self.store,
            original_sale=sale,
            created_by=self.owner,
            reason="Prueba de devolucion",
        )
        add_sale_return_line(
            business=self.business,
            return_doc=return_doc,
            original_line=line,
            quantity=Decimal("1.000"),
            restock=restock,
            user=self.owner,
        )
        return return_doc

    def test_sales_templates_smoke_endpoints_return_200(self):
        self.login_as_owner()
        sale, line = self._create_completed_sale_with_line()
        return_doc = self._create_draft_return_with_line(sale=sale, line=line)

        sale_list_response = self.client.get(
            reverse("sales:sale_list", kwargs={"store_id": self.store.pk})
        )
        sale_detail_response = self.client.get(
            reverse(
                "sales:sale_detail",
                kwargs={"store_id": self.store.pk, "sale_pk": sale.pk},
            )
        )
        sale_open_response = self.client.get(
            reverse("sales:sale_open", kwargs={"store_id": self.store.pk})
        )
        return_list_response = self.client.get(
            reverse("sales:return_list", kwargs={"store_id": self.store.pk})
        )
        return_detail_response = self.client.get(
            reverse(
                "sales:return_detail",
                kwargs={"store_id": self.store.pk, "return_pk": return_doc.pk},
            )
        )

        self.assertEqual(sale_list_response.status_code, 200)
        self.assertEqual(sale_detail_response.status_code, 200)
        self.assertEqual(sale_open_response.status_code, 200)
        self.assertEqual(return_list_response.status_code, 200)
        self.assertEqual(return_detail_response.status_code, 200)

    def test_return_complete_requires_pin_and_accepts_valid_pin(self):
        self.login_as_owner()
        self.pos_settings.require_pin_for_sensitive_actions = True
        self.pos_settings.save(
            update_fields=["require_pin_for_sensitive_actions", "updated_at"]
        )
        self.owner.set_pin("1234")
        self.owner.save(update_fields=["pin_hash", "updated_at"])

        sale, line = self._create_completed_sale_with_line()
        return_doc = self._create_draft_return_with_line(
            sale=sale, line=line, restock=True
        )

        detail_response = self.client.get(
            reverse(
                "sales:return_detail",
                kwargs={"store_id": self.store.pk, "return_pk": return_doc.pk},
            )
        )
        self.assertEqual(detail_response.status_code, 200)
        self.assertContains(detail_response, 'name="pin"')

        no_pin_response = self.client.post(
            reverse(
                "sales:return_complete",
                kwargs={
                    "store_id": self.store.pk,
                    "return_pk": return_doc.pk,
                },
            ),
            data={},
        )
        return_doc.refresh_from_db()

        self.assertEqual(no_pin_response.status_code, 302)
        self.assertEqual(return_doc.status, SaleReturnStatusChoices.DRAFT)
        self.assertIsNone(return_doc.completed_at)

        with_pin_response = self.client.post(
            reverse(
                "sales:return_complete",
                kwargs={
                    "store_id": self.store.pk,
                    "return_pk": return_doc.pk,
                },
            ),
            data={"pin": "1234"},
        )
        return_doc.refresh_from_db()

        self.assertEqual(with_pin_response.status_code, 302)
        self.assertEqual(return_doc.status, SaleReturnStatusChoices.COMPLETED)
        self.assertIsNotNone(return_doc.completed_at)
