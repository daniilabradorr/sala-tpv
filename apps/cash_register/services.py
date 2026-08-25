from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction

from apps.cash_register.helpers import business_exists
from apps.cash_register.models import CashRegister, CashSession
from apps.cash_register.repositories import CashRegisterRepository
from apps.core.models import Business
from apps.stores.models import Store
from apps.users.helpers import (
    belongs_to_business,
    can_open_cash_register,
    is_authenticated_user,
)
from apps.users.models import CustomUser


ZERO = Decimal("0.00")
MONEY_STEP = Decimal("0.01")


class CashRegisterService:
    """
    Casos de uso del módulo Cash Register.

    El Service:
    - aplica reglas dinámicas;
    - comprueba permisos;
    - coordina Repository;
    - controla transacciones;
    - controla locking;
    - traduce errores de persistencia a errores de dominio.
    """

    def __init__(
        self,
        repository: CashRegisterRepository | None = None,
    ):
        self.repository = (
            repository
            if repository is not None
            else CashRegisterRepository()
        )

    @staticmethod
    def _opening_amount(value) -> Decimal:
        """
        Normaliza el importe inicial de apertura.

        Opening amount:
            puede ser 0
            nunca puede ser negativo

        Todo cálculo monetario interno termina siendo Decimal.
        """

        # bool hereda de int en Python.
        # No queremos aceptar True como 1 €.
        if isinstance(value, bool):
            raise ValidationError(
                {
                    "opening_amount":
                        "El importe inicial no es válido."
                }
            )

        # El contrato monetario interno usa Decimal.
        # Evitamos trabajar con floats para dinero.
        if isinstance(value, float):
            raise ValidationError(
                {
                    "opening_amount": (
                        "El importe inicial debe enviarse "
                        "como Decimal o como texto decimal."
                    )
                }
            )

        try:
            amount = Decimal(
                str(value)
            ).quantize(
                MONEY_STEP,
                rounding=ROUND_HALF_UP,
            )

        except (
            InvalidOperation,
            TypeError,
            ValueError,
        ) as exc:
            raise ValidationError(
                {
                    "opening_amount":
                        "El importe inicial no es válido."
                }
            ) from exc

        if amount < ZERO:
            raise ValidationError(
                {
                    "opening_amount": (
                        "El importe inicial no puede ser negativo."
                    )
                }
            )

        return amount

    def open_cash_session(
        self,
        *,
        business: Business,
        store_id: int,
        cash_register_id: int,
        user: CustomUser,
        opening_amount,
    ) -> CashSession:
        """
        Abre una nueva sesión de caja.

        Garantiza:

        - Business válido y activo.
        - Usuario autenticado y activo.
        - Usuario perteneciente al Business.
        - Store perteneciente al Business.
        - Store activa.
        - CashRegister perteneciente a Business + Store.
        - CashRegister activa.
        - Permiso para abrir caja.
        - opening_amount >= 0.
        - Una única sesión OPEN por CashRegister.
        - Protección frente a concurrencia.
        """

        # ==========================================================
        # 1. Business
        # ==========================================================

        if not business_exists(business):
            raise ValidationError(
                {
                    "business":
                        "El negocio no existe o está inactivo."
                }
            )

        # ==========================================================
        # 2. Usuario
        # ==========================================================

        if not is_authenticated_user(user):
            raise ValidationError(
                {
                    "user":
                        "El usuario no está autenticado o está inactivo."
                }
            )

        if not belongs_to_business(
            user,
            business,
        ):
            raise ValidationError(
                {
                    "user":
                        "El usuario no pertenece al negocio."
                }
            )

        # ==========================================================
        # 3. Opening amount
        # ==========================================================

        opening_amount = self._opening_amount(
            opening_amount,
        )

        # ==========================================================
        # 4. Operación crítica
        # ==========================================================

        with transaction.atomic():

            # ------------------------------------------------------
            # Store
            # ------------------------------------------------------

            try:
                store = self.repository.get_store(
                    business=business,
                    store_id=store_id,
                )

            except Store.DoesNotExist as exc:
                raise ValidationError(
                    {
                        "store": (
                            "La tienda no existe o no pertenece "
                            "al negocio."
                        )
                    }
                ) from exc

            if not store.is_active:
                raise ValidationError(
                    {
                        "store":
                            "La tienda está inactiva."
                    }
                )

            # ------------------------------------------------------
            # CashRegister
            #
            # AQUÍ ADQUIRIMOS EL LOCK.
            # ------------------------------------------------------

            try:
                cash_register = (
                    self.repository
                    .get_cash_register_for_update(
                        business=business,
                        store=store,
                        cash_register_id=cash_register_id,
                    )
                )

            except CashRegister.DoesNotExist as exc:
                raise ValidationError(
                    {
                        "cash_register": (
                            "La caja no existe o no pertenece "
                            "al negocio y tienda indicados."
                        )
                    }
                ) from exc

            if not cash_register.is_active:
                raise ValidationError(
                    {
                        "cash_register":
                            "La caja está inactiva."
                    }
                )

            # ------------------------------------------------------
            # Permiso
            # ------------------------------------------------------

            if not can_open_cash_register(
                user,
                store,
            ):
                raise ValidationError(
                    {
                        "user":
                            "El usuario no tiene permiso para abrir esta caja."
                    }
                )

            # ------------------------------------------------------
            # Sesión OPEN existente
            # ------------------------------------------------------

            current_session = (
                self.repository.get_open_session(
                    cash_register=cash_register,
                )
            )

            if current_session is not None:
                raise ValidationError(
                    {
                        "cash_register":
                            "La caja ya tiene una sesión abierta."
                    }
                )

            # ------------------------------------------------------
            # Crear CashSession
            # ------------------------------------------------------
            #
            # Abrimos un savepoint interno porque, aunque tenemos
            # select_for_update(), la UniqueConstraint de la BD
            # sigue siendo nuestra última barrera de seguridad.
            # ------------------------------------------------------

            try:
                with transaction.atomic():
                    session = (
                        self.repository.create_cash_session(
                            business=business,
                            store=store,
                            cash_register=cash_register,
                            opened_by=user,
                            opening_amount=opening_amount,
                        )
                    )

            except IntegrityError as exc:
                raise ValidationError(
                    {
                        "cash_register":
                            "La caja ya tiene una sesión abierta."
                    }
                ) from exc

            return session