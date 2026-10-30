"""Temporary EUR-only write policy; never converts or repairs historical data."""

from django.core.exceptions import ValidationError


CURRENCY_BLOCK_MESSAGE = (
    "Netxodo solo admite EUR para nuevas operaciones monetarias. "
    "Este negocio tiene una moneda no soportada; la operación está bloqueada. "
    "No cambies la moneda para recuperar ventas o documentos pendientes: "
    "requieren una revisión autorizada sin convertir ni alterar el histórico."
)
HISTORICAL_CURRENCY_WARNING = (
    CURRENCY_BLOCK_MESSAGE + " Las consultas conservan los importes y símbolos "
    "originales de la aplicación. Los documentos no guardan una moneda histórica "
    "verificable; el símbolo € no acredita su moneda ni implica conversión."
)


def business_currency(business_id):
    from apps.business_config.models import BusinessProfile

    # Unconfigured legacy Businesses have always used the schema default EUR.
    # Do not materialize a profile or use a possibly stale related-object cache.
    return next(
        iter(
            BusinessProfile.objects.filter(business_id=business_id).values_list(
                "currency_code", flat=True
            )
        ),
        "EUR",
    )


def ensure_eur_for_business(business_id):
    if business_id is not None and business_currency(business_id) != "EUR":
        # Non-field error: all existing command forms can display it, including
        # forms without a currency input. Authorization stays with the caller.
        raise ValidationError(CURRENCY_BLOCK_MESSAGE, code="unsupported_currency")


def validate_profile_currency(profile):
    from apps.business_config.models import BusinessProfile

    previous = (
        BusinessProfile.objects.filter(pk=profile.pk)
        .values_list("currency_code", "business_id")
        .first()
        if profile.pk
        else None
    )
    if previous is not None and previous[1] != profile.business_id:
        raise ValidationError(
            {"business": "No se puede trasladar un perfil monetario a otro negocio."}
        )
    previous_currency = previous[0] if previous else None
    if previous_currency is not None and previous_currency != "EUR":
        if profile.currency_code != previous_currency:
            raise ValidationError(
                {
                    "currency_code": (
                        "La moneda histórica no puede cambiarse sin una revisión "
                        "autorizada. No se convertirán ni reinterpretarán importes."
                    )
                }
            )
    elif profile.currency_code != "EUR":
        raise ValidationError({"currency_code": "Netxodo solo admite EUR."})
