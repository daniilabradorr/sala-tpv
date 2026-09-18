"""Server-side catalogue used by every app-shell navigation surface."""

from django.urls import reverse

from apps.users.helpers import (
    can_manage_business_settings,
    can_manage_users,
    can_sell_in_store,
    is_owner_or_manager,
)


GROUPS = (
    ("operation", "Operación"),
    ("management", "Gestión"),
    ("administration", "Administración"),
)


def _item(item_id, label, icon, url, group, keywords, active=False):
    return {
        "id": item_id,
        "label": label,
        "icon": icon,
        "url": url,
        "group": group,
        "keywords": keywords,
        "active": active,
    }


def build_shell_navigation(request, *, active_store):
    """Build authorized navigation once for sidebar and command palette."""

    user = request.user
    app_name = getattr(getattr(request, "resolver_match", None), "app_name", "")
    business_id = getattr(user, "business_id", None)
    items = [
        _item(
            "home",
            "Inicio",
            "home",
            reverse("core:home"),
            "operation",
            "inicio dashboard resumen",
            app_name == "core",
        )
    ]
    if not business_id:
        if user.is_superuser:
            items.append(
                _item(
                    "admin",
                    "Administración Django",
                    "settings",
                    reverse("admin:index"),
                    "administration",
                    "admin administración",
                    app_name == "admin",
                )
            )
        return _group(items), []

    if active_store is not None:
        store_kwargs = {"store_id": active_store.pk}
        items.extend(
            (
                _item(
                    "sales",
                    "Ventas",
                    "receipt",
                    reverse("sales:sale_list", kwargs=store_kwargs),
                    "operation",
                    "ventas tpv tickets histórico",
                    app_name == "sales",
                ),
                _item(
                    "cash",
                    "Caja",
                    "cash-register",
                    reverse("cash_register:register_list", kwargs=store_kwargs),
                    "operation",
                    "caja registro sesiones efectivo",
                    app_name == "cash_register",
                ),
            )
        )

    items.extend(
        (
            _item(
                "products",
                "Productos",
                "box",
                reverse("catalog:product_list"),
                "management",
                "productos catálogo categorías impuestos",
                app_name == "catalog",
            ),
            _item(
                "inventory",
                "Inventario",
                "inventory",
                reverse("inventory:dashboard"),
                "management",
                "inventario stock existencias",
                app_name == "inventory",
            ),
            _item(
                "customers",
                "Clientes",
                "users",
                reverse("customers:customer_list"),
                "management",
                "clientes cuentas",
                app_name == "customers",
            ),
        )
    )
    if is_owner_or_manager(user):
        items.append(
            _item(
                "purchases",
                "Compras",
                "truck",
                reverse("purchases:purchase_list"),
                "management",
                "compras proveedores pedidos",
                app_name == "purchases",
            )
        )
    if active_store is not None:
        items.append(
            _item(
                "billing",
                "Facturación",
                "file-text",
                reverse("billing:document_list", kwargs={"store_id": active_store.pk}),
                "management",
                "facturación facturas documentos fiscal",
                app_name == "billing",
            )
        )
    if is_owner_or_manager(user):
        items.append(
            _item(
                "stores",
                "Tiendas",
                "store",
                reverse("stores:store_list"),
                "administration",
                "tiendas establecimientos",
                app_name == "stores",
            )
        )
    if can_manage_users(user):
        profile_names = {"profile", "profile_update", "password_change", "pin_change"}
        url_name = getattr(getattr(request, "resolver_match", None), "url_name", "")
        items.append(
            _item(
                "users",
                "Usuarios",
                "users",
                reverse("users:user_list"),
                "administration",
                "usuarios equipo empleados",
                app_name == "users" and url_name not in profile_names,
            )
        )
    if can_manage_business_settings(user):
        items.append(
            _item(
                "settings",
                "Configuración",
                "settings",
                reverse("business_config:profile"),
                "administration",
                "configuración negocio ajustes",
                app_name == "business_config",
            )
        )

    actions = []
    if active_store is not None and can_sell_in_store(user, active_store):
        actions.append(
            _item(
                "new-sale",
                "Nueva venta",
                "plus",
                reverse("sales:sale_open", kwargs={"store_id": active_store.pk}),
                "quick",
                "venta tpv ticket abrir",
            )
        )
    actions.append(
        _item(
            "new-customer",
            "Nuevo cliente",
            "user-plus",
            reverse("customers:customer_create"),
            "quick",
            "cliente crear alta",
        )
    )
    if is_owner_or_manager(user):
        actions.extend(
            (
                _item(
                    "new-purchase",
                    "Nueva compra",
                    "truck",
                    reverse("purchases:purchase_create"),
                    "quick",
                    "compra pedido crear",
                ),
                _item(
                    "new-product",
                    "Nuevo producto",
                    "box",
                    reverse("catalog:product_create"),
                    "quick",
                    "producto crear alta",
                ),
            )
        )
    return _group(items), actions


def _group(items):
    return [
        {"id": group_id, "label": label, "items": group_items}
        for group_id, label in GROUPS
        if (group_items := [item for item in items if item["group"] == group_id])
    ]
