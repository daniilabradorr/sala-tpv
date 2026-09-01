from dataclasses import dataclass
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from apps.billing.models import BillingDocumentTypeChoices, BillingSeries
from apps.business_config.models import BusinessProfile, POSSettings
from apps.business_config.services import create_business_configuration
from apps.cash_register.models import CashRegister
from apps.catalog.models import Tax
from apps.core.models import Business
from apps.payments.models import PaymentMethod, PaymentMethodCodeChoices
from apps.stores.models import Store
from apps.users.models import CustomUser, RoleChoices


class OnboardingError(Exception):
    """Base error for business provisioning failures."""


class OnboardingDuplicateBusinessError(OnboardingError):
    """Raised when a fiscal identity has already been provisioned."""


class OnboardingInvalidOwnerPasswordError(OnboardingError):
    """Raised when onboarding receives no usable Owner password."""


@dataclass(frozen=True)
class OnboardingResult:
    business: Business
    profile: BusinessProfile
    pos_settings: POSSettings
    tax: Tax
    store: Store
    owner: CustomUser
    cash_register: CashRegister
    payment_methods: tuple[PaymentMethod, ...]
    billing_series: tuple[BillingSeries, ...]


class OnboardingService:
    PAYMENT_METHODS = (
        (PaymentMethodCodeChoices.CASH, PaymentMethodCodeChoices.CASH.label),
        (PaymentMethodCodeChoices.CARD, PaymentMethodCodeChoices.CARD.label),
        (PaymentMethodCodeChoices.BIZUM, PaymentMethodCodeChoices.BIZUM.label),
        (PaymentMethodCodeChoices.TRANSFER, PaymentMethodCodeChoices.TRANSFER.label),
    )
    BILLING_DOCUMENT_TYPES = (
        BillingDocumentTypeChoices.F1,
        BillingDocumentTypeChoices.F2,
        BillingDocumentTypeChoices.F3,
        BillingDocumentTypeChoices.R1,
        BillingDocumentTypeChoices.R5,
    )

    @classmethod
    @transaction.atomic
    def create_business(
        cls,
        *,
        legal_name,
        tax_identifier,
        phone,
        email,
        address_line_1,
        postal_code,
        city,
        province,
        store_name,
        owner_first_name,
        owner_last_name,
        owner_email,
        owner_phone,
        owner_password,
        owner_pin,
        trade_name="",
        address_line_2="",
        country_code="ES",
        store_address_line_1=None,
        store_address_line_2=None,
        store_postal_code=None,
        store_city=None,
        store_province=None,
        store_phone=None,
        store_email=None,
    ):
        if owner_password is None or not str(owner_password).strip():
            raise OnboardingInvalidOwnerPasswordError(
                "La contraseña del propietario es obligatoria."
            )

        normalized_country_code = (country_code or "").strip().upper()
        normalized_tax_identifier = (tax_identifier or "").strip().upper()

        if BusinessProfile.objects.filter(
            country_code=normalized_country_code,
            tax_identifier=normalized_tax_identifier,
        ).exists():
            raise OnboardingDuplicateBusinessError(
                "Ya existe una empresa con esta identidad fiscal."
            )

        normalized_trade_name = (trade_name or "").strip()
        business = Business.objects.create(
            name=normalized_trade_name or (legal_name or "").strip()
        )
        profile, pos_settings = create_business_configuration(
            business=business,
            legal_name=legal_name,
            tax_identifier=normalized_tax_identifier,
            trade_name=normalized_trade_name,
            phone=phone,
            email=email,
            address_line_1=address_line_1,
            address_line_2=address_line_2,
            postal_code=postal_code,
            city=city,
            province=province,
            country_code=normalized_country_code,
            currency_code="EUR",
        )
        tax = Tax.objects.create(
            business=business,
            name="IVA 21%",
            code="IVA_21",
            tax_type=Tax.TAX_TYPE_IVA,
            rate=Decimal("21.00"),
            clave_regimen=Tax.REGIMEN_GENERAL,
            calificacion_operacion=Tax.CALIFICACION_SUJETA_NO_EXENTA,
            operacion_exenta=None,
            has_equivalence_surcharge=False,
            equivalence_surcharge_rate=None,
            is_default=True,
            is_active=True,
        )
        store = Store.objects.create(
            business=business,
            name=store_name,
            address_line_1=cls._fallback(store_address_line_1, profile.address_line_1),
            address_line_2=cls._fallback(store_address_line_2, profile.address_line_2),
            postal_code=cls._fallback(store_postal_code, profile.postal_code),
            city=cls._fallback(store_city, profile.city),
            province=cls._fallback(store_province, profile.province),
            country_code=profile.country_code,
            phone_store=cls._fallback(store_phone, profile.phone),
            email_store=cls._fallback(store_email, profile.email),
            is_active=True,
            is_default=True,
        )
        owner = CustomUser.objects.create_user(
            email=owner_email,
            password=owner_password,
            business=business,
            role=RoleChoices.OWNER,
            first_name=owner_first_name,
            last_name=owner_last_name,
            phone=owner_phone,
            is_active=True,
        )
        owner.set_pin(owner_pin)
        owner.save(update_fields=["pin_hash", "updated_at"])

        cash_register = CashRegister.objects.create(
            business=business,
            store=store,
            name="Caja principal",
            code="CAJA-01",
            is_active=True,
        )
        payment_methods = tuple(
            PaymentMethod.objects.create(
                business=business,
                name=name,
                code=code,
                is_active=True,
                allows_refund=True,
            )
            for code, name in cls.PAYMENT_METHODS
        )
        year = timezone.localdate().year
        billing_series = tuple(
            BillingSeries.objects.create(
                business=business,
                store=store,
                cash_register=None,
                name=f"{document_type.label} - {store.name}",
                document_type=document_type,
                prefix=f"{document_type.value}-{store.code}",
                year=year,
                current_number=0,
                padding=6,
                is_active=True,
            )
            for document_type in cls.BILLING_DOCUMENT_TYPES
        )
        return OnboardingResult(
            business=business,
            profile=profile,
            pos_settings=pos_settings,
            tax=tax,
            store=store,
            owner=owner,
            cash_register=cash_register,
            payment_methods=payment_methods,
            billing_series=billing_series,
        )

    @staticmethod
    def _fallback(value, fallback):
        return fallback if value is None else value
