from django import forms
from django.contrib.auth.forms import AuthenticationForm

from apps.users.helpers import is_manager
from apps.users.models import CustomUser, RoleChoices, UserStoreAccess


def set_accessible_field_attrs(form):
    """Link bound controls to their help and error text without JavaScript."""
    if not form.is_bound:
        return form
    has_non_field_errors = bool(form.non_field_errors())
    for name, field in form.fields.items():
        described_by = []
        if field.help_text:
            described_by.append(f"id_{name}_helptext")
        if form.errors.get(name):
            described_by.append(f"id_{name}_error")
        if has_non_field_errors:
            described_by.append("form-non-field-errors")
        if form.errors.get(name) or has_non_field_errors:
            field.widget.attrs["aria-invalid"] = "true"
        if described_by:
            field.widget.attrs["aria-describedby"] = " ".join(described_by)
    return form


class UserLoginForm(AuthenticationForm):
    """Django authentication with a non-enumerating, accessible presentation."""

    error_messages = {
        "invalid_login": "No hemos podido iniciar sesión con esos datos.",
        "inactive": "No hemos podido iniciar sesión con esos datos.",
    }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["username"].label = "Correo electrónico"
        self.fields["username"].widget.attrs.update(
            {"autocomplete": "username", "placeholder": "usuario@empresa.es"}
        )
        self.fields["password"].label = "Contraseña"
        self.fields["password"].widget.attrs["autocomplete"] = "current-password"
        set_accessible_field_attrs(self)


class UserProfileUpdateForm(forms.ModelForm):
    """
    Formulario para que el usuario edite su propio perfil.

    No incluimos:
    - email
    - password
    - role
    - business
    - stores
    - pin_hash

    Porque esos campos son sensibles o se gestionan desde otras vistas.
    """

    class Meta:
        model = CustomUser
        fields = [
            "first_name",
            "last_name",
            "phone",
        ]
        labels = {
            "first_name": "Nombre",
            "last_name": "Apellidos",
            "phone": "Teléfono",
        }
        widgets = {
            "first_name": forms.TextInput(attrs={"autocomplete": "given-name"}),
            "last_name": forms.TextInput(attrs={"autocomplete": "family-name"}),
            "phone": forms.TextInput(attrs={"autocomplete": "tel"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        set_accessible_field_attrs(self)


class UserCreateForm(forms.ModelForm):
    """
    Formulario para crear usuarios internos del negocio.
    """

    password = forms.CharField(
        label="Contraseña",
        widget=forms.PasswordInput,
    )

    password_confirm = forms.CharField(
        label="Confirmar contraseña",
        widget=forms.PasswordInput,
    )

    class Meta:
        model = CustomUser
        fields = [
            "email",
            "first_name",
            "last_name",
            "phone",
            "role",
        ]

    def __init__(self, *args, business=None, actor=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.business = business
        self.actor = actor

        if self.business:
            self.instance.business = self.business

        if is_manager(self.actor):
            self.fields["role"].choices = [
                choice
                for choice in RoleChoices.choices
                if choice[0] != RoleChoices.OWNER
            ]
        set_accessible_field_attrs(self)

    def clean_role(self):
        role = self.cleaned_data["role"]
        if is_manager(self.actor) and role == RoleChoices.OWNER:
            raise forms.ValidationError("Un manager no puede asignar el rol owner.")
        return role

    def clean(self):
        cleaned_data = super().clean()

        password = cleaned_data.get("password")
        password_confirm = cleaned_data.get("password_confirm")

        if password and password_confirm and password != password_confirm:
            raise forms.ValidationError("Las contraseñas no coinciden.")

        return cleaned_data


class UserUpdateForm(forms.ModelForm):
    """
    Formulario para editar usuarios del negocio.

    Aquí sí permitimos cambiar el rol y activar/desactivar,
    porque esta vista será usada por owner/manager.
    """

    class Meta:
        model = CustomUser
        fields = [
            "first_name",
            "last_name",
            "phone",
            "role",
        ]

    def __init__(self, *args, actor=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.actor = actor

        if is_manager(self.actor):
            self.fields["role"].choices = [
                choice
                for choice in RoleChoices.choices
                if choice[0] != RoleChoices.OWNER
            ]
        set_accessible_field_attrs(self)

    def clean_role(self):
        role = self.cleaned_data["role"]
        if is_manager(self.actor) and role == RoleChoices.OWNER:
            raise forms.ValidationError("Un manager no puede asignar el rol owner.")
        return role


class UserFilterForm(forms.Form):
    q = forms.CharField(required=False, label="Buscar", max_length=150)
    role = forms.ChoiceField(
        required=False, choices=(("", "Todos"), *RoleChoices.choices), label="Rol"
    )
    status = forms.ChoiceField(
        choices=(("active", "Activos"), ("inactive", "Inactivos"), ("all", "Todos")),
        label="Estado",
    )
    store = forms.ChoiceField(required=False, label="Tienda")

    def __init__(self, *args, stores, **kwargs):
        super().__init__(*args, **kwargs)
        self.stores = list(stores)
        self.fields["store"].choices = [("", "Todas")] + [
            (str(s.pk), s.name) for s in self.stores
        ]

    def clean_store(self):
        value = self.cleaned_data["store"]
        if not value:
            return None
        store = next((s for s in self.stores if str(s.pk) == value), None)
        if store is None:
            raise forms.ValidationError("Selecciona una tienda del negocio.")
        return store


class StoreAccessMatrixForm(forms.Form):
    """One server-defined row per store; business and user are never client fields."""

    def __init__(self, *args, stores, accesses=(), **kwargs):
        super().__init__(*args, **kwargs)
        self.stores = list(stores)
        current = {a.store_id: a for a in accesses}
        for store in self.stores:
            access = current.get(store.pk)
            for suffix, label, default in (
                ("active", "Acceso", False),
                ("sell", "Vender", True),
                ("open", "Abrir caja", False),
                ("close", "Cerrar caja", False),
            ):
                attr = (
                    "is_active"
                    if suffix == "active"
                    else f"can_{suffix}"
                    if suffix == "sell"
                    else f"can_{suffix}_cash"
                )
                self.fields[f"store_{store.pk}_{suffix}"] = forms.BooleanField(
                    required=False, label=label, initial=getattr(access, attr, default)
                )

    @property
    def matrix_rows(self):
        return [
            {
                "store": s,
                "active": self[f"store_{s.pk}_active"],
                "sell": self[f"store_{s.pk}_sell"],
                "open": self[f"store_{s.pk}_open"],
                "close": self[f"store_{s.pk}_close"],
            }
            for s in self.stores
        ]

    def normalized_accesses(self):
        return {
            s.pk: {
                "is_active": self.cleaned_data[f"store_{s.pk}_active"],
                "can_sell": self.cleaned_data[f"store_{s.pk}_sell"],
                "can_open_cash": self.cleaned_data[f"store_{s.pk}_open"],
                "can_close_cash": self.cleaned_data[f"store_{s.pk}_close"],
            }
            for s in self.stores
        }


class UserPinChangeForm(forms.Form):
    """
    Formulario para cambiar el PIN del usuario actual.

    No editamos pin_hash directamente.
    La vista usará user.set_pin(new_pin).
    """

    new_pin = forms.CharField(
        label="Nuevo PIN",
        min_length=4,
        max_length=6,
        widget=forms.PasswordInput,
    )

    new_pin_confirm = forms.CharField(
        label="Confirmar nuevo PIN",
        min_length=4,
        max_length=6,
        widget=forms.PasswordInput,
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        set_accessible_field_attrs(self)

    def clean_new_pin(self):
        pin = self.cleaned_data["new_pin"]

        if not pin.isdigit():
            raise forms.ValidationError("El PIN debe contener solo dígitos.")

        return pin

    def clean(self):
        cleaned_data = super().clean()

        new_pin = cleaned_data.get("new_pin")
        new_pin_confirm = cleaned_data.get("new_pin_confirm")

        if new_pin and new_pin_confirm and new_pin != new_pin_confirm:
            raise forms.ValidationError("Los PIN no coinciden.")

        return cleaned_data


class UserStoreAccessForm(forms.ModelForm):
    """
    Formulario para un acceso concreto de usuario a tienda.

    Cada formulario representa un registro UserStoreAccess.
    """

    class Meta:
        model = UserStoreAccess
        fields = [
            "store",
            "can_sell",
            "can_open_cash",
            "can_close_cash",
            "is_active",
        ]
