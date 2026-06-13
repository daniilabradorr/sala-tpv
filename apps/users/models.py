from django.db import models
from django.core.exceptions import ValidationError
from django.contrib.auth.base_user import AbstractBaseUser
from django.contrib.auth.models import PermissionsMixin

from apps.core.models import Business
from .managers import CustomUserManager

import uuid


class RoleChoices(models.TextChoices):
    OWNER = "owner", "Owner"
    MANAGER = "manager", "Manager"
    CASHIER = "cashier", "Cashier"


# Create your models here.
class CustomUser(AbstractBaseUser, PermissionsMixin):
    business = models.ForeignKey(
        Business,
        on_delete=models.CASCADE,
        related_name="users",
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
    created_at = models.DateTimeField(auto_now_add=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = ["firts_name", "last_name", "rol", "phone"]

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
        """aqui ahora lo que quiero hacer es que phone
        tenga un formato correcto."""

        if self.phone and not self.phone.isdigit():
            raise ValidationError(
                "ERROR: El número de teléfono debe contener solo dígitos."
            )

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)
