from decimal import Decimal

from apps.cash_register.models import CashRegister, CashSession
from apps.core.models import Business
from apps.stores.models import Store
from apps.users.models import CustomUser


class CashRegisterRepository:
    """
    Frontera de persistencia del módulo Cash Register.

    IMPORTANTE:
    - No contiene reglas de negocio.
    - No decide permisos.
    - No abre/cierra transacciones por su cuenta.
    - El Service controla transaction.atomic().
    """

    def get_store(
        self,
        *,
        business: Business,
        store_id: int,
    ) -> Store:
        """
        Obtiene una Store que pertenezca al Business indicado.

        No filtramos por is_active aquí porque queremos que sea
        el Service quien decida qué error de negocio devolver.
        """
        return Store.objects.get(
            pk=store_id,
            business=business,
        )

    def get_cash_register_for_update(
        self,
        *,
        business: Business,
        store: Store,
        cash_register_id: int,
    ) -> CashRegister:
        """
        Obtiene y bloquea la CashRegister hasta finalizar
        la transacción actual.

        Bloqueamos CashRegister y no CashSession porque al abrir
        la primera sesión todavía no existe ninguna CashSession
        que podamos bloquear.
        """
        return (
            CashRegister.objects
            .select_for_update()
            .get(
                pk=cash_register_id,
                business=business,
                store=store,
            )
        )

    def get_open_session(
        self,
        *,
        cash_register: CashRegister,
    ) -> CashSession | None:
        """
        Devuelve la sesión OPEN actual de la caja, si existe.
        """
        return (
            CashSession.objects
            .filter(
                cash_register=cash_register,
                status=CashSession.Status.OPEN,
            )
            .first()
        )

    def create_cash_session(
        self,
        *,
        business: Business,
        store: Store,
        cash_register: CashRegister,
        opened_by: CustomUser,
        opening_amount: Decimal,
    ) -> CashSession:
        """
        Persiste una nueva sesión OPEN.

        El Repository no decide si se puede abrir:
        esa decisión ya debe haberla tomado el Service.
        """
        return CashSession.objects.create(
            business=business,
            store=store,
            cash_register=cash_register,
            opened_by=opened_by,
            status=CashSession.Status.OPEN,
            opening_amount=opening_amount,
            expected_cash_amount=opening_amount,
            counted_cash_amount=None,
            difference_amount=Decimal("0.00"),
        )