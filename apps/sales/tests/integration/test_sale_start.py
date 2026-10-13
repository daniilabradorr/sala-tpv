"""Direct TPV start, deferred cash context and security regressions."""

from decimal import Decimal
from uuid import uuid4

from django.contrib.messages import get_messages
from django.core.exceptions import ValidationError
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.cash_register.models import CashRegister, CashSession
from apps.customers.models import CustomerAccount
from apps.inventory.models import StockMovement
from apps.payments.models import Payment
from apps.sales.checkout import run_checkout
from apps.sales.models import Sale
from apps.sales.services import add_sale_line, complete_sale, update_sale_cash_session
from apps.sales.tests.factories import (
    create_pos_settings,
    create_sales_business,
    create_sales_customer,
    create_sales_product,
    create_sales_store,
    create_sales_tax,
    create_sales_user,
    create_store_access,
)
from apps.users.models import RoleChoices


@override_settings(
    STORAGES={
        "staticfiles": {
            "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"
        }
    }
)
class SaleStartTests(TestCase):
    def setUp(self):
        self.business = create_sales_business()
        self.store = create_sales_store(business=self.business)
        self.owner = create_sales_user(business=self.business)
        self.settings = create_pos_settings(
            business=self.business,
            require_open_cash_register=True,
            enable_stock_control=False,
        )
        self.client.force_login(self.owner)
        self.url = reverse("sales:sale_start", args=[self.store.pk])

    def session(self, *, store=None, active=True, closed=False):
        store = store or self.store
        register = CashRegister.objects.create(
            business=store.business,
            store=store,
            name=f"Caja {uuid4().hex[:8]}",
            code=uuid4().hex[:10],
            is_active=active,
        )
        session = CashSession.objects.create(
            business=store.business,
            store=store,
            cash_register=register,
            opened_by=self.owner,
        )
        if closed:
            session.status = CashSession.Status.CLOSED
            session.closed_at = timezone.now()
            session.closed_by = self.owner
            session.counted_cash_amount = Decimal("0.00")
            session.save()
        return session

    def start(self, data=None):
        response = self.client.post(self.url, data or {})
        sale = Sale.objects.latest("pk")
        self.assertRedirects(
            response, reverse("sales:sale_detail", args=[self.store.pk, sale.pk])
        )
        self.assertEqual(sale.status, "open")
        self.assertEqual(sale.document_type_requested, "ticket")
        return sale

    def test_no_session_required_until_economic_step(self):
        create_sales_customer(business=self.business)
        sale = self.start({"document_type_requested": "invoice"})
        self.assertIsNone(sale.customer_id)
        self.assertIsNone(sale.cash_session_id)
        self.assertIsNone(sale.cash_register_id)
        self.assertFalse(CashSession.objects.exists())
        self.assertFalse(CashRegister.objects.exists())
        product = create_sales_product(
            business=self.business,
            tax=create_sales_tax(business=self.business),
            track_stock=False,
        )
        add_sale_line(
            business=self.business,
            sale=sale,
            product=product,
            quantity=1,
            user=self.owner,
        )
        with self.assertRaises(ValidationError):
            complete_sale(business=self.business, sale=sale, closed_by=self.owner)
        with self.assertRaisesMessage(
            ValidationError, "La sesión de caja está cerrada o no existe."
        ):
            run_checkout(
                business=self.business,
                sale=sale,
                user=self.owner,
                intents=(),
                series_id=None,
                billing_key=uuid4(),
                allow_split=True,
            )
        sale.refresh_from_db()
        self.assertEqual(sale.status, "open")
        self.assertFalse(Payment.objects.exists())
        self.assertFalse(StockMovement.objects.exists())
        self.assertFalse(sale.billing_documents.exists())
        page = self.client.get(
            reverse("sales:sale_detail", args=[self.store.pk, sale.pk])
        )
        self.assertContains(page, "Abrir caja")
        self.assertContains(page, 'id="product-grid"')

    def test_single_valid_pair_even_with_unused_registers(self):
        session = self.session()
        self.session(active=False)
        self.session(closed=True)
        CashRegister.objects.create(
            business=self.business, store=self.store, name="Sin sesión", code="EMPTY"
        )
        other_store = create_sales_store(business=self.business)
        self.session(store=other_store)
        sale = self.start()
        self.assertEqual(sale.cash_session, session)
        self.assertEqual(sale.cash_register, session.cash_register)

    def test_multiple_sessions_are_selected_inside_workspace(self):
        first = self.session()
        second = self.session()
        sale = self.start()
        self.assertIsNone(sale.cash_session_id)
        self.assertIsNone(sale.cash_register_id)
        workspace = reverse("sales:sale_detail", args=[self.store.pk, sale.pk])
        response = self.client.get(workspace)
        self.assertContains(response, "Usar sesión")
        self.assertEqual(
            set(response.context["cash_session_form"].fields["cash_session"].queryset),
            {first, second},
        )
        url = reverse("sales:sale_cash_session_update", args=[self.store.pk, sale.pk])
        response = self.client.post(url, {"cash_session": second.pk})
        self.assertRedirects(response, workspace)
        sale.refresh_from_db()
        self.assertEqual(sale.cash_session, second)
        self.assertEqual(sale.cash_register, second.cash_register)
        self.assertEqual(Sale.objects.count(), 1)

    def test_contextual_session_and_customer_are_preserved(self):
        session = self.session()
        self.session()
        customer = create_sales_customer(business=self.business)
        response = self.client.post(
            reverse("sales:sale_start_for_session", args=[self.store.pk, session.pk]),
            {"customer": customer.pk},
        )
        sale = Sale.objects.get()
        self.assertRedirects(
            response, reverse("sales:sale_detail", args=[self.store.pk, sale.pk])
        )
        self.assertEqual(sale.customer, customer)
        self.assertEqual(sale.cash_session, session)
        self.assertEqual(sale.document_type_requested, "ticket")

    def test_get_refresh_back_and_legacy_route_are_safe(self):
        for name in ("sale_start", "sale_open"):
            response = self.client.get(reverse(f"sales:{name}", args=[self.store.pk]))
            self.assertRedirects(
                response, reverse("sales:sale_list", args=[self.store.pk])
            )
            self.assertTemplateNotUsed(response, "sales/sale_open.html")
        self.assertFalse(Sale.objects.exists())
        sale = self.start()
        workspace = reverse("sales:sale_detail", args=[self.store.pk, sale.pk])
        self.client.get(workspace)
        self.client.get(workspace)
        self.client.get(self.url)
        self.assertEqual(Sale.objects.count(), 1)
        # A deliberate manual POST is a separate intent, without fiscal/payment keys.
        self.start()
        self.assertEqual(Sale.objects.count(), 2)

    def test_authorized_roles_and_store_isolation(self):
        for role in (RoleChoices.OWNER, RoleChoices.MANAGER, RoleChoices.CASHIER):
            with self.subTest(role=role):
                user = create_sales_user(business=self.business, role=role)
                if role != RoleChoices.OWNER:
                    create_store_access(
                        business=self.business, user=user, store=self.store
                    )
                self.client.force_login(user)
                sale = self.start({"store_id": 99999})
                self.assertEqual(sale.store, self.store)
                self.assertEqual(sale.opened_by, user)
        blocked = create_sales_user(business=self.business, role=RoleChoices.CASHIER)
        self.client.force_login(blocked)
        count = Sale.objects.count()
        self.assertEqual(self.client.post(self.url).status_code, 403)
        self.assertEqual(Sale.objects.count(), count)
        foreign = create_sales_store(business=create_sales_business())
        self.client.force_login(self.owner)
        self.assertEqual(
            self.client.post(
                reverse("sales:sale_start", args=[foreign.pk])
            ).status_code,
            403,
        )
        self.assertEqual(Sale.objects.count(), count)

    def test_session_assignment_rejects_invalid_context_and_closed_sales(self):
        sale = self.start()
        other = self.session(store=create_sales_store(business=self.business))
        closed = self.session(closed=True)
        inactive = self.session(active=False)
        url = reverse("sales:sale_cash_session_update", args=[self.store.pk, sale.pk])
        for session in (other, closed, inactive):
            response = self.client.post(url, {"cash_session": session.pk})
            self.assertTrue(list(get_messages(response.wsgi_request)))
            sale.refresh_from_db()
            self.assertIsNone(sale.cash_session_id)
            with self.assertRaises(ValidationError):
                update_sale_cash_session(
                    business=self.business,
                    sale=sale,
                    cash_session=session,
                    updated_by=self.owner,
                )
        valid = self.session()
        denied = create_sales_user(business=self.business, role=RoleChoices.CASHIER)
        with self.assertRaises(ValidationError):
            update_sale_cash_session(
                business=self.business, sale=sale, cash_session=valid, updated_by=denied
            )
        self.client.force_login(denied)
        self.assertEqual(
            self.client.post(url, {"cash_session": valid.pk}).status_code, 403
        )
        self.client.force_login(self.owner)
        sale.status = "cancelled"
        sale.save()
        self.assertEqual(
            self.client.post(url, {"cash_session": valid.pk}).status_code, 403
        )
        with self.assertRaises(ValidationError):
            update_sale_cash_session(
                business=self.business,
                sale=sale,
                cash_session=valid,
                updated_by=self.owner,
            )

    def test_all_navigation_starts_are_post_forms(self):
        customer = create_sales_customer(business=self.business)
        CustomerAccount.objects.create(business=self.business, customer=customer)
        pages = (
            reverse("core:home"),
            reverse("sales:sale_list", args=[self.store.pk]),
            reverse("customers:customer_detail", args=[customer.pk]),
        )
        for url in pages:
            page = self.client.get(url)
            self.assertContains(page, f'action="{self.url}"')
            self.assertContains(page, "data-nx-sale-start")
            self.assertNotContains(page, f'href="{self.url}"')
            self.assertNotContains(
                page, reverse("sales:sale_open", args=[self.store.pk])
            )
        page = self.client.get(pages[-1])
        self.assertContains(page, f'name="customer" value="{customer.pk}"')
