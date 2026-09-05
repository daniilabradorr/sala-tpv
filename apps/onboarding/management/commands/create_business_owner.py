import getpass

from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError

from apps.onboarding.services import OnboardingError, OnboardingService


class Command(BaseCommand):
    help = "Crea una empresa y su propietario mediante el servicio de onboarding."
    service_arguments = (
        "legal_name",
        "tax_identifier",
        "trade_name",
        "phone",
        "email",
        "address_line_1",
        "address_line_2",
        "postal_code",
        "city",
        "province",
        "country_code",
        "store_name",
        "store_address_line_1",
        "store_address_line_2",
        "store_postal_code",
        "store_city",
        "store_province",
        "store_phone",
        "store_email",
        "owner_first_name",
        "owner_last_name",
        "owner_email",
        "owner_phone",
    )

    def add_arguments(self, parser):
        parser.add_argument("--legal-name", required=True)
        parser.add_argument("--tax-identifier", required=True)
        parser.add_argument("--trade-name", default="")
        parser.add_argument("--phone", required=True)
        parser.add_argument("--email", required=True)
        parser.add_argument("--address-line-1", required=True)
        parser.add_argument("--address-line-2", default="")
        parser.add_argument("--postal-code", required=True)
        parser.add_argument("--city", required=True)
        parser.add_argument("--province", required=True)
        parser.add_argument("--country-code", default="ES")

        parser.add_argument("--store-name", required=True)
        parser.add_argument("--store-address-line-1")
        parser.add_argument("--store-address-line-2")
        parser.add_argument("--store-postal-code")
        parser.add_argument("--store-city")
        parser.add_argument("--store-province")
        parser.add_argument("--store-phone")
        parser.add_argument("--store-email")

        parser.add_argument("--owner-first-name", required=True)
        parser.add_argument("--owner-last-name", required=True)
        parser.add_argument("--owner-email", required=True)
        parser.add_argument("--owner-phone", required=True)
        parser.add_argument("--owner-password")
        parser.add_argument("--owner-pin")

    def handle(self, *args, **options):
        owner_password = options.pop("owner_password")
        owner_pin = options.pop("owner_pin")

        if owner_password is None:
            owner_password = getpass.getpass("Contraseña del propietario: ")
            confirmation = getpass.getpass("Confirme la contraseña: ")
            if owner_password != confirmation:
                raise CommandError("Las contraseñas no coinciden.")

        if owner_pin is None:
            owner_pin = getpass.getpass("PIN del propietario: ")

        try:
            result = OnboardingService.create_business(
                **{name: options[name] for name in self.service_arguments},
                owner_password=owner_password,
                owner_pin=owner_pin,
            )
        except (OnboardingError, ValidationError) as error:
            raise CommandError(self._error_message(error)) from error

        self._write_success(result)

    @staticmethod
    def _error_message(error):
        if isinstance(error, ValidationError):
            return "; ".join(error.messages)
        return str(error)

    def _write_success(self, result):
        series = "\n".join(
            f"  {billing_series.prefix}" for billing_series in result.billing_series
        )
        self.stdout.write(
            self.style.SUCCESS(
                "\n".join(
                    (
                        "Empresa creada correctamente.",
                        "",
                        "Business:",
                        f"  ID: {result.business.pk}",
                        f"  Nombre: {result.business.name}",
                        f"  Slug: {result.business.slug}",
                        "",
                        "Store:",
                        f"  ID: {result.store.pk}",
                        f"  Nombre: {result.store.name}",
                        f"  Código: {result.store.code}",
                        "",
                        "Owner:",
                        f"  {result.owner.email}",
                        "",
                        "Caja:",
                        f"  {result.cash_register.name}",
                        f"  {result.cash_register.code}",
                        "",
                        "Métodos de pago:",
                        f"  {len(result.payment_methods)}",
                        "",
                        "Series:",
                        series,
                    )
                )
            )
        )
