from django.core.exceptions import PermissionDenied, ValidationError
from django.utils import timezone
from apps.audit.presentation import present_event
from apps.audit.selectors import get_audit_events
from apps.reports.periods import report_period_from_dates
from apps.stores.selectors import get_stores_available_for_user
from apps.users.forms import UserFilterForm, StoreAccessMatrixForm
from apps.users.helpers import can_manage_user
from apps.users.models import RoleChoices
from apps.users.selectors import get_users_for_admin
from apps.users.services import (
    activate_user,
    create_user_with_store_accesses,
    deactivate_user,
    update_user,
    update_user_store_accesses,
)

from django.contrib.auth.views import LoginView, LogoutView, PasswordChangeView
from django.contrib import messages
from django.urls import reverse_lazy, reverse
from django.views.generic import (
    DetailView,
    ListView,
    UpdateView,
    View,
    FormView,
)
from apps.users.forms import (
    UserProfileUpdateForm,
    UserCreateForm,
    UserUpdateForm,
    UserPinChangeForm,
    UserLoginForm,
    set_accessible_field_attrs,
)
from django.shortcuts import redirect, get_object_or_404, render
from django.contrib.auth.mixins import LoginRequiredMixin

from apps.users.mixins import (
    ManagerOrOwnerRequiredMixin,
)
from apps.users.models import CustomUser
from apps.stores.models import Store


# Create your views here.
class UserLoginView(LoginView):
    template_name = "users/login.html"
    authentication_form = UserLoginForm
    redirect_authenticated_user = True

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["session_expired"] = self.request.GET.get("expired") == "1"
        return context


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

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["active_tab"] = (
            "security" if self.request.GET.get("tab") == "security" else "profile"
        )
        return context


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

    def get_success_url(self):
        return f"{reverse('users:profile')}?tab=security"

    def get_form(self, form_class=None):
        return set_accessible_field_attrs(super().get_form(form_class))

    def form_valid(self, form):
        messages.success(self.request, "Contraseña actualizada correctamente.")
        return super().form_valid(form)


class UserPinChangeView(LoginRequiredMixin, FormView):
    template_name = "users/pin_change.html"
    form_class = UserPinChangeForm

    def get_success_url(self):
        return f"{reverse('users:profile')}?tab=security"

    def form_valid(self, form):
        user = self.request.user
        new_pin = form.cleaned_data["new_pin"]

        user.set_pin(new_pin)
        user.save(update_fields=["pin_hash", "updated_at"])

        messages.success(self.request, "PIN actualizado correctamente.")
        return super().form_valid(form)


# Administración pública de usuarios (FE-22)
class AdminUsersMixin(ManagerOrOwnerRequiredMixin):
    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated and not request.user.business_id:
            raise PermissionDenied("Se necesita un contexto de negocio.")
        return super().dispatch(request, *args, **kwargs)

    def business(self):
        business = getattr(self.request.user, "business", None)
        if business is None:
            raise PermissionDenied("Se necesita un contexto de negocio.")
        return business

    def target(self):
        return get_object_or_404(
            get_users_for_admin(business=self.business(), status="all"),
            pk=self.kwargs["pk"],
        )


class UserListView(AdminUsersMixin, ListView):
    model = CustomUser
    template_name = "users/user_list.html"
    context_object_name = "users"
    paginate_by = 20

    def get_queryset(self):
        data = self.request.GET.copy()
        data.setdefault("status", "active")
        self.filter_form = UserFilterForm(
            data, stores=Store.objects.filter(business=self.business()).order_by("name")
        )
        return (
            get_users_for_admin(
                business=self.business(), **self.filter_form.cleaned_data
            )
            if self.filter_form.is_valid()
            else CustomUser.objects.none()
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        query = self.request.GET.copy()
        query.pop("page", None)
        context.update(filter_form=self.filter_form, pagination_query=query.urlencode())
        return context


class UserDetailView(AdminUsersMixin, View):
    def get(self, request, pk):
        target = self.target()
        tab = request.GET.get("tab", "summary")
        if tab not in {"summary", "stores", "activity"}:
            tab = "summary"
        stores = Store.objects.filter(business=self.business()).order_by("name")
        access_map = {
            a.store_id: a for a in target.store_accesses.select_related("store")
        }
        activity = []
        if tab == "activity":
            scope = (
                None
                if request.user.role == RoleChoices.OWNER
                else get_stores_available_for_user(user=request.user, only_active=False)
            )
            end = timezone.localdate()
            period = report_period_from_dates(
                date_from=end - timezone.timedelta(days=29), date_to=end
            )
            activity = [
                present_event(e, user=request.user)
                for e in get_audit_events(
                    business=self.business(), stores=scope, user=target, period=period
                )[:25]
            ]
        return render(
            request,
            "users/user_detail.html",
            {
                "target_user": target,
                "active_tab": tab,
                "store_rows": [
                    {"store": s, "access": access_map.get(s.pk)} for s in stores
                ],
                "activity": activity,
                "can_manage_target": can_manage_user(request.user, target),
            },
        )


class UserCreateView(AdminUsersMixin, View):
    template_name = "users/user_create.html"

    def forms(self, data=None):
        stores = list(Store.objects.filter(business=self.business()).order_by("name"))
        return (
            UserCreateForm(data, business=self.business(), actor=self.request.user),
            StoreAccessMatrixForm(data, stores=stores),
            stores,
        )

    def get(self, request):
        form, matrix, stores = self.forms()
        return render(
            request,
            self.template_name,
            {"form": form, "matrix": matrix, "stores": stores},
        )

    def post(self, request):
        form, matrix, stores = self.forms(request.POST)
        if form.is_valid() and matrix.is_valid():
            user = create_user_with_store_accesses(
                actor=request.user,
                user_data=form.cleaned_data.copy(),
                accesses=matrix.normalized_accesses(),
            )
            messages.success(request, "Usuario creado correctamente.")
            return redirect("users:user_detail", pk=user.pk)
        return render(
            request,
            self.template_name,
            {"form": form, "matrix": matrix, "stores": stores},
            status=422,
        )


class UserUpdateView(AdminUsersMixin, View):
    template_name = "users/user_update.html"

    def dispatch(self, request, *args, **kwargs):
        if not can_manage_user(request.user, self.target()):
            raise PermissionDenied
        return super().dispatch(request, *args, **kwargs)

    def get(self, request, pk):
        target = self.target()
        return render(
            request,
            self.template_name,
            {
                "form": UserUpdateForm(instance=target, actor=request.user),
                "target_user": target,
            },
        )

    def post(self, request, pk):
        target = self.target()
        form = UserUpdateForm(request.POST, instance=target, actor=request.user)
        if form.is_valid():
            target = update_user(
                actor=request.user, target_user=target, data=form.cleaned_data
            )
            messages.success(request, "Usuario actualizado correctamente.")
            return redirect("users:user_detail", pk=target.pk)
        return render(
            request,
            self.template_name,
            {"form": form, "target_user": target},
            status=422,
        )


class LifecycleView(AdminUsersMixin, View):
    activate = False

    def dispatch(self, request, *args, **kwargs):
        if not can_manage_user(request.user, self.target()):
            raise PermissionDenied
        return super().dispatch(request, *args, **kwargs)

    def get(self, request, pk):
        return render(
            request,
            "users/user_lifecycle_confirm.html",
            {"target_user": self.target(), "activate": self.activate},
        )

    def post(self, request, pk):
        try:
            (activate_user if self.activate else deactivate_user)(
                actor=request.user, target_user=self.target()
            )
        except ValidationError as exc:
            messages.error(request, "; ".join(exc.messages))
            return redirect("users:user_detail", pk=pk)
        messages.success(
            request,
            "Usuario reactivado correctamente."
            if self.activate
            else "Usuario desactivado correctamente.",
        )
        return redirect("users:user_detail", pk=pk)


class UserDeactivateView(LifecycleView):
    pass


class UserActivateView(LifecycleView):
    activate = True


class UserStoreAccessManageView(AdminUsersMixin, View):
    template_name = "users/user_store_access_manage.html"

    def dispatch(self, request, *args, **kwargs):
        target = self.target()
        if (
            not can_manage_user(request.user, target)
            or target.role == RoleChoices.OWNER
        ):
            raise PermissionDenied
        return super().dispatch(request, *args, **kwargs)

    def form(self, data=None):
        target = self.target()
        stores = list(Store.objects.filter(business=self.business()).order_by("name"))
        return StoreAccessMatrixForm(
            data, stores=stores, accesses=target.store_accesses.all()
        ), stores

    def get(self, request, pk):
        form, stores = self.form()
        return render(
            request,
            self.template_name,
            {"matrix": form, "stores": stores, "target_user": self.target()},
        )

    def post(self, request, pk):
        form, stores = self.form(request.POST)
        if form.is_valid():
            update_user_store_accesses(
                actor=request.user,
                target_user=self.target(),
                accesses=form.normalized_accesses(),
            )
            messages.success(request, "Accesos a tiendas actualizados correctamente.")
            return redirect(
                reverse("users:user_detail", kwargs={"pk": pk}) + "?tab=stores"
            )
        return render(
            request,
            self.template_name,
            {"matrix": form, "stores": stores, "target_user": self.target()},
            status=422,
        )
