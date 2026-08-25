"""Tests unitarios de formularios del módulo sales."""

from decimal import Decimal
import uuid

from django.db import IntegrityError, transaction
from django.test import TestCase
from django.utils import timezone

from apps.cash_register.models import CashRegister, CashSession
from apps.sales.forms import (
    SaleCancelForm,
    SaleFilterForm,
    SaleLineCreateForm,
    SaleOpenForm,
    SaleReturnCreateForm,
    SaleReturnLineCreateForm,
    SaleReturnLineUpdateForm,
)
from apps.sales.models import (
    RequestedDocumentTypeChoices,
    SaleReturnStatusChoices,
    SaleStatusChoices,
)
from apps.sales.selectors import get_returnable_sale_lines
from apps.sales.tests.factories import (
    create_pos_settings,
    create_sale,
    create_sale_line,
    create_sale_return,
    create_sale_return_line,
    create_sales_business,
    create_sales_customer,
    create_sales_product,
    create_sales_store,
    create_sales_tax,
    create_sales_user,
)


class SaleFormsTests(TestCase):
    def setUp(self):  # noqa: N802
        self.business = create_sales_business()
        self.other_business = create_sales_business(name="Otro negocio")
        self.store = create_sales_store(business=self.business)
        self.owner = create_sales_user(business=self.business, pin="1234")
        self.tax = create_sales_tax(business=self.business)
        self.product = create_sales_product(
            business=self.business,
            tax=self.tax,
            base_price=Decimal("10.00"),
        )
        self.customer = create_sales_customer(
            business=self.business,
            name="Cliente permitido",
        )
        self.other_customer = create_sales_customer(
            business=self.other_business,
            name="Cliente ajeno",
        )
        self.pos_settings = create_pos_settings(
            business=self.business,
            require_open_cash_register=False,
            require_pin_for_sensitive_actions=False,
        )
        self.sale = create_sale(
            business=self.business,
            store=self.store,
            opened_by=self.owner,
        )

    def create_cash_register(self, *, business=None, store=None, name="Caja 1"):
        return CashRegister.objects.create(
            business=business or self.business,
            store=store or self.store,
            name=name,
            code=f"CAJA-{uuid.uuid4().hex[:8].upper()}",
        )

    def create_cash_session(
        self, *, cash_register, status=CashSession.Status.OPEN, opened_by=None
    ):
        session = CashSession.objects.create(
            business=cash_register.business,
            store=cash_register.store,
            cash_register=cash_register,
            expected_cash_amount=Decimal("0.00"),
            difference_amount=Decimal("0.00"),
            opened_by=opened_by or self.owner,
        )
        if status == CashSession.Status.CLOSED:
            session.status = CashSession.Status.CLOSED
            session.closed_at = timezone.now()
            session.closed_by = opened_by or self.owner
            session.counted_cash_amount = Decimal("0.00")
            session.save()
        return session

    def test_filter_form_rejects_reversed_date_range(self):
        form = SaleFilterForm(
            data={
                "date_from": "2026-07-20",
                "date_to": "2026-07-10",
            },
            business=self.business,
            store=self.store,
        )

        self.assertFalse(form.is_valid())
        self.assertIn("__all__", form.errors)

    def test_filter_form_only_exposes_customers_from_current_business(self):
        form = SaleFilterForm(
            business=self.business,
            store=self.store,
        )

        customer_ids = set(
            form.fields["customer"].queryset.values_list("pk", flat=True)
        )

        self.assertIn(self.customer.pk, customer_ids)
        self.assertNotIn(self.other_customer.pk, customer_ids)

    def test_open_form_accepts_ticket_without_customer_or_cash_when_not_required(self):
        form = SaleOpenForm(
            data={
                "document_type_requested": RequestedDocumentTypeChoices.TICKET,
                "customer": "",
                "cash_register": "",
                "cash_session": "",
            },
            business=self.business,
            store=self.store,
            user=self.owner,
        )

        self.assertTrue(form.is_valid(), form.errors)

    def test_open_form_requires_customer_when_invoice_is_requested(self):
        form = SaleOpenForm(
            data={
                "document_type_requested": RequestedDocumentTypeChoices.INVOICE,
                "customer": "",
                "cash_register": "",
                "cash_session": "",
            },
            business=self.business,
            store=self.store,
            user=self.owner,
        )

        self.assertFalse(form.is_valid())
        self.assertIn("customer", form.errors)

    def test_open_form_rejects_customer_from_other_business(self):
        form = SaleOpenForm(
            data={
                "document_type_requested": RequestedDocumentTypeChoices.INVOICE,
                "customer": self.other_customer.pk,
                "cash_register": "",
                "cash_session": "",
            },
            business=self.business,
            store=self.store,
            user=self.owner,
        )

        self.assertFalse(form.is_valid())
        self.assertIn("customer", form.errors)

    def test_open_form_requires_cash_register_and_session_when_configured(self):
        self.pos_settings.require_open_cash_register = True
        self.pos_settings.save()

        form = SaleOpenForm(
            data={"document_type_requested": RequestedDocumentTypeChoices.TICKET},
            business=self.business,
            store=self.store,
            user=self.owner,
        )

        self.assertFalse(form.is_valid())
        self.assertIn("cash_register", form.errors)
        self.assertIn("cash_session", form.errors)

    def test_open_form_accepts_valid_cash_context_when_required(self):
        self.pos_settings.require_open_cash_register = True
        self.pos_settings.save()
        register = self.create_cash_register()
        session = self.create_cash_session(cash_register=register)
        form = SaleOpenForm(
            data={
                "document_type_requested": RequestedDocumentTypeChoices.TICKET,
                "cash_register": register.pk,
                "cash_session": session.pk,
            },
            business=self.business,
            store=self.store,
            user=self.owner,
        )

        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data["cash_register"], register)
        self.assertEqual(form.cleaned_data["cash_session"], session)

    def test_open_form_accepts_valid_cash_context_when_optional(self):
        register = self.create_cash_register()
        session = self.create_cash_session(cash_register=register)
        form = SaleOpenForm(
            data={
                "document_type_requested": RequestedDocumentTypeChoices.TICKET,
                "cash_register": register.pk,
                "cash_session": session.pk,
            },
            business=self.business,
            store=self.store,
            user=self.owner,
        )

        self.assertTrue(form.is_valid(), form.errors)

    def test_open_form_rejects_non_numeric_register_id_without_raising(self):
        form = SaleOpenForm(
            data={
                "document_type_requested": RequestedDocumentTypeChoices.TICKET,
                "cash_register": "manipulated",
                "cash_session": "",
            },
            business=self.business,
            store=self.store,
            user=self.owner,
        )

        self.assertFalse(form.is_valid())
        self.assertIn("cash_register", form.errors)

    def test_open_form_rejects_inactive_register(self):
        register = self.create_cash_register()
        register.is_active = False
        register.save()
        form = SaleOpenForm(
            data={
                "document_type_requested": RequestedDocumentTypeChoices.TICKET,
                "cash_register": register.pk,
                "cash_session": "",
            },
            business=self.business,
            store=self.store,
            user=self.owner,
        )

        self.assertFalse(form.is_valid())
        self.assertIn("cash_register", form.errors)

    def test_open_form_limits_sessions_to_selected_register(self):
        register = self.create_cash_register()
        session = self.create_cash_session(cash_register=register)
        other_register = self.create_cash_register(name="Caja 2")
        other_session = self.create_cash_session(cash_register=other_register)

        form = SaleOpenForm(
            data={"cash_register": register.pk},
            business=self.business,
            store=self.store,
            user=self.owner,
        )

        session_ids = set(
            form.fields["cash_session"].queryset.values_list("pk", flat=True)
        )
        self.assertEqual(session_ids, {session.pk})
        self.assertNotIn(other_session.pk, session_ids)

    def test_database_rejects_open_session_with_closed_at(self):
        register = self.create_cash_register()
        session = self.create_cash_session(cash_register=register)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                CashSession.objects.filter(pk=session.pk).update(
                    closed_at=timezone.now()
                )

    def test_open_form_rejects_cash_register_without_session(self):
        register = self.create_cash_register()
        form = SaleOpenForm(
            data={
                "document_type_requested": RequestedDocumentTypeChoices.TICKET,
                "cash_register": register.pk,
                "cash_session": "",
            },
            business=self.business,
            store=self.store,
            user=self.owner,
        )

        self.assertFalse(form.is_valid())
        self.assertIn("cash_session", form.errors)

    def test_open_form_rejects_session_without_cash_register(self):
        register = self.create_cash_register()
        session = self.create_cash_session(cash_register=register)
        form = SaleOpenForm(
            data={
                "document_type_requested": RequestedDocumentTypeChoices.TICKET,
                "cash_register": "",
                "cash_session": session.pk,
            },
            business=self.business,
            store=self.store,
            user=self.owner,
        )

        self.assertFalse(form.is_valid())
        self.assertIn("cash_session", form.errors)

    def test_open_form_rejects_closed_session(self):
        register = self.create_cash_register()
        session = self.create_cash_session(
            cash_register=register, status=CashSession.Status.CLOSED
        )
        form = SaleOpenForm(
            data={
                "document_type_requested": RequestedDocumentTypeChoices.TICKET,
                "cash_register": register.pk,
                "cash_session": session.pk,
            },
            business=self.business,
            store=self.store,
            user=self.owner,
        )

        self.assertFalse(form.is_valid())
        self.assertIn("cash_session", form.errors)

    def test_open_form_rejects_session_from_another_register(self):
        register = self.create_cash_register()
        other_register = self.create_cash_register(name="Caja 2")
        session = self.create_cash_session(cash_register=other_register)
        form = SaleOpenForm(
            data={
                "document_type_requested": RequestedDocumentTypeChoices.TICKET,
                "cash_register": register.pk,
                "cash_session": session.pk,
            },
            business=self.business,
            store=self.store,
            user=self.owner,
        )

        self.assertFalse(form.is_valid())
        self.assertIn("cash_session", form.errors)

    def test_open_form_rejects_session_from_another_business(self):
        register = self.create_cash_register()
        other_store = create_sales_store(business=self.other_business)
        other_user = create_sales_user(business=self.other_business)
        other_register = self.create_cash_register(
            business=self.other_business,
            store=other_store,
            name="Caja ajena",
        )
        session = self.create_cash_session(
            cash_register=other_register, opened_by=other_user
        )
        form = SaleOpenForm(
            data={
                "document_type_requested": RequestedDocumentTypeChoices.TICKET,
                "cash_register": register.pk,
                "cash_session": session.pk,
            },
            business=self.business,
            store=self.store,
            user=self.owner,
        )

        self.assertFalse(form.is_valid())
        self.assertIn("cash_session", form.errors)

    def test_open_form_rejects_register_from_another_business(self):
        other_store = create_sales_store(business=self.other_business)
        register = self.create_cash_register(
            business=self.other_business, store=other_store
        )
        form = SaleOpenForm(
            data={
                "document_type_requested": RequestedDocumentTypeChoices.TICKET,
                "cash_register": register.pk,
            },
            business=self.business,
            store=self.store,
            user=self.owner,
        )

        self.assertFalse(form.is_valid())
        self.assertIn("cash_register", form.errors)

    def test_open_form_rejects_register_from_another_store(self):
        other_store = create_sales_store(business=self.business, name="Otra tienda")
        register = self.create_cash_register(store=other_store)
        form = SaleOpenForm(
            data={
                "document_type_requested": RequestedDocumentTypeChoices.TICKET,
                "cash_register": register.pk,
            },
            business=self.business,
            store=self.store,
            user=self.owner,
        )

        self.assertFalse(form.is_valid())
        self.assertIn("cash_register", form.errors)

    def test_line_form_rejects_discount_above_configured_percentage(self):
        self.pos_settings.max_manual_discount_percent = Decimal("20.00")
        self.pos_settings.save()

        form = SaleLineCreateForm(
            data={
                "product": self.product.pk,
                "quantity": "1.000",
                "unit_base_price": "10.00",
                "discount_amount": "3.00",
            },
            business=self.business,
            store=self.store,
            sale=self.sale,
            user=self.owner,
        )

        self.assertFalse(form.is_valid())
        self.assertIn("discount_amount", form.errors)

    def test_line_form_ignores_tampered_manual_price_when_disabled(self):
        self.pos_settings.allow_manual_price = False
        self.pos_settings.save()

        form = SaleLineCreateForm(
            data={
                "product": self.product.pk,
                "quantity": "1.000",
                "unit_base_price": "1.00",
                "discount_amount": "0.00",
            },
            business=self.business,
            store=self.store,
            sale=self.sale,
            user=self.owner,
        )

        self.assertTrue(form.is_valid(), form.errors)
        self.assertIsNone(form.cleaned_data["unit_base_price"])

    def test_cancel_form_requires_valid_pin_when_configured(self):
        self.pos_settings.require_pin_for_sensitive_actions = True
        self.pos_settings.save()

        invalid = SaleCancelForm(
            data={"pin": "9999"},
            sale=self.sale,
            user=self.owner,
        )
        valid = SaleCancelForm(
            data={"pin": "1234"},
            sale=self.sale,
            user=self.owner,
        )

        self.assertFalse(invalid.is_valid())
        self.assertIn("pin", invalid.errors)
        self.assertTrue(valid.is_valid(), valid.errors)


class SaleReturnFormsTests(TestCase):
    def setUp(self):  # noqa: N802
        self.business = create_sales_business()
        self.store = create_sales_store(business=self.business)
        self.owner = create_sales_user(business=self.business)
        create_pos_settings(
            business=self.business,
            require_open_cash_register=False,
            require_pin_for_sensitive_actions=False,
        )
        self.tax = create_sales_tax(business=self.business)
        self.product = create_sales_product(business=self.business, tax=self.tax)
        self.sale = create_sale(
            business=self.business,
            store=self.store,
            opened_by=self.owner,
            status=SaleStatusChoices.COMPLETED,
        )
        self.sale_line = create_sale_line(
            business=self.business,
            sale=self.sale,
            product=self.product,
            quantity=Decimal("3.000"),
        )

    def test_return_create_form_strips_reason_and_rejects_blank(self):
        valid = SaleReturnCreateForm(
            data={"reason": "  Producto defectuoso  "},
            business=self.business,
            sale=self.sale,
            user=self.owner,
        )
        invalid = SaleReturnCreateForm(
            data={"reason": "   "},
            business=self.business,
            sale=self.sale,
            user=self.owner,
        )

        self.assertTrue(valid.is_valid(), valid.errors)
        self.assertEqual(valid.cleaned_data["reason"], "Producto defectuoso")
        self.assertFalse(invalid.is_valid())

    def test_return_line_form_rejects_quantity_above_remaining_capacity(self):
        completed_return = create_sale_return(
            business=self.business,
            store=self.store,
            original_sale=self.sale,
            created_by=self.owner,
            status=SaleReturnStatusChoices.COMPLETED,
        )
        create_sale_return_line(
            business=self.business,
            return_doc=completed_return,
            original_line=self.sale_line,
            quantity=Decimal("2.000"),
        )

        draft_return = create_sale_return(
            business=self.business,
            store=self.store,
            original_sale=self.sale,
            created_by=self.owner,
        )
        returnable_lines = get_returnable_sale_lines(
            business=self.business,
            sale=self.sale,
        )

        form = SaleReturnLineCreateForm(
            data={
                "original_line": self.sale_line.pk,
                "quantity": "2.000",
            },
            business=self.business,
            return_doc=draft_return,
            returnable_lines=returnable_lines,
        )

        self.assertFalse(form.is_valid())
        self.assertIn("quantity", form.errors)

    def test_return_line_update_form_preserves_restock_false_initial(self):
        draft_return = create_sale_return(
            business=self.business,
            store=self.store,
            original_sale=self.sale,
            created_by=self.owner,
        )
        line = create_sale_return_line(
            business=self.business,
            return_doc=draft_return,
            original_line=self.sale_line,
            quantity=Decimal("1.000"),
            restock=False,
        )

        form = SaleReturnLineUpdateForm(
            business=self.business,
            return_doc=draft_return,
            line=line,
            initial={
                "quantity": line.quantity,
                "restock": line.restock,
            },
        )

        self.assertIs(form["restock"].value(), False)
