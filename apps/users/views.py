from django.contrib.auth.views import LoginView, LogoutView, PasswordChangeView
from django.contrib import messages
from django.urls import reverse_lazy, reverse
from django.views.generic import (
    CreateView,
    DetailView,
    ListView,
    UpdateView,
    View,
    FormView,
)
from apps.users.forms import (
    UserStoreAccessFormSet,
    UserProfileUpdateForm,
    UserCreateForm,
    UserUpdateForm,
    UserPinChangeForm,
)
from django.shortcuts import redirect, get_object_or_404, render
from django.contrib.auth.mixins import LoginRequiredMixin

from apps.users.mixins import BusinessUserQuerysetMixin, ManagerOrOwnerRequiredMixin
from apps.users.models import CustomUser, UserStoreAccess
from apps.stores.models import Stores


# Create your views here.
class UserLoginView(LoginView):
    template_name = "users/login.html"
    redirect_authenticated_user = True


class UserLogoutView(LogoutView):
    next_page = "users:login"


# detail del perfil del usuario
class UserProfileDetailView(LoginRequiredMixin, DetailView):
    model = CustomUser
    template_name = "users/profile.html"
    context_object_name = "user"

    def get_object(self, queryset=None):
        """
        Devuelve siempre el usuario logueado.
        Así evitamos que un usuario vea el perfil de otro cambiando la URL.
        """
        return self.request.user


# vista para actualizar el perfil del usuario
class UserProfileUpdateView(LoginRequiredMixin, UpdateView):
    model = CustomUser
    form_class = UserProfileUpdateForm
    template_name = "users/profile_update.html"
    context_object_name = "profile_user"
    success_url = reverse_lazy("users:profile")

    def get_object(self, queryset=None):
        """
        Edita siempre el usuario logueado.
        """
        return self.request.user

    def form_valid(self, form):
        messages.success(self.request, "Perfil actualizado correctamente.")
        return super().form_valid(form)


# ahora las vistas para cambiar la contraseña y el pin de seguridad del usuario
class UserPasswordChangeView(LoginRequiredMixin, PasswordChangeView):
    template_name = "users/password_change.html"
    success_url = reverse_lazy("users:profile")

    def form_valid(self, form):
        messages.success(self.request, "Contraseña actualizada correctamente.")
        return super().form_valid(form)


class UserPinChangeView(LoginRequiredMixin, FormView):
    template_name = "users/pin_change.html"
    form_class = UserPinChangeForm
    success_url = reverse_lazy("users:profile")

    def form_valid(self, form):
        user = self.request.user
        new_pin = form.cleaned_data["new_pin"]

        user.set_pin(new_pin)
        user.save(update_fields=["pin_hash", "updated_at"])

        messages.success(self.request, "PIN actualizado correctamente.")
        return super().form_valid(form)


# ahora la gestion de susuarios del negocio, solo accesible para manager o owner del negocio, y el superusuario
class UserListView(ManagerOrOwnerRequiredMixin, BusinessUserQuerysetMixin, ListView):
    model = CustomUser
    template_name = "users/user_list.html"
    context_object_name = "users"
    paginate_by = 20


class UserDetailView(
    ManagerOrOwnerRequiredMixin,
    BusinessUserQuerysetMixin,
    DetailView,
):
    model = CustomUser
    template_name = "users/user_detail.html"
    context_object_name = "target_user"


class UserCreateView(ManagerOrOwnerRequiredMixin, CreateView):
    model = CustomUser
    form_class = UserCreateForm
    template_name = "users/user_create.html"

    def get_form_kwargs(self):
        # para mandar al form el business del usuario logueado, para que el nuevo usuario se cree en el mismo negocio
        # y asi no puede poner otro negocio, ni el superusuario puede poner otro negocio, porque el form lo ignora y pone el del usuario logueado
        kwargs = super().get_form_kwargs()

        if not self.request.user.is_superuser:
            kwargs["business"] = self.request.user.business

        return kwargs

    def form_valid(self, form):
        new_user = form.save(commit=False)

        if not self.request.user.is_superuser:
            new_user.business = self.request.user.business

        password = form.cleaned_data.get("password")
        if password:
            new_user.set_password(password)

        new_user.save()
        form.save_m2m()

        messages.success(self.request, "Usuario creado correctamente.")
        self.object = new_user
        return redirect(self.get_success_url())

    def get_success_url(self):
        return reverse("users:user_detail", kwargs={"pk": self.object.pk})


class UserUpdateView(
    ManagerOrOwnerRequiredMixin, BusinessUserQuerysetMixin, UpdateView
):
    model = CustomUser
    form_class = UserUpdateForm
    template_name = "users/user_update.html"
    context_object_name = "target_user"

    def form_valid(self, form):
        messages.success(self.request, "Usuario actualizado correctamente.")
        return super().form_valid(form)

    def get_success_url(self):
        return reverse("users:user_detail", kwargs={"pk": self.object.pk})


class UserDeactivateView(ManagerOrOwnerRequiredMixin, BusinessUserQuerysetMixin, View):
    """
    Desactiva un usuario sin borrarlo.
    Debe hacerse por POST.
    """

    def post(self, request, *args, **kwargs):
        target_user = get_object_or_404(
            self.get_queryset(),
            pk=kwargs["pk"],
        )

        if target_user == request.user:
            messages.error(request, "No puedes desactivar tu propio usuario.")
            return redirect("users:user_detail", pk=target_user.pk)

        target_user.is_active = False
        target_user.save(update_fields=["is_active", "updated_at"])

        messages.success(request, "Usuario desactivado correctamente.")
        return redirect("users:user_list")


class UserActivateView(ManagerOrOwnerRequiredMixin, BusinessUserQuerysetMixin, View):
    """
    Reactiva un usuario desactivado.
    Debe hacerse por POST.
    """

    def post(self, request, *args, **kwargs):
        target_user = get_object_or_404(
            self.get_queryset(),
            pk=kwargs["pk"],
        )

        target_user.is_active = True
        target_user.save(update_fields=["is_active", "updated_at"])

        messages.success(request, "Usuario activado correctamente.")
        return redirect("users:user_detail", pk=target_user.pk)


# GESTIÓN DE ACCESOS A TIENDAS
class UserStoreAccessManageView(
    ManagerOrOwnerRequiredMixin,
    BusinessUserQuerysetMixin,
    View,
):
    """
    Vista para gestionar los accesos de un usuario a las tiendas del negocio.

    Esta vista NO crea usuarios.
    Esta vista NO crea tiendas.
    Esta vista NO abre ni cierra cajas.

    Solo gestiona registros de UserStoreAccess, es decir:

        Usuario X puede acceder a Tienda Y
        Usuario X puede vender en Tienda Y
        Usuario X puede abrir caja en Tienda Y
        Usuario X puede cerrar caja en Tienda Y
        Usuario X tiene ese acceso activo/inactivo

    Se usa porque en el sistema no relacionamos directamente User con CashRegister.
    La relación correcta es:

        User -> UserStoreAccess -> Store -> CashRegister

    Por eso los permisos de caja se controlan a nivel de tienda.
    """

    template_name = "users/user_store_access_manage.html"

    def get_target_user(self):
        """
        Obtiene el usuario al que vamos a gestionar los accesos.

        El pk viene de la URL, por ejemplo:

            /users/5/store-access/

        Pero NO buscamos el usuario directamente con CustomUser.objects.get(pk=5),
        porque eso permitiría acceder a usuarios de otros negocios si alguien manipula la URL.

        Usamos self.get_queryset(), que viene de BusinessUserQuerysetMixin.
        Ese queryset ya está filtrado por business, salvo si el usuario actual es superuser.

        Resultado:
            - Un owner/manager solo puede gestionar usuarios de su propio negocio.
            - Un superuser puede gestionar todos.
        """
        return get_object_or_404(
            self.get_queryset(),
            pk=self.kwargs["pk"],
        )

    def get_access_queryset(self, target_user):
        """
        Obtiene los accesos actuales del usuario a tiendas.

        Aquí buscamos registros UserStoreAccess del usuario que estamos editando.

        Ejemplo de resultados:
            - Tienda Centro: puede vender, puede abrir caja, no puede cerrar caja
            - Tienda Norte: puede vender, no puede abrir caja, no puede cerrar caja

        Filtramos por:
            business=target_user.business
            user=target_user

        Esto evita mezclar accesos de otro negocio.

        select_related("store"):
            Carga también la tienda relacionada para evitar consultas extra
            cuando en el template mostremos access.store.name.

        order_by("store__name"):
            Ordena los accesos por nombre de tienda.
        """
        return (
            UserStoreAccess.objects.filter(
                business=target_user.business,
                user=target_user,
            )
            .select_related("store")
            .order_by("store__name")
        )

    def build_formset(self, target_user, data=None):
        """
        Construye el formset de accesos a tiendas.

        ¿Por qué usamos un formset?

        Porque un usuario puede tener varios accesos, uno por cada tienda.

        Ejemplo:
            Formulario 1 -> Tienda Centro
            Formulario 2 -> Tienda Norte
            Formulario 3 -> Tienda Online

        Cada formulario representa un UserStoreAccess.

        data=None:
            Se usa cuando entramos por GET.
            Muestra los datos actuales.

        data=request.POST:
            Se usa cuando enviamos el formulario por POST.
            Valida y guarda los cambios enviados.

        prefix="store_accesses":
            Sirve para identificar este formset en el HTML.
            Es útil si en la misma página hubiera más formularios.
        """
        formset = UserStoreAccessFormSet(
            data=data,
            queryset=self.get_access_queryset(target_user),
            prefix="store_accesses",
        )

        """
        Aquí limitamos el campo 'store' de cada formulario.

        ¿Por qué?

        Porque no queremos que aparezcan tiendas de otros negocios.
        Solo deben poder seleccionarse tiendas activas del negocio del usuario.

        Esto también protege contra manipulación del HTML:
        aunque alguien modifique el formulario desde el navegador,
        el queryset del campo store solo acepta tiendas válidas.
        """
        for form in formset.forms:
            if "store" in form.fields:
                form.fields["store"].queryset = Stores.objects.filter(
                    business=target_user.business,
                    is_active=True,
                ).order_by("name")

        return formset

    def get(self, request, *args, **kwargs):
        """
        Método que se ejecuta cuando entramos a la página.

        Flujo:
            1. Busca el usuario que vamos a gestionar.
            2. Construye el formset con sus accesos actuales.
            3. Renderiza la plantilla.

        En la plantilla tendremos:
            target_user -> usuario gestionado
            formset -> formularios de accesos a tiendas
        """
        target_user = self.get_target_user()
        formset = self.build_formset(target_user)

        return render(
            request,
            self.template_name,
            {
                "target_user": target_user,
                "formset": formset,
            },
        )

    def post(self, request, *args, **kwargs):
        """
        Método que se ejecuta cuando enviamos el formulario.

        Flujo:
            1. Busca el usuario que vamos a gestionar.
            2. Construye el formset con los datos enviados por POST.
            3. Valida el formset.
            4. Si es válido:
                - Guarda accesos nuevos o modificados.
                - Borra accesos marcados para eliminar.
                - Redirige al detalle del usuario.
            5. Si no es válido:
                - Vuelve a mostrar la plantilla con errores.
        """
        target_user = self.get_target_user()
        formset = self.build_formset(target_user, data=request.POST)

        if formset.is_valid():
            """
            save(commit=False) crea los objetos modificados,
            pero todavía NO los guarda en base de datos.

            ¿Por qué no guardamos directamente?

            Porque antes necesitamos asignar campos protegidos:
                access.business = target_user.business
                access.user = target_user

            Estos campos no deberían venir del formulario.
            Los controlamos nosotros desde backend.
            """
            instances = formset.save(commit=False)

            """
            Si el formset permite borrar registros con can_delete=True,
            aquí eliminamos los accesos marcados para borrar.

            Ejemplo:
                Quitar acceso del usuario a Tienda Norte.
            """
            for deleted_object in formset.deleted_objects:
                deleted_object.delete()

            """
            Guardamos cada acceso nuevo o modificado.

            Forzamos:
                business = negocio del usuario gestionado
                user = usuario gestionado

            Así evitamos que alguien pueda manipular el POST
            para asignar accesos a otro usuario o a otro negocio.
            """
            for access in instances:
                access.business = target_user.business
                access.user = target_user
                access.save()

            messages.success(
                request,
                "Accesos a tiendas actualizados correctamente.",
            )

            """
            Cuando todo se guarda bien, mandamos al detalle del usuario.
            """
            return redirect("users:user_detail", pk=target_user.pk)

        """
        Si el formset no es válido, volvemos a mostrar la página
        con los errores de validación.
        """
        return render(
            request,
            self.template_name,
            {
                "target_user": target_user,
                "formset": formset,
            },
        )
