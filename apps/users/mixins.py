from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404

from apps.stores.models import Stores
from apps.users.models import CustomUser
from apps.users.helpers import (
    is_owner,
    is_owner_or_manager,
    can_manage_users,
    can_manage_business_settings,
    can_view_reports,
    can_perform_sensitive_action,
    can_access_store,
    can_sell_in_store,
    can_open_cash_register,
    can_close_cash_register,
)


class BusinessUserQuerysetMixin:
    """
    Mixin para vistas de usuarios.
    Evita que un owner/manager de un negocio vea usuarios de otro negocio.
    El superusuario puede ver todos.
    """

    # esto se hace para el rendimiento delas consultas, para que no haga muchas consultas a la base de datos

    def get_queryset(self):
        """Retorna el queryset de usuarios filtrado por negocio del usuario logueado.
        Si el usuario es superusuario, retorna todos los usuarios.

        que hace select_related y prefetch_related para optimizar las consultas a la base de datos.
        select_related: para traer la relación de negocio en la misma consulta.
        prefetch_related: para traer la relación de accesos a tiendas en una sola consulta.
        """
        qs = (
            CustomUser.objects.select_related("business")
            .prefetch_related("store_accesses__store")
            .order_by("email")
        )

        if self.request.user.is_superuser:
            return qs

        return qs.filter(business=self.request.user.business)


# ============================================================================
# PERMISOS GLOBALES - Mixins para validar permisos a nivel de negocio
# ============================================================================
# Estos mixins validan permisos que aplican a todo el negocio sin considerar
# tienda específica. El permiso se valida solo con el usuario.
# ============================================================================


class BasePermissionMixin(LoginRequiredMixin):
    """
    Mixin base para validar permisos globales del negocio.

    Propósito:
        - Validar que el usuario tenga permiso para acceder a vistas relacionadas
          con el negocio completo.
        - Permitir el acceso automático a superusuarios.
        - Mostrar mensaje de permiso denegado personalizable.

    Cómo funciona:
        - El atributo `permission_checker` debe asignarse a una función helper
          que recibe solo el usuario: permission_checker(user) -> bool
        - Levanta PermissionDenied si el usuario no tiene permisos.

    Atributos:
        permission_checker: Función que valida permisos (debe retornar bool)
        permission_denied_message: Mensaje mostrado si se deniega el acceso
    """

    permission_checker = None
    permission_denied_message = "No tienes permiso para acceder a esta página."

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_superuser:
            return super().dispatch(request, *args, **kwargs)

        if self.permission_checker is None:
            raise PermissionDenied(
                "No se ha definido el validador de permisos globales."
            )

        if not self.permission_checker(request.user):
            raise PermissionDenied(self.permission_denied_message)

        return super().dispatch(request, *args, **kwargs)


class OwnerRequiredMixin(BasePermissionMixin):
    """
    Mixin para validar que el usuario sea propietario del negocio.

    Uso: Aplicar en vistas que solo el propietario debe acceder
    Ejemplo: Cambiar configuración principal del negocio, gestionar propietarios.
    """

    permission_checker = staticmethod(is_owner)
    permission_denied_message = "Solo el propietario puede acceder a esta página."


class ManagerOrOwnerRequiredMixin(BasePermissionMixin):
    """
    Mixin para validar que el usuario sea propietario o gerente del negocio.

    Uso: Aplicar en vistas de gestión general del negocio
    Ejemplo: Ver reportes del negocio, aprobar cambios importantes.
    """

    permission_checker = staticmethod(is_owner_or_manager)
    permission_denied_message = "Solo owner o manager pueden acceder a esta página."


class CanManageUsersMixin(BasePermissionMixin):
    """
    Mixin para validar que el usuario pueda gestionar otros usuarios.

    Uso: Aplicar en vistas de creación, edición y eliminación de usuarios
    Ejemplo: CRUD de usuarios, asignación de roles.
    """

    permission_checker = staticmethod(can_manage_users)
    permission_denied_message = "No tienes permiso para gestionar usuarios."


class CanManageBusinessSettingsMixin(BasePermissionMixin):
    """
    Mixin para validar que el usuario pueda modificar la configuración del negocio.

    Uso: Aplicar en vistas de configuración general del negocio
    Ejemplo: Cambiar nombre del negocio, horarios, políticas.
    """

    permission_checker = staticmethod(can_manage_business_settings)
    permission_denied_message = (
        "No tienes permiso para modificar la configuración del negocio."
    )


class CanViewReportsMixin(BasePermissionMixin):
    """
    Mixin para validar que el usuario pueda visualizar reportes del negocio.

    Uso: Aplicar en vistas de reportes y analytics
    Ejemplo: Ventas totales, inventario, ganancias.
    """

    permission_checker = staticmethod(can_view_reports)
    permission_denied_message = "No tienes permiso para ver reportes."


class CanPerformSensitiveActionMixin(BasePermissionMixin):
    """
    Mixin para validar que el usuario pueda realizar acciones sensibles del negocio.

    Uso: Aplicar en vistas de operaciones críticas o irreversibles
    Ejemplo: Eliminar datos, rescindir contratos, cambios radicales.
    Nota: Generalmente requiere PIN adicional para mayor seguridad.
    """

    permission_checker = staticmethod(can_perform_sensitive_action)
    permission_denied_message = "No tienes permiso para realizar esta acción sensible."


# ============================================================================
# PERMISOS POR TIENDA - Mixins para validar permisos específicos de una tienda
# ============================================================================
# Estos mixins validan permisos que aplican a operaciones en una tienda específica.
# El permiso se valida con el usuario Y la tienda obtenida de los parámetros URL.
# ============================================================================


class BaseStorePermissionMixin(LoginRequiredMixin):
    """
    Mixin base para validar permisos relacionados con operaciones en una tienda.

    Propósito:
        - Validar que el usuario tenga permiso para operar en una tienda específica.
        - Recuperar automáticamente la tienda desde los parámetros URL.
        - Permitir acceso automático a superusuarios.
        - Mostrar mensaje de permiso denegado personalizable.

    Cómo funciona:
        - El atributo `permission_checker` debe asignarse a una función helper
          que recibe usuario y tienda: permission_checker(user, store) -> bool
        - Por defecto espera que la URL tenga el parámetro: <int:store_id>
        - El atributo `store_kwarg` permite personalizar el nombre del parámetro URL.
        - Levanta PermissionDenied si el usuario no tiene permisos.

    Atributos:
        permission_checker: Función que valida permisos (debe retornar bool)
        store_kwarg: Nombre del parámetro URL con el ID de tienda (default: 'store_id')
        permission_denied_message: Mensaje mostrado si se deniega el acceso

    Métodos:
        get_store(): Recupera la tienda desde la URL
        dispatch(): Valida permisos antes de ejecutar la vista
    """

    permission_checker = None
    store_kwarg = "store_id"
    permission_denied_message = "No tienes permiso para operar en esta tienda."

    def get_store(self):
        """
        Recupera la tienda desde los parámetros URL.

        Retorna: Objeto Stores si existe
        Levanta: PermissionDenied si no se indica la tienda en la URL
        """
        store_id = self.kwargs.get(self.store_kwarg)

        if not store_id:
            raise PermissionDenied("No se ha indicado la tienda.")

        return get_object_or_404(Stores, pk=store_id)

    def dispatch(self, request, *args, **kwargs):
        """
        Valida los permisos antes de ejecutar la vista.

        Proceso:
            1. Obtiene la tienda desde la URL
            2. Permite acceso automático a superusuarios
            3. Valida que permission_checker esté definido
            4. Valida que el usuario tenga permiso para esta tienda
            5. Si todo es válido, ejecuta la vista
        """
        self.store = self.get_store()

        if request.user.is_superuser:
            return super().dispatch(request, *args, **kwargs)

        if self.permission_checker is None:
            raise PermissionDenied(
                "No se ha definido el validador de permisos de tienda."
            )

        if not self.permission_checker(request.user, self.store):
            raise PermissionDenied(self.permission_denied_message)

        return super().dispatch(request, *args, **kwargs)


class StoreAccessRequiredMixin(BaseStorePermissionMixin):
    """
    Mixin para validar que el usuario tenga acceso a la tienda.

    Uso: Aplicar en vistas básicas de acceso a una tienda
    Ejemplo: Ver dashboard de tienda, listar información general.
    """

    permission_checker = staticmethod(can_access_store)
    permission_denied_message = "No tienes acceso a esta tienda."


class CanSellInStoreMixin(BaseStorePermissionMixin):
    """
    Mixin para validar que el usuario pueda realizar ventas en la tienda.

    Uso: Aplicar en vistas de punto de venta (POS) y creación de transacciones
    Ejemplo: Crear venta, procesar pago, emitir factura.
    """

    permission_checker = staticmethod(can_sell_in_store)
    permission_denied_message = "No tienes permiso para vender en esta tienda."


class CanOpenCashRegisterMixin(BaseStorePermissionMixin):
    """
    Mixin para validar que el usuario pueda abrir la caja registradora.

    Uso: Aplicar en vistas de apertura de caja (cash register opening)
    Ejemplo: Registrar monto inicial de caja para el turno.
    Nota: Generalmente requiere PIN de seguridad adicional.
    """

    permission_checker = staticmethod(can_open_cash_register)
    permission_denied_message = "No tienes permiso para abrir caja en esta tienda."


class CanCloseCashRegisterMixin(BaseStorePermissionMixin):
    """
    Mixin para validar que el usuario pueda cerrar la caja registradora.

    Uso: Aplicar en vistas de cierre de caja (cash register closing)
    Ejemplo: Generar reporte de cierre de caja, contar dinero, registrar diferencias.
    Nota: Generalmente requiere PIN de seguridad adicional y validación de montos.
    """

    permission_checker = staticmethod(can_close_cash_register)
    permission_denied_message = "No tienes permiso para cerrar caja en esta tienda."
