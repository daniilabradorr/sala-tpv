from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction

from apps.stores.models import Store
from apps.users.helpers import can_manage_user, is_manager
from apps.users.models import CustomUser, RoleChoices, UserStoreAccess


def _assert_actor(actor, target=None, role=None):
    if not actor.business_id:
        raise PermissionDenied("Se necesita un negocio para administrar usuarios.")
    if target is not None and (
        target.business_id != actor.business_id or not can_manage_user(actor, target)
    ):
        raise PermissionDenied("No tienes permiso para gestionar este usuario.")
    if is_manager(actor) and role == RoleChoices.OWNER:
        raise PermissionDenied("Un manager no puede gestionar propietarios.")


@transaction.atomic
def create_user_with_store_accesses(*, actor, user_data, accesses):
    _assert_actor(actor, role=user_data["role"])
    password = user_data.pop("password")
    user_data.pop("password_confirm", None)
    user = CustomUser(business=actor.business, **user_data)
    user.set_password(password)
    user.save()
    if user.role != RoleChoices.OWNER:
        _update_accesses(user, accesses)
    return user


@transaction.atomic
def update_user(*, actor, target_user, data):
    target = CustomUser.objects.select_for_update().get(pk=target_user.pk)
    _assert_actor(actor, target, data.get("role"))
    for field in ("first_name", "last_name", "phone", "role"):
        if field in data:
            setattr(target, field, data[field])
    target.save(
        update_fields=["first_name", "last_name", "phone", "role", "updated_at"]
    )
    return target


def _update_accesses(target, accesses):
    stores = {s.pk: s for s in Store.objects.filter(business=target.business)}
    if set(accesses) - set(stores):
        raise ValidationError("La matriz contiene una tienda ajena al negocio.")
    existing = {
        a.store_id: a
        for a in UserStoreAccess.objects.select_for_update().filter(
            user=target, business=target.business
        )
    }
    for store_id, values in accesses.items():
        access = existing.get(store_id) or UserStoreAccess(
            business=target.business, user=target, store=stores[store_id]
        )
        access.is_active = values["is_active"]
        access.can_sell = values["can_sell"]
        access.can_open_cash = values["can_open_cash"]
        access.can_close_cash = values["can_close_cash"]
        access.save()


@transaction.atomic
def update_user_store_accesses(*, actor, target_user, accesses):
    target = CustomUser.objects.select_for_update().get(pk=target_user.pk)
    _assert_actor(actor, target)
    if target.role != RoleChoices.OWNER:
        _update_accesses(target, accesses)
    return target


@transaction.atomic
def deactivate_user(*, actor, target_user):
    target = CustomUser.objects.select_for_update().get(pk=target_user.pk)
    _assert_actor(actor, target)
    if actor.pk == target.pk:
        raise ValidationError("No puedes desactivar tu propio usuario.")
    target.is_active = False
    target.save(update_fields=["is_active", "updated_at"])
    return target


@transaction.atomic
def activate_user(*, actor, target_user):
    target = CustomUser.objects.select_for_update().get(pk=target_user.pk)
    _assert_actor(actor, target)
    target.is_active = True
    target.save(update_fields=["is_active", "updated_at"])
    return target
