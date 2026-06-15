from django import forms
from django.forms import modelformset_factory

from apps.users.models import CustomUser, UserStoreAccess


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
            "is_active",
        ]


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


UserStoreAccessFormSet = modelformset_factory(
    UserStoreAccess,
    form=UserStoreAccessForm,
    extra=1,
    can_delete=True,
)
