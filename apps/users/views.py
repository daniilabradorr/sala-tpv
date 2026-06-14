from django.contrib.auth.views import LoginView, LogoutView
from django.views.generic import DetailView, ListView, UpdateView
from django.contrib.auth.mixins import LoginRequiredMixin
from apps.users.mixins import *
from apps.users.models import CustomUser


# Create your views here.
class UserLoginView(LoginView):
    template_name = "users/login.html"
    redirect_authenticated_user = True

class UserLogoutView(LogoutView):
    next_page = "users:login"
    
#detail del perfil del usuario
class UserProfileDetailView(LoginRequiredMixin, DetailView):
    model = CustomUser
    template_name = "users/profile.html"
    context_object_name = "user"
    
#vista para actualizar el perfil del usuario
class UserProfileUpdateView(LoginRequiredMixin, UpdateView):
    model = CustomUser
    template_name = "users/profile_update.html"
    fields = ["first_name", "last_name", "phone"]

#ahora las vistas para cambiar la contraseña y el pin de seguridad del usuario
class UserPasswordChangeView(LoginRequiredMixin, UpdateView):
    model = CustomUser
    template_name = "users/password_change.html"
    fields = ["password"]
    
class UserPinChangeView(LoginRequiredMixin, UpdateView):
    model = CustomUser
    template_name = "users/pin_change.html"
    fields = ["pin_hash"]
    

#ahora para listar los usuarios de un negocio
#solo pueden acceder manager o owner del negocio, y el superusuario
class UserListView(LoginRequiredMixin, ManagerOrOwnerRequiredMixin, ListView):
    model = CustomUser
    template_name = "users/user_list.html"
    context_object_name = "users"
    paginate_by = 20

    def get_queryset(self):
        user = self.request.user

        if user.is_superuser:
            return CustomUser.objects.select_related("business").order_by("email")

        return (
            CustomUser.objects
            .filter(business=user.business)
            .select_related("business")
            .order_by("email")
        )
        
#ME FALTARIA TODO ESTO + TESTS + ADMIN
"""UserDetailView	Ver detalle de un usuario del negocio: datos, rol, accesos a tienda.	DetailView
UserCreateView	Crear un usuario interno: owner, manager o cashier.	CreateView
UserUpdateView	Editar un usuario: nombre, teléfono, rol, activo/inactivo.	UpdateView
UserDeactivateView	Desactivar usuario sin borrarlo. Cambia is_active=False.	View
UserActivateView	Reactivar usuario. Cambia is_active=True.	View
UserStoreAccessManageView	Gestionar tiendas asignadas a un usuario y permisos: vender, abrir caja, cerrar caja.	FormView o UpdateView personalizado"""