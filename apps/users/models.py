import uuid

from django.db import models
from django.core.exceptions import ValidationError
from django.contrib.auth.base_user import AbstractBaseUser
from django.contrib.auth.models import PermissionsMixin
from django.contrib.auth.hashers import make_password, check_password
from django.utils import timezone

from apps.core.models import Business
from apps.stores.models import Stores
from .managers import CustomUserManager


class RoleChoices(models.TextChoices):
    OWNER = "owner", "Owner"
    MANAGER = "manager", "Manager"
    CASHIER = "cashier", "Cashier"


class CustomUser(AbstractBaseUser, PermissionsMixin):
    business = models.ForeignKey(
        Business,
        on_delete=models.CASCADE,
        related_name="users",
        null=True,
        blank=True,
    )

    stores = models.ManyToManyField(
        Stores,
        through="UserStoreAccess",
        through_fields=("user", "store"),
        related_name="users",
        blank=True,
    )

    pin_hash = models.CharField(
        "PIN para acciones importantes",
        max_length=128,
        blank=True,
    )

    email = models.EmailField("Correo electrónico", unique=True)
    first_name = models.CharField("Nombre", max_length=150, blank=True)
    last_name = models.CharField("Apellidos", max_length=150, blank=True)
    role = models.CharField("Rol", max_length=20, choices=RoleChoices.choices)
    phone = models.CharField("Teléfono", max_length=20, blank=True)

    employee_code = models.UUIDField(
        "Código interno",
        default=uuid.uuid4,
        editable=False,
        unique=True,
    )

    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)

    date_joined = models.DateTimeField(default=timezone.now)
    created_at = models.DateTimeField(auto_now_add=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = ["first_name", "last_name", "role", "phone"]

    objects = CustomUserManager()

    class Meta:
        verbose_name = "usuario"
        verbose_name_plural = "usuarios"
        ordering = ("email",)
        indexes = [
            models.Index(fields=["business", "role"], name="users_biz_role_idx"),
            models.Index(fields=["is_active", "email"], name="users_active_email_idx"),
        ]

    def __str__(self):
        full_name = f"{self.first_name} {self.last_name}".strip()
        return full_name or self.email

    def clean(self):
        super().clean()

        errors = {}

        if self.email:
            self.email = type(self).objects.normalize_email(self.email)

        if self.phone and not self.phone.isdigit():
            errors["phone"] = "El número de teléfono debe contener solo dígitos."

        if not self.is_superuser and not self.business_id:
            errors["business"] = "Los usuarios normales deben pertenecer a un negocio."

        if errors:
            raise ValidationError(errors)

    def set_pin(self, raw_pin):
        if not raw_pin:
            self.pin_hash = ""
            return

        raw_pin = str(raw_pin)

        if not raw_pin.isdigit():
            raise ValidationError("El PIN debe contener solo dígitos.")

        if len(raw_pin) < 4 or len(raw_pin) > 6:
            raise ValidationError("El PIN debe tener entre 4 y 6 dígitos.")

        self.pin_hash = make_password(raw_pin)

    def check_pin(self, raw_pin):
        if not self.pin_hash:
            return False

        return check_password(str(raw_pin), self.pin_hash)

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)


class UserStoreAccess(models.Model):
    business = models.ForeignKey(
        Business,
        on_delete=models.CASCADE,
        related_name="user_store_accesses",
    )

    user = models.ForeignKey(
        CustomUser,
        on_delete=models.CASCADE,
        related_name="store_accesses",
    )

    store = models.ForeignKey(
        Stores,
        on_delete=models.CASCADE,
        related_name="user_accesses",
    )

    can_sell = models.BooleanField(default=True)
    can_open_cash = models.BooleanField(default=False)
    can_close_cash = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "acceso de usuario a tienda"
        verbose_name_plural = "accesos de usuarios a tiendas"
        constraints = [
            models.UniqueConstraint(
                fields=["business", "user", "store"],
                name="unique_user_store_access",
            )
        ]
        indexes = [
            models.Index(
                fields=["business", "user", "is_active"],
                name="user_store_access_user_idx",
            ),
            models.Index(
                fields=["business", "store", "is_active"],
                name="user_store_access_store_idx",
            ),
        ]

    def __str__(self):
        return f"{self.user} - {self.store}"

    def clean(self):
        super().clean()

        errors = {}

        if self.user_id and self.business_id:
            if self.user.business_id != self.business_id:
                errors["user"] = "El usuario no pertenece a este negocio."

        if self.store_id and self.business_id:
            if self.store.business_id != self.business_id:
                errors["store"] = "La tienda no pertenece a este negocio."

        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)