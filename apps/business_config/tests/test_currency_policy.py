"""E-P01: authoritative EUR writes, immutable legacy and PostgreSQL races."""

from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from threading import Barrier
from uuid import uuid4
from unittest.mock import patch

from django.contrib import admin
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import connection, connections
from django.forms.models import model_to_dict
from django.test import Client, RequestFactory, TransactionTestCase
from django.urls import reverse

from apps.business_config.currency import ensure_eur_for_business
from apps.business_config.forms import BusinessProfileForm
from apps.business_config.models import BusinessProfile
from apps.business_config.services import (
    create_business_configuration,
    update_business_profile,
)
from apps.cash_register.models import CashMovement, CashRegister, CashSession
from apps.cash_register.services import CashRegisterService
from apps.core.models import Business
from apps.payments.services import register_sale_payment
from apps.sales.services import open_sale, complete_sale
from tests.performance import phase3_billing_audit as audit
from tests.performance.phase3_harness import payload, url


def legacy(dataset):
    # Only fixture simulation of rows persisted before E-P01, never an app writer.
    BusinessProfile.objects.filter(business=dataset.business).update(
        currency_code="USD"
    )


class CurrencyPolicyTests(TransactionTestCase):
    def fixture(self, label, invoice=False):
        return audit.fixture("eur-policy-" + label, 1, invoice)

    def assert_blocked(self, callback):
        with self.assertRaisesMessage(ValidationError, "Netxodo solo admite EUR"):
            callback()

    def payment(self, d, sale, key=None, amount=None):
        return register_sale_payment(
            business=d.business,
            sale_id=sale.pk,
            method_id=d.methods[1].pk,
            amount=sale.total_amount if amount is None else amount,
            user=d.user,
            idempotency_key=key or uuid4(),
            cash_session_id=d.session.pk,
        )

    def test_new_configuration_eur_and_usd_and_missing_profile_default(self):
        d, _ = self.fixture("new")
        data = model_to_dict(d.business.profile)
        data = {
            k: data[k]
            for k in (
                "legal_name",
                "phone",
                "email",
                "address_line_1",
                "postal_code",
                "city",
                "province",
            )
        }
        for code in ("USD", "GBP", "JPY", "eur", "EUR"):
            b = Business.objects.create(
                name=code, slug="new-" + code.lower() + uuid4().hex[:8]
            )
            with self.subTest(currency=code):
                if code != "EUR":
                    self.assert_blocked(
                        lambda: create_business_configuration(
                            business=b,
                            tax_identifier=uuid4().hex[:12],
                            currency_code=code,
                            **data,
                        )
                    )
                    self.assertFalse(
                        BusinessProfile.objects.filter(business=b).exists()
                    )
                else:
                    p, _ = create_business_configuration(
                        business=b,
                        tax_identifier=uuid4().hex[:12],
                        currency_code=code,
                        **data,
                    )
                    self.assertEqual(p.currency_code, "EUR")
        # An absent profile has the pre-existing implicit EUR contract; no row created.
        b = Business.objects.create(name="Unconfigured EUR", slug="unconfigured")
        ensure_eur_for_business(b.pk)
        self.assertFalse(BusinessProfile.objects.filter(business=b).exists())

    def test_profile_form_service_model_and_direct_post_reject_eur_to_usd(self):
        d, _ = self.fixture("config")
        p = d.business.profile
        data = {**model_to_dict(p), "currency_code": "USD"}
        form = BusinessProfileForm(data=data, instance=p)
        self.assertFalse(form.is_valid())
        self.assertIn("currency_code", form.errors)
        self.assert_blocked(
            lambda: update_business_profile(
                business=d.business, updated_by=d.user, currency_code="USD"
            )
        )
        p.currency_code = "USD"
        self.assert_blocked(p.save)
        client = Client()
        client.force_login(d.user)
        response = client.post(reverse("business_config:profile"), data)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Netxodo solo admite EUR")
        p.refresh_from_db()
        self.assertEqual(p.currency_code, "EUR")

    def test_admin_form_and_delete_cannot_bypass(self):
        d, _ = self.fixture("admin")
        d.user.is_staff = d.user.is_superuser = True
        d.user.save(update_fields=["is_staff", "is_superuser"])
        client = Client()
        client.force_login(d.user)
        p = d.business.profile
        response = client.post(
            reverse("admin:business_config_businessprofile_change", args=[p.pk]),
            {**model_to_dict(p), "currency_code": "USD", "_save": "Save"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Netxodo solo admite EUR")
        model_admin = admin.site._registry[BusinessProfile]
        request = RequestFactory().post("/admin/")
        request.user = d.user
        self.assertTrue(model_admin.has_delete_permission(request, p))
        legacy(d)
        response = client.post(
            reverse("admin:business_config_businessprofile_delete", args=[p.pk]),
            {"post": "yes"},
        )
        self.assertEqual(response.status_code, 403)

        p.refresh_from_db()
        self.assertEqual(p.currency_code, "USD")
        self.assertFalse(model_admin.has_delete_permission(request, p))
        with self.assertRaises(PermissionDenied):
            model_admin.delete_queryset(
                request, BusinessProfile.objects.filter(pk=p.pk)
            )
        self.assertTrue(BusinessProfile.objects.filter(pk=p.pk).exists())
        self.assert_blocked(p.delete)
        other, _ = self.fixture("admin-eur-delete")
        eur_profile = BusinessProfile.objects.get(business=other.business)
        selected = BusinessProfile.objects.filter(pk__in=[p.pk, eur_profile.pk])
        with self.assertRaises(PermissionDenied):
            model_admin.delete_queryset(request, selected)
        self.assertEqual(selected.count(), 2)
        model_admin.delete_queryset(
            request, BusinessProfile.objects.filter(pk=eur_profile.pk)
        )
        self.assertFalse(BusinessProfile.objects.filter(pk=eur_profile.pk).exists())
        self.assertTrue(BusinessProfile.objects.filter(pk=p.pk).exists())

    def test_legacy_currency_unchanged_and_cannot_be_relabelled(self):
        d, _ = self.fixture("legacy-config")
        legacy(d)
        p = update_business_profile(
            business=d.business, updated_by=d.user, trade_name="Updated safely"
        )
        self.assertEqual(p.currency_code, "USD")
        for code in ("EUR", "GBP", ""):
            with (
                self.subTest(code=code),
                self.assertRaisesMessage(ValidationError, "moneda histórica"),
            ):
                update_business_profile(
                    business=d.business, updated_by=d.user, currency_code=code
                )
        p.refresh_from_db()
        self.assertEqual(p.currency_code, "USD")

    def test_stale_profile_does_not_allow_sale_payment_or_cash(self):
        d, sale = self.fixture("legacy-write")
        complete_sale(business=d.business, sale=sale, closed_by=d.user)
        self.assertEqual(d.business.profile.currency_code, "EUR")
        legacy(d)
        before = audit.snapshot(d, [sale])
        callbacks = [
            lambda: open_sale(business=d.business, store=d.store, opened_by=d.user),
            lambda: self.payment(d, sale),
            lambda: CashRegisterService().register_cash_in(
                business=d.business,
                store_id=d.store.pk,
                cash_register_id=d.register.pk,
                cash_session_id=d.session.pk,
                user=d.user,
                amount=Decimal("1"),
                reason="test",
            ),
            lambda: CashRegisterService().review_cash_count(
                business=d.business,
                store_id=d.store.pk,
                cash_register_id=d.register.pk,
                cash_session_id=d.session.pk,
                user=d.user,
                counted_amount=Decimal("0"),
            ),
            lambda: sale.save(),
        ]
        for callback in callbacks:
            self.assert_blocked(callback)
            self.assertEqual(audit.snapshot(d, [sale]), before)
        self.assertFalse(CashMovement.objects.filter(business=d.business).exists())

    def test_f1_f2_pending_emission_blocked_without_number_or_payment_changes(self):
        for invoice in (False, True):
            d, sale = self.fixture("invoice-" + str(invoice), invoice)
            audit.paid(d, sale)
            legacy(d)
            before = audit.snapshot(d, [sale])
            key = uuid4()
            for _ in range(2):
                self.assert_blocked(lambda: audit.issue(d, sale, key=key))
                self.assertEqual(audit.snapshot(d, [sale]), before)

    def test_p01_and_p02_legacy_checkout_post_and_uuid_retries_are_blocked(self):
        for full in (True, False):
            d, sale = self.fixture("recover-" + str(full))
            complete_sale(business=d.business, sale=sale, closed_by=d.user)
            key = uuid4()
            self.payment(
                d, sale, key=key, amount=sale.total_amount if full else Decimal("5")
            )
            data = payload(d, sale)
            if not full:
                CashRegisterService().close_cash_session(
                    business=d.business,
                    store_id=d.store.pk,
                    cash_register_id=d.register.pk,
                    cash_session_id=d.session.pk,
                    user=d.user,
                    counted_cash_amount=Decimal("0"),
                )
                register = CashRegister.objects.create(
                    business=d.business, store=d.store, name="Recovery", code="REC"
                )
                session = CashSession.objects.create(
                    business=d.business,
                    store=d.store,
                    cash_register=register,
                    opened_by=d.user,
                )
                data["recovery_cash_session"] = session.pk
                data["amount"] = str(sale.total_amount - Decimal("5"))
                data["recovery_confirm"] = "on"
            legacy(d)
            before = audit.snapshot(d, [sale])
            client = Client()
            client.force_login(d.user)
            for _ in range(2):
                response = client.post(url(sale), data, HTTP_HX_REQUEST="true")
                self.assertEqual(response.status_code, 200 if full else 422)
                self.assertContains(
                    response,
                    "Netxodo solo admite EUR",
                    status_code=200 if full else 422,
                )
                self.assertEqual(audit.snapshot(d, [sale]), before)
            # Payment replay has potential debt effects, so must also block.
            self.assert_blocked(
                lambda: self.payment(
                    d, sale, key=key, amount=sale.total_amount if full else Decimal("5")
                )
            )
            self.assertEqual(audit.snapshot(d, [sale]), before)

    def test_historical_reads_print_and_billing_uuid_replay_do_not_mutate(self):
        d, sale = self.fixture("history", True)
        audit.paid(d, sale)
        document = audit.issue(d, sale)
        legacy(d)
        before = audit.snapshot(d, [sale])
        client = Client()
        client.force_login(d.user)
        for name, args in (
            ("sales:sale_detail", [d.store.pk, sale.pk]),
            ("billing:document_detail", [d.store.pk, document.pk]),
            ("billing:document_print", [d.store.pk, document.pk]),
            ("business_config:profile", []),
        ):
            response = client.get(reverse(name, args=args))
            self.assertEqual(response.status_code, 200)
            self.assertContains(response, "moneda histórica")
            self.assertEqual(audit.snapshot(d, [sale]), before)
        self.assertEqual(
            audit.issue(d, sale, key=document.idempotency_key).pk, document.pk
        )
        self.assertEqual(audit.snapshot(d, [sale]), before)
        document.total_amount = Decimal("999")
        with self.assertRaises(ValidationError):
            document.save()
        self.assertEqual(audit.snapshot(d, [sale]), before)

    def test_cross_business_cannot_recover_or_read_history(self):
        d, sale = self.fixture("tenant")
        audit.paid(d, sale)
        doc = audit.issue(d, sale)
        other, _ = self.fixture("other")
        legacy(d)
        before = audit.snapshot(d, [sale])
        client = Client()
        client.force_login(other.user)
        for name, args in (
            ("billing:document_print", [d.store.pk, doc.pk]),
            ("sales:sale_checkout", [d.store.pk, sale.pk]),
        ):
            self.assertIn(client.get(reverse(name, args=args)).status_code, (403, 404))
        with self.assertRaises(ValidationError):
            audit.billing.issue_sale_document(
                business=other.business,
                sale_id=sale.pk,
                series_id=audit.series_for(d, sale).pk,
                issued_by=other.user,
                idempotency_key=uuid4(),
            )
        self.assertEqual(audit.snapshot(d, [sale]), before)

    def test_postgres_concurrent_legacy_payments_and_emissions_leave_no_effect(self):
        if connection.vendor != "postgresql":
            self.skipTest("PostgreSQL required")
        for emission in (False, True):
            d, sale = self.fixture("race-" + str(emission))
            if emission:
                audit.paid(d, sale)
            else:
                complete_sale(business=d.business, sale=sale, closed_by=d.user)
            legacy(d)
            before = audit.snapshot(d, [sale])
            barrier = Barrier(2)
            key = uuid4()

            def worker():
                connections.close_all()
                try:
                    barrier.wait(timeout=10)
                    self.assert_blocked(
                        lambda: (
                            audit.issue(d, sale, key=key)
                            if emission
                            else self.payment(d, sale, key=key)
                        )
                    )
                    return "blocked"
                finally:
                    connections.close_all()

            with ThreadPoolExecutor(max_workers=2) as pool:
                futures = [pool.submit(worker) for _ in range(2)]
                self.assertEqual(
                    [f.result(timeout=20) for f in futures], ["blocked", "blocked"]
                )
            self.assertEqual(audit.snapshot(d, [sale]), before)

    def test_legacy_direct_billing_post_and_new_cash_session_are_blocked(self):
        d, sale = self.fixture("direct-commands")
        audit.paid(d, sale)
        register = CashRegister.objects.create(
            business=d.business, store=d.store, name="New", code="NEW"
        )
        legacy(d)
        before = audit.snapshot(d, [sale])
        client = Client()
        client.force_login(d.user)
        for _ in range(2):
            response = client.post(
                reverse("billing:issue_sale_document", args=[d.store.pk, sale.pk]),
                {
                    "series": audit.series_for(d, sale).pk,
                    "idempotency_key": str(uuid4()),
                },
            )
            self.assertEqual(response.status_code, 200)
            self.assertContains(response, "Netxodo solo admite EUR", status_code=200)
            self.assertEqual(audit.snapshot(d, [sale]), before)
        self.assert_blocked(
            lambda: CashRegisterService().open_cash_session(
                business=d.business,
                store_id=d.store.pk,
                cash_register_id=register.pk,
                user=d.user,
                opening_amount=Decimal("0"),
            )
        )
        self.assertEqual(audit.snapshot(d, [sale]), before)

    def test_legacy_prices_blocked_but_metadata_and_historical_csv_still_readable(self):
        d, sale = self.fixture("prices-and-report")
        audit.paid(d, sale)
        legacy(d)
        product = d.products[0]
        product.name = "Safe metadata"
        product.save()
        product.base_price = Decimal("99")
        self.assert_blocked(product.save)
        product.refresh_from_db()
        self.assertEqual(product.base_price, Decimal("10"))
        before = audit.snapshot(d, [sale])
        client = Client()
        client.force_login(d.user)
        response = client.get(reverse("reports:sales_export"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Aviso de moneda histórica")
        self.assertContains(response, "12.10")
        self.assertEqual(audit.snapshot(d, [sale]), before)

    def test_superuser_historical_print_uses_document_business_warning(self):
        d, sale = self.fixture("super-history")
        audit.paid(d, sale)
        document = audit.issue(d, sale)
        legacy(d)
        other, _ = self.fixture("super-user")
        other.user.is_superuser = True
        other.user.save(update_fields=["is_superuser"])
        before = audit.snapshot(d, [sale])
        client = Client()
        client.force_login(other.user)
        response = client.get(
            reverse("billing:document_print", args=[d.store.pk, document.pk])
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "moneda histórica")
        self.assertEqual(audit.snapshot(d, [sale]), before)

    def test_legacy_profile_cannot_be_transferred_to_enable_old_business(self):
        d, _ = self.fixture("transfer")
        legacy(d)
        p = BusinessProfile.objects.get(business=d.business)
        other = Business.objects.create(name="Other", slug="profile-transfer-target")
        p.business = other
        with self.assertRaisesMessage(ValidationError, "trasladar"):
            p.save()
        p.refresh_from_db()
        self.assertEqual(p.business_id, d.business.pk)
        self.assertEqual(p.currency_code, "USD")

    def test_new_sale_is_blocked_before_t1_and_inventory_calls(self):
        from apps.sales.checkout import run_checkout, PaymentIntent

        d, sale = self.fixture("before-t1")
        legacy(d)
        before = audit.snapshot(d, [sale])
        with patch("apps.sales.checkout.complete_sale") as complete:
            self.assert_blocked(
                lambda: run_checkout(
                    business=d.business,
                    sale=sale,
                    user=d.user,
                    intents=[
                        PaymentIntent(
                            method_id=d.methods[1].pk,
                            amount=sale.total_amount,
                            idempotency_key=uuid4(),
                        )
                    ],
                    series_id=audit.series_for(d, sale).pk,
                    billing_key=uuid4(),
                    allow_split=False,
                )
            )
            complete.assert_not_called()
        with patch("apps.sales.services.decrease_stock") as stock:
            self.assert_blocked(
                lambda: complete_sale(business=d.business, sale=sale, closed_by=d.user)
            )
            stock.assert_not_called()
        self.assertEqual(audit.snapshot(d, [sale]), before)
