from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction

from apps.cash_register.helpers import business_exists
from django.utils import timezone

from apps.business_config.models import POSSettings
from apps.cash_register.models import CashCount, CashMovement, CashRegister, CashSession
from apps.cash_register.repositories import CashRegisterRepository
from apps.core.models import Business
from apps.stores.models import Store
from apps.users.helpers import (
    belongs_to_business,
    can_access_store,
    can_close_cash_register,
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
            repository if repository is not None else CashRegisterRepository()
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
                {"opening_amount": "El importe inicial no es válido."}
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
            amount = Decimal(str(value)).quantize(
                MONEY_STEP,
                rounding=ROUND_HALF_UP,
            )

        except (
            InvalidOperation,
            TypeError,
            ValueError,
        ) as exc:
            raise ValidationError(
                {"opening_amount": "El importe inicial no es válido."}
            ) from exc

        if amount < ZERO:
            raise ValidationError(
                {"opening_amount": ("El importe inicial no puede ser negativo.")}
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
            raise ValidationError({"business": "El negocio no existe o está inactivo."})

        # ==========================================================
        # 2. Usuario
        # ==========================================================

        if not is_authenticated_user(user):
            raise ValidationError(
                {"user": "El usuario no está autenticado o está inactivo."}
            )

        if not belongs_to_business(
            user,
            business,
        ):
            raise ValidationError({"user": "El usuario no pertenece al negocio."})

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
                    {"store": ("La tienda no existe o no pertenece al negocio.")}
                ) from exc

            if not store.is_active:
                raise ValidationError({"store": "La tienda está inactiva."})

            # ------------------------------------------------------
            # CashRegister
            #
            # AQUÍ ADQUIRIMOS EL LOCK.
            # ------------------------------------------------------

            try:
                cash_register = self.repository.get_cash_register_for_update(
                    business=business,
                    store=store,
                    cash_register_id=cash_register_id,
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
                raise ValidationError({"cash_register": "La caja está inactiva."})

            # ------------------------------------------------------
            # Permiso
            # ------------------------------------------------------

            if not can_open_cash_register(
                user,
                store,
            ):
                raise ValidationError(
                    {"user": "El usuario no tiene permiso para abrir esta caja."}
                )

            # ------------------------------------------------------
            # Sesión OPEN existente
            # ------------------------------------------------------

            current_session = self.repository.get_open_session(
                cash_register=cash_register,
            )

            if current_session is not None:
                raise ValidationError(
                    {"cash_register": "La caja ya tiene una sesión abierta."}
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
                    session = self.repository.create_cash_session(
                        business=business,
                        store=store,
                        cash_register=cash_register,
                        opened_by=user,
                        opening_amount=opening_amount,
                    )

            except IntegrityError as exc:
                raise ValidationError(
                    {"cash_register": "La caja ya tiene una sesión abierta."}
                ) from exc

            return session

    @staticmethod
    def _positive_amount(value, field="amount") -> Decimal:
        if isinstance(value, (bool, float)):
            raise ValidationError(
                {field: "El importe debe ser Decimal o texto decimal."}
            )
        try:
            amount = Decimal(str(value)).quantize(MONEY_STEP, rounding=ROUND_HALF_UP)
        except (InvalidOperation, TypeError, ValueError) as exc:
            raise ValidationError({field: "El importe no es válido."}) from exc
        if amount <= ZERO:
            raise ValidationError({field: "El importe debe ser mayor que cero."})
        return amount

    @staticmethod
    def _nonnegative_amount(value, field) -> Decimal:
        if isinstance(value, (bool, float)):
            raise ValidationError(
                {field: "El importe debe ser Decimal o texto decimal."}
            )
        try:
            amount = Decimal(str(value)).quantize(MONEY_STEP, rounding=ROUND_HALF_UP)
        except (InvalidOperation, TypeError, ValueError) as exc:
            raise ValidationError({field: "El importe no es válido."}) from exc
        if amount < ZERO:
            raise ValidationError({field: "El importe no puede ser negativo."})
        return amount

    def _manual_movement(
        self,
        *,
        business,
        store_id,
        cash_register_id,
        cash_session_id,
        user,
        amount,
        movement_type,
        reason="",
        adjustment_direction=None,
    ):
        if not business_exists(business):
            raise ValidationError({"business": "El negocio no existe o está inactivo."})
        if not is_authenticated_user(user) or not belongs_to_business(user, business):
            raise ValidationError({"user": "El usuario no es válido para el negocio."})
        amount = self._positive_amount(amount)
        with transaction.atomic():
            try:
                store = self.repository.get_store(business=business, store_id=store_id)
            except Store.DoesNotExist as exc:
                raise ValidationError(
                    {"store": "La tienda no pertenece al negocio."}
                ) from exc
            if not store.is_active or not can_access_store(user, store):
                raise ValidationError(
                    {"store": "El usuario no puede operar en la tienda."}
                )
            try:
                session = self.repository.get_cash_session_for_update(
                    business=business, store=store, cash_session_id=cash_session_id
                )
            except CashSession.DoesNotExist as exc:
                raise ValidationError(
                    {"cash_session": "La sesión no es válida."}
                ) from exc
            if session.cash_register_id != cash_register_id:
                raise ValidationError(
                    {"cash_register": "La sesión no pertenece a la caja."}
                )
            if not session.is_open:
                raise ValidationError({"cash_session": "La sesión está cerrada."})
            direction = Decimal("1.00")
            if movement_type == CashMovement.MovementType.CASH_OUT or (
                movement_type == CashMovement.MovementType.ADJUSTMENT
                and adjustment_direction == CashMovement.AdjustmentDirection.OUT
            ):
                direction = Decimal("-1.00")
            balance = session.expected_cash_amount + direction * amount
            if balance < ZERO and direction < ZERO and not (reason or "").strip():
                raise ValidationError(
                    {"reason": "El motivo es obligatorio si el saldo queda negativo."}
                )
            movement = self.repository.create_cash_movement(
                business=business,
                store=store,
                cash_session=session,
                movement_type=movement_type,
                adjustment_direction=adjustment_direction,
                amount=amount,
                balance_after=balance,
                created_by=user,
                reason=(reason or "").strip(),
            )
            session.expected_cash_amount = balance
            session.save(update_fields=["expected_cash_amount", "updated_at"])
            return movement

    def register_cash_in(self, **kwargs):
        return self._manual_movement(
            movement_type=CashMovement.MovementType.CASH_IN, **kwargs
        )

    def register_cash_out(self, **kwargs):
        return self._manual_movement(
            movement_type=CashMovement.MovementType.CASH_OUT, **kwargs
        )

    def register_adjustment(self, *, adjustment_direction, **kwargs):
        if adjustment_direction not in CashMovement.AdjustmentDirection.values:
            raise ValidationError(
                {"adjustment_direction": "La dirección no es válida."}
            )
        return self._manual_movement(
            movement_type=CashMovement.MovementType.ADJUSTMENT,
            adjustment_direction=adjustment_direction,
            **kwargs,
        )

    def review_cash_count(
        self,
        *,
        business,
        store_id,
        cash_register_id,
        cash_session_id,
        user,
        counted_amount,
        notes="",
    ):
        counted = self._nonnegative_amount(counted_amount, "counted_amount")
        with transaction.atomic():
            store = self.repository.get_store(business=business, store_id=store_id)
            if not can_access_store(user, store):
                raise ValidationError(
                    {"user": "El usuario no puede operar en la tienda."}
                )
            session = self.repository.get_cash_session_for_update(
                business=business, store=store, cash_session_id=cash_session_id
            )
            if session.cash_register_id != cash_register_id or not session.is_open:
                raise ValidationError(
                    {"cash_session": "La sesión no está abierta en la caja."}
                )
            return self.repository.create_cash_count(
                count_type=CashCount.CountType.REVIEW,
                business=business,
                store=store,
                cash_session=session,
                counted_amount=counted,
                expected_amount=session.expected_cash_amount,
                difference_amount=counted - session.expected_cash_amount,
                counted_by=user,
                notes=notes,
            )

    def close_cash_session(
        self,
        *,
        business,
        store_id,
        cash_register_id,
        cash_session_id,
        user,
        counted_cash_amount,
        pin=None,
        notes="",
    ):
        counted = self._nonnegative_amount(counted_cash_amount, "counted_cash_amount")
        with transaction.atomic():
            store = self.repository.get_store(business=business, store_id=store_id)
            if not can_close_cash_register(user, store):
                raise ValidationError(
                    {"user": "El usuario no tiene permiso para cerrar caja."}
                )
            settings = POSSettings.objects.get(business=business)
            if settings.require_pin_for_sensitive_actions and (
                not pin or not user.check_pin(pin)
            ):
                raise ValidationError({"pin": "El PIN indicado no es válido."})
            session = self.repository.get_cash_session_for_update(
                business=business, store=store, cash_session_id=cash_session_id
            )
            if session.cash_register_id != cash_register_id or not session.is_open:
                raise ValidationError(
                    {"cash_session": "La sesión ya está cerrada o no es válida."}
                )
            difference = counted - session.expected_cash_amount
            count = self.repository.create_cash_count(
                count_type=CashCount.CountType.CLOSING,
                business=business,
                store=store,
                cash_session=session,
                counted_amount=counted,
                expected_amount=session.expected_cash_amount,
                difference_amount=difference,
                counted_by=user,
                notes=notes,
            )
            session.status = CashSession.Status.CLOSED
            session.counted_cash_amount = counted
            session.difference_amount = difference
            session.closed_by = user
            session.closed_at = timezone.now()
            session.save(
                update_fields=[
                    "status",
                    "counted_cash_amount",
                    "difference_amount",
                    "closed_by",
                    "closed_at",
                    "updated_at",
                ]
            )
            return session, count


def register_payment_cash_movement(*, payment, locked_session=None):
    """Create the physical cash effect; caller owns the surrounding transaction."""
    if not payment.is_completed or not payment.method.affects_cash_register:
        return None
    existing = CashMovement.objects.filter(payment=payment).first()
    if existing:
        return existing
    session = locked_session or CashSession.objects.select_for_update().get(
        pk=payment.cash_session_id, business=payment.business, store=payment.store
    )
    if not session.is_open:
        raise ValidationError({"cash_session": "La sesión está cerrada."})
    is_refund = payment.is_refund
    balance = session.expected_cash_amount + (
        -payment.amount if is_refund else payment.amount
    )
    movement = CashMovement.objects.create(
        business=payment.business,
        store=payment.store,
        cash_session=session,
        movement_type=(
            CashMovement.MovementType.REFUND_CASH
            if is_refund
            else CashMovement.MovementType.SALE_CASH
        ),
        amount=payment.amount,
        balance_after=balance,
        sale=payment.sale,
        payment=payment,
        created_by=payment.processed_by,
    )
    session.expected_cash_amount = balance
    session.save(update_fields=["expected_cash_amount", "updated_at"])
    return movement
