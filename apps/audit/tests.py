from datetime import date, datetime, timezone
from decimal import Decimal
from enum import Enum
from uuid import uuid4

from django.contrib import admin
from django.contrib.auth.models import Permission
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models.deletion import ProtectedError
from django.test import RequestFactory, TestCase

from apps.audit.admin import AuditEventAdmin, BusinessFilter, StoreFilter, UserFilter
from apps.audit.constants import EVENT_MODULES, AuditEventType, AuditModule
from apps.audit.exceptions import (
    AuditImmutableError,
    AuditPayloadError,
    AuditValidationError,
)
from apps.audit.models import AuditEvent
from apps.audit.sanitizers import (
    MAX_DEPTH,
    MAX_ITEMS,
    MAX_STRING_LENGTH,
    REDACTED,
    sanitize_payload,
)
from apps.audit.selectors import get_audit_events
from apps.audit.services import log_event
from apps.core.models import Business
from apps.stores.models import Store
from apps.users.models import CustomUser, RoleChoices


class PayloadEnum(Enum):
    VALUE = "serializable"


class AuditTestMixin:
    @classmethod
    def setUpTestData(cls):
        cls.business = Business.objects.create(name="Business One")
        cls.other_business = Business.objects.create(name="Business Two")
        cls.store = Store.objects.create(
            business=cls.business, name="Store One", code="ONE"
        )
        cls.other_store = Store.objects.create(
            business=cls.other_business, name="Store Two", code="TWO"
        )
        cls.user = CustomUser.objects.create_user(
            business=cls.business,
            email="owner-one@example.com",
            password="audit-test-password",
            role=RoleChoices.OWNER,
            first_name="Owner",
        )
        cls.other_user = CustomUser.objects.create_user(
            business=cls.other_business,
            email="owner-two@example.com",
            password="audit-test-password",
            role=RoleChoices.OWNER,
            first_name="Other",
        )

    def event(self, **overrides):
        values = {
            "business": self.business,
            "store": self.store,
            "user": self.user,
            "event_type": AuditEventType.SALE_COMPLETED,
            "module": AuditModule.SALES,
            "message": "Sale completed",
        }
        values.update(overrides)
        return log_event(**values)


class AuditServiceTests(AuditTestMixin, TestCase):
    def test_event_module_mapping_matches_pre_verifactu_contract(self):
        expected = {
            AuditEventType.SALE_COMPLETED: AuditModule.SALES,
            AuditEventType.SALE_CANCELLED: AuditModule.SALES,
            AuditEventType.SALE_RETURN_COMPLETED: AuditModule.SALES,
            AuditEventType.SALE_RETURN_CANCELLED: AuditModule.SALES,
            AuditEventType.PAYMENT_COMPLETED: AuditModule.PAYMENTS,
            AuditEventType.PAYMENT_REFUNDED: AuditModule.PAYMENTS,
            AuditEventType.PAYMENT_CANCELLED: AuditModule.PAYMENTS,
            AuditEventType.SALE_ON_ACCOUNT_REGISTERED: AuditModule.PAYMENTS,
            AuditEventType.CASH_SESSION_OPENED: AuditModule.CASH_REGISTER,
            AuditEventType.CASH_IN: AuditModule.CASH_REGISTER,
            AuditEventType.CASH_OUT: AuditModule.CASH_REGISTER,
            AuditEventType.CASH_ADJUSTED: AuditModule.CASH_REGISTER,
            AuditEventType.CASH_COUNTED: AuditModule.CASH_REGISTER,
            AuditEventType.CASH_SESSION_CLOSED: AuditModule.CASH_REGISTER,
            AuditEventType.STOCK_INITIALIZED: AuditModule.INVENTORY,
            AuditEventType.STOCK_ADJUSTED: AuditModule.INVENTORY,
            AuditEventType.STOCK_ADJUSTMENT_CANCELLED: AuditModule.INVENTORY,
            AuditEventType.PURCHASE_CREATED: AuditModule.PURCHASES,
            AuditEventType.PURCHASE_ORDERED: AuditModule.PURCHASES,
            AuditEventType.PURCHASE_RECEIVED: AuditModule.PURCHASES,
            AuditEventType.PURCHASE_CANCELLED: AuditModule.PURCHASES,
            AuditEventType.BILLING_DOCUMENT_ISSUED: AuditModule.BILLING,
            AuditEventType.BILLING_DOCUMENT_SUBSTITUTED: AuditModule.BILLING,
            AuditEventType.BILLING_DOCUMENT_RECTIFIED: AuditModule.BILLING,
            AuditEventType.BUSINESS_CONFIG_CHANGED: AuditModule.BUSINESS_CONFIG,
        }

        self.assertEqual(EVENT_MODULES, expected)
        self.assertEqual(len(EVENT_MODULES), 25)

    def test_creates_complete_event_and_allows_system_user(self):
        event = self.event(ip_address="2001:db8::1", user=None)

        self.assertEqual(event.business, self.business)
        self.assertEqual(event.store, self.store)
        self.assertIsNone(event.user)
        self.assertEqual(event.ip_address, "2001:db8::1")
        self.assertIsNotNone(event.created_at)
        self.assertIsNotNone(event.updated_at)

    def test_business_is_required(self):
        with self.assertRaises(AuditValidationError):
            self.event(business=None)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                AuditEvent.objects.create(
                    event_type=AuditEventType.SALE_COMPLETED,
                    module=AuditModule.SALES,
                    message="No business",
                )

    def test_message_must_be_a_non_blank_string(self):
        for message in ("", "   ", None):
            with self.subTest(message=message):
                with self.assertRaises(AuditValidationError):
                    self.event(message=message)

        event = self.event(message="Sale completed")
        self.assertEqual(event.message, "Sale completed")

    def test_rejects_cross_business_store_and_user(self):
        with self.assertRaises(AuditValidationError):
            self.event(store=self.other_store)
        with self.assertRaises(AuditValidationError):
            self.event(user=self.other_user)

    def test_superuser_may_be_actor_for_any_business(self):
        superuser = CustomUser.objects.create_superuser(
            email="root@example.com",
            password="secret",
            role=RoleChoices.OWNER,
            first_name="Root",
            last_name="User",
            phone="600000001",
        )
        event = self.event(user=superuser)
        self.assertEqual(event.user, superuser)

    def test_derives_entity_reference_from_model(self):
        event = self.event(entity=self.store)
        self.assertEqual(event.entity_type, "stores.store")
        self.assertEqual(event.entity_id, str(self.store.pk))

    def test_accepts_manual_entity_reference(self):
        event = self.event(entity_type="external.record", entity_id=uuid4())
        self.assertEqual(event.entity_type, "external.record")
        self.assertIsInstance(event.entity_id, str)

    def test_requires_entity_reference_pair_and_exclusive_input(self):
        with self.assertRaises(AuditValidationError):
            self.event(entity_type="sales.sale")
        with self.assertRaises(AuditValidationError):
            self.event(entity_id="1")
        with self.assertRaises(AuditValidationError):
            self.event(entity=self.store, entity_type="stores.store", entity_id="1")

    def test_rejects_blank_manual_entity_references(self):
        for entity_type, entity_id in (
            ("", ""),
            ("   ", "123"),
            ("sales.sale", "   "),
        ):
            with self.subTest(entity_type=entity_type, entity_id=entity_id):
                with self.assertRaises(AuditValidationError):
                    self.event(entity_type=entity_type, entity_id=entity_id)

    def test_model_clean_rejects_blank_manual_entity_references(self):
        event = AuditEvent(
            business=self.business,
            event_type=AuditEventType.SALE_COMPLETED,
            module=AuditModule.SALES,
            message="Invalid reference",
            entity_type=" ",
            entity_id="123",
        )
        with self.assertRaises(ValidationError):
            event.clean()

    def test_database_enforces_entity_reference_pair(self):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                AuditEvent.objects.create(
                    business=self.business,
                    event_type=AuditEventType.SALE_COMPLETED,
                    module=AuditModule.SALES,
                    message="Invalid",
                    entity_type="sales.sale",
                )

    def test_rejects_cross_business_entity(self):
        with self.assertRaises(AuditValidationError):
            self.event(entity=self.other_store)

    def test_validates_event_module_mapping_and_unknown_event(self):
        with self.assertRaises(AuditValidationError):
            self.event(module=AuditModule.PAYMENTS)
        with self.assertRaises(AuditValidationError):
            self.event(event_type="UNKNOWN_EVENT")

    def test_validates_ip_address(self):
        with self.assertRaises(AuditValidationError):
            self.event(ip_address="not-an-ip")

    def test_rolls_back_with_callers_atomic_transaction(self):
        with self.assertRaises(RuntimeError):
            with transaction.atomic():
                self.event()
                raise RuntimeError("domain operation failed")
        self.assertFalse(AuditEvent.objects.exists())


class AuditSanitizerTests(AuditTestMixin, TestCase):
    def test_nested_payload_redacts_secrets_and_preserves_cash_session_id(self):
        self.assertEqual(
            sanitize_payload(
                {
                    "safe": {
                        "token": "token-value",
                        "pin": "1234",
                        "cash_session_id": 1,
                    }
                }
            ),
            {
                "safe": {
                    "token": REDACTED,
                    "pin": REDACTED,
                    "cash_session_id": 1,
                }
            },
        )

    def test_preserves_pin_configuration_boolean_but_redacts_real_pins(self):
        self.assertEqual(
            sanitize_payload(
                {
                    "require_pin_for_sensitive_actions": False,
                    "pin": "1234",
                    "pin_hash": "hash",
                    "employee_pin": "5678",
                    "auth_pin": "9012",
                    "cash_session_id": 42,
                }
            ),
            {
                "require_pin_for_sensitive_actions": False,
                "pin": REDACTED,
                "pin_hash": REDACTED,
                "employee_pin": REDACTED,
                "auth_pin": REDACTED,
                "cash_session_id": 42,
            },
        )

    def test_preserves_cash_session_id_and_redacts_sensitive_session_keys(self):
        self.assertEqual(
            sanitize_payload(
                {
                    "cash_session_id": 123,
                    "session_id": "django-session",
                    "auth_session_id": "auth-session",
                    "session_token": "session-token",
                }
            ),
            {
                "cash_session_id": 123,
                "session_id": REDACTED,
                "auth_session_id": REDACTED,
                "session_token": REDACTED,
            },
        )

    def test_recursively_redacts_normalized_secret_keys(self):
        payload = {
            "password": "one",
            "Password_Hash": "two",
            "raw-password": "three",
            "nested": {"API Key": "four", "authorization": "five"},
            "items": [{"pin_hash": "six"}, {"refreshToken": "seven"}],
        }
        event = self.event(metadata=payload)
        self.assertEqual(event.metadata["password"], REDACTED)
        self.assertEqual(event.metadata["Password_Hash"], REDACTED)
        self.assertEqual(event.metadata["nested"]["API Key"], REDACTED)
        self.assertEqual(event.metadata["items"][1]["refreshToken"], REDACTED)

    def test_redacts_prefixed_and_suffixed_secret_keys(self):
        keys = (
            "db_password",
            "password_confirmation",
            "user_password",
            "payment_api_key",
            "stripe_api_key",
            "oauth_refresh_token",
            "client_secret_value",
            "authorization_header",
            "session_token",
        )
        event = self.event(metadata={key: "sensitive" for key in keys})
        self.assertEqual(event.metadata, {key: REDACTED for key in keys})

    def test_preserves_fiscal_hashes(self):
        event = self.event(metadata={"current_hash": "abc", "previous_hash": "def"})
        self.assertEqual(
            event.metadata, {"current_hash": "abc", "previous_hash": "def"}
        )

    def test_converts_supported_json_types(self):
        identifier = uuid4()
        moment = datetime(2026, 9, 15, 12, 30, tzinfo=timezone.utc)
        event = self.event(
            old_payload={"amount": Decimal("12.30")},
            new_payload={"id": identifier, "day": date(2026, 9, 15)},
            metadata={"moment": moment, "enum": PayloadEnum.VALUE, "tuple": (1, 2)},
        )
        self.assertEqual(event.old_payload["amount"], "12.30")
        self.assertEqual(event.new_payload["id"], str(identifier))
        self.assertEqual(event.new_payload["day"], "2026-09-15")
        self.assertEqual(event.metadata["moment"], moment.isoformat())
        self.assertEqual(event.metadata["enum"], "serializable")
        self.assertEqual(event.metadata["tuple"], [1, 2])

    def test_converts_and_sanitizes_nested_sets(self):
        event = self.event(metadata={"values": {"visible", "another"}})
        self.assertCountEqual(event.metadata["values"], ["visible", "another"])

        with self.assertRaises(AuditPayloadError):
            self.event(metadata={"values": set(range(MAX_ITEMS + 1))})
        with self.assertRaises(AuditPayloadError):
            self.event(metadata={"values": {object()}})

    def test_none_payloads_remain_null(self):
        event = self.event()
        self.assertIsNone(event.old_payload)
        self.assertIsNone(event.new_payload)
        self.assertIsNone(event.metadata)

    def test_rejects_unknown_objects_and_non_dictionary_root(self):
        with self.assertRaises(AuditPayloadError):
            self.event(metadata={"object": object()})
        with self.assertRaises(AuditPayloadError):
            self.event(metadata=["not", "an", "object"])

    def test_rejects_payload_limits(self):
        with self.assertRaises(AuditPayloadError):
            self.event(metadata={"value": "x" * (MAX_STRING_LENGTH + 1)})
        with self.assertRaises(AuditPayloadError):
            self.event(metadata={str(index): index for index in range(MAX_ITEMS + 1)})
        nested = "value"
        for _ in range(MAX_DEPTH + 1):
            nested = {"nested": nested}
        with self.assertRaises(AuditPayloadError):
            self.event(metadata=nested)


class AuditImmutabilityTests(AuditTestMixin, TestCase):
    def test_instance_save_and_delete_are_forbidden(self):
        event = self.event()
        event.message = "Changed"
        with self.assertRaises(AuditImmutableError):
            event.save()
        with self.assertRaises(AuditImmutableError):
            event.delete()

    def test_queryset_update_delete_and_bulk_update_are_forbidden(self):
        event = self.event()
        with self.assertRaises(AuditImmutableError):
            AuditEvent.objects.filter(pk=event.pk).update(message="Changed")
        with self.assertRaises(AuditImmutableError):
            AuditEvent.objects.filter(pk=event.pk).delete()
        event.message = "Changed"
        with self.assertRaises(AuditImmutableError):
            AuditEvent.objects.bulk_update([event], ["message"])
        with self.assertRaises(AuditImmutableError):
            AuditEvent.objects.all().bulk_update([event], ["message"])

    def test_bulk_create_cannot_upsert_or_ignore_conflicts(self):
        event = self.event()
        replacement = AuditEvent(
            pk=event.pk,
            business=self.business,
            event_type=event.event_type,
            module=event.module,
            message="Changed by upsert",
        )
        with self.assertRaises(AuditImmutableError):
            AuditEvent.objects.bulk_create(
                [replacement],
                update_conflicts=True,
                update_fields=["message"],
                unique_fields=["pk"],
            )
        event.refresh_from_db()
        self.assertEqual(event.message, "Sale completed")

        with self.assertRaises(AuditImmutableError):
            AuditEvent.objects.bulk_create([replacement], ignore_conflicts=True)
        with self.assertRaises(AuditImmutableError):
            AuditEvent.objects.all().bulk_create(
                [replacement],
                update_conflicts=True,
                update_fields=["message"],
                unique_fields=["pk"],
            )

    def test_user_and_store_are_protected(self):
        self.event()
        with self.assertRaises(ProtectedError):
            self.user.delete()
        with self.assertRaises(ProtectedError):
            self.store.delete()

    def test_deactivating_user_and_store_preserves_history(self):
        event = self.event()
        self.user.is_active = False
        self.user.save(update_fields=["is_active"])
        self.store.is_active = False
        self.store.save(update_fields=["is_active"])

        event.refresh_from_db()
        self.assertEqual(event.user_id, self.user.pk)
        self.assertEqual(event.store_id, self.store.pk)


class AuditSelectorTests(AuditTestMixin, TestCase):
    def test_selector_and_manager_are_business_scoped(self):
        own = self.event()
        self.event(
            business=self.other_business,
            store=self.other_store,
            user=self.other_user,
        )
        self.assertEqual(list(get_audit_events(business=self.business)), [own])
        self.assertEqual(list(AuditEvent.objects.for_business(self.business.pk)), [own])


class AuditAdminTests(AuditTestMixin, TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.model_admin = AuditEventAdmin(AuditEvent, admin.site)
        self.own_event = self.event()
        self.other_event = self.event(
            business=self.other_business,
            store=self.other_store,
            user=self.other_user,
        )

    def _request(self, user, query=None):
        request = self.factory.get("/admin/audit/auditevent/", query or {})
        request.user = user
        return request

    def test_admin_is_read_only(self):
        request = self._request(self.user)
        self.assertFalse(self.model_admin.has_add_permission(request))
        self.assertFalse(self.model_admin.has_change_permission(request))
        self.assertFalse(self.model_admin.has_delete_permission(request))
        self.assertEqual(
            set(self.model_admin.get_readonly_fields(request, self.own_event)),
            {field.name for field in AuditEvent._meta.fields},
        )

    def test_normal_user_sees_only_own_business_with_view_permission(self):
        self.user.is_staff = True
        self.user.user_permissions.add(
            Permission.objects.get(codename="view_auditevent")
        )
        request = self._request(self.user)
        self.assertTrue(self.model_admin.has_view_permission(request))
        self.assertEqual(list(self.model_admin.get_queryset(request)), [self.own_event])

    def test_cashier_without_view_permission_cannot_view_audit(self):
        self.user.role = RoleChoices.CASHIER
        self.user.is_staff = True
        self.user.save(update_fields=["role", "is_staff"])

        self.assertFalse(self.model_admin.has_view_permission(self._request(self.user)))

    def test_manipulated_business_filter_cannot_escape_tenant_queryset(self):
        self.user.is_staff = True
        self.user.user_permissions.add(
            Permission.objects.get(codename="view_auditevent")
        )
        request = self._request(self.user, {"business": self.other_business.pk})
        base_queryset = self.model_admin.get_queryset(request)
        filter_instance = BusinessFilter(
            request,
            {"business": [str(self.other_business.pk)]},
            AuditEvent,
            self.model_admin,
        )

        self.assertFalse(filter_instance.queryset(request, base_queryset).exists())

    def test_superuser_sees_all_businesses(self):
        superuser = CustomUser.objects.create_superuser(
            email="admin@example.com",
            password="secret",
            role=RoleChoices.OWNER,
            first_name="Admin",
            last_name="User",
            phone="600000002",
        )
        queryset = self.model_admin.get_queryset(self._request(superuser))
        self.assertCountEqual(queryset, [self.own_event, self.other_event])

    def test_non_superuser_without_business_sees_nothing(self):
        orphan = CustomUser(
            email="orphan@example.com", role=RoleChoices.OWNER, is_staff=True
        )
        CustomUser.objects.bulk_create([orphan])
        self.assertFalse(self.model_admin.get_queryset(self._request(orphan)).exists())

    def test_related_filter_lookups_are_tenant_scoped(self):
        request = self._request(self.user)
        for filter_class, expected in (
            (BusinessFilter, {str(self.business.pk)}),
            (StoreFilter, {str(self.store.pk)}),
            (UserFilter, {str(self.user.pk)}),
        ):
            filter_instance = filter_class(request, {}, AuditEvent, self.model_admin)
            self.assertEqual(
                {value for value, _label in filter_instance.lookup_choices}, expected
            )
