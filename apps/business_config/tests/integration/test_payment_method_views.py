from django.test import TestCase
from django.urls import reverse

from apps.business_config.services import create_business_configuration
from apps.core.models import Business
from apps.payments.forms import PaymentMethodAdminForm
from apps.payments.models import PaymentMethod
from apps.payments.selectors import get_mvp_payment_methods_for_business
from apps.users.models import CustomUser, RoleChoices


class PaymentMethodConfigurationTests(TestCase):
    def setUp(self):
        self.business = Business.objects.create(name="Sala", slug="sala-methods")
        create_business_configuration(
            business=self.business,
            legal_name="Sala SL",
            tax_identifier="B12345678",
            phone="600000000",
            email="sala@example.com",
            address_line_1="Calle Uno",
            postal_code="28001",
            city="Madrid",
            province="Madrid",
        )
        self.owner = CustomUser.objects.create_user(
            email="owner-methods@example.com",
            password="secret",
            business=self.business,
            role=RoleChoices.OWNER,
        )
        self.methods = [
            PaymentMethod.objects.create(business=self.business, name=name, code=code)
            for code, name in (
                ("transfer", "Transferencia"),
                ("card", "Tarjeta"),
                ("cash", "Efectivo"),
                ("bizum", "Bizum"),
            )
        ]
        self.card = next(method for method in self.methods if method.code == "card")
        self.url = reverse("business_config:payment_method", args=[self.card.pk])

    def test_selector_is_tenant_scoped_mvp_only_and_commercially_ordered(self):
        other = Business.objects.create(name="Otra", slug="otra-methods")
        PaymentMethod.objects.create(business=other, name="Otra tarjeta", code="card")
        self.assertEqual(
            [
                method.code
                for method in get_mvp_payment_methods_for_business(
                    business=self.business
                )
            ],
            ["cash", "card", "bizum", "transfer"],
        )

    def test_form_exposes_only_allowed_fields(self):
        self.assertEqual(
            set(PaymentMethodAdminForm().fields), {"name", "is_active", "allows_refund"}
        )

    def test_owner_updates_allowed_fields_and_forged_immutable_fields_are_ignored(self):
        self.client.force_login(self.owner)
        response = self.client.post(
            self.url,
            {
                "name": "Tarjeta bancaria",
                "is_active": "",
                "allows_refund": "on",
                "code": "cash",
                "affects_cash_register": "on",
                "business": 999,
            },
        )
        self.assertRedirects(response, reverse("business_config:pos"))
        self.card.refresh_from_db()
        self.assertEqual(self.card.name, "Tarjeta bancaria")
        self.assertFalse(self.card.is_active)
        self.assertTrue(self.card.allows_refund)
        self.assertEqual(self.card.code, "card")
        self.assertFalse(self.card.affects_cash_register)
        self.assertEqual(self.card.business, self.business)

    def test_forged_cash_flag_cannot_break_cash_invariant(self):
        cash = next(method for method in self.methods if method.code == "cash")
        self.client.force_login(self.owner)
        response = self.client.post(
            reverse("business_config:payment_method", args=[cash.pk]),
            {
                "name": "Efectivo caja",
                "is_active": "on",
                "allows_refund": "on",
                "code": "card",
                "affects_cash_register": "",
            },
        )
        self.assertRedirects(response, reverse("business_config:pos"))
        cash.refresh_from_db()
        self.assertEqual(cash.code, "cash")
        self.assertTrue(cash.affects_cash_register)
        for method in self.methods:
            method.refresh_from_db()
            if method.code != "cash":
                self.assertFalse(method.affects_cash_register)

    def test_cross_tenant_pk_is_not_disclosed(self):
        other = Business.objects.create(name="Otra", slug="otra-method")
        foreign = PaymentMethod.objects.create(
            business=other, name="Tarjeta", code="card"
        )
        self.client.force_login(self.owner)
        url = reverse("business_config:payment_method", args=[foreign.pk])
        self.assertEqual(self.client.get(url).status_code, 404)
        self.assertEqual(self.client.post(url, {"name": "Hack"}).status_code, 404)
        foreign.refresh_from_db()
        self.assertEqual(foreign.name, "Tarjeta")

    def test_manager_and_cashier_are_denied(self):
        for role in (RoleChoices.MANAGER, RoleChoices.CASHIER):
            user = CustomUser.objects.create_user(
                email=f"{role}-methods@example.com",
                password="secret",
                business=self.business,
                role=role,
            )
            self.client.force_login(user)
            self.assertEqual(self.client.get(self.url).status_code, 403)
