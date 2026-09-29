from urllib.parse import urlsplit

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import Resolver404, resolve, reverse, reverse_lazy
from django.utils.http import url_has_allowed_host_and_scheme
from django.views import View
from django.views.decorators.http import require_POST
from django.views.generic import (
    CreateView,
    DeleteView,
    DetailView,
    ListView,
    UpdateView,
)

from apps.cash_register.selectors import get_cash_registers_for_store
from apps.core.shell import ACTIVE_STORE_SESSION_KEY, get_shell_stores_for_user
from apps.stores.forms import StoreCreateForm, StoreUpdateForm
from apps.stores.models import Store
from apps.stores.selectors import (
    get_store_admin_list,
    get_store_kpis,
    get_store_team,
    get_stores_available_for_user,
)
from apps.stores.services import (
    activate_store,
    deactivate_store,
    delete_store,
    set_default_store,
)
from apps.users.helpers import can_access_store, can_manage_stores
from apps.users.mixins import (
    BusinessRequiredMixin,
    ManagerOrOwnerRequiredMixin,
    StoreAccessRequiredMixin,
)


def _business(user):
    business = getattr(user, "business", None)
    if business is None:
        raise PermissionDenied("Se requiere un contexto de negocio explícito.")
    return business


@login_required
@require_POST
def set_active_store(request, pk):
    """Persist an authorized operational Store context; never changes default."""
    _business(request.user)
    store = next(
        (item for item in get_shell_stores_for_user(request.user) if item.pk == pk),
        None,
    )
    if store is None:
        raise Http404
    request.session[ACTIVE_STORE_SESSION_KEY] = store.pk
    next_url = request.POST.get("next", "")
    if not url_has_allowed_host_and_scheme(
        next_url, {request.get_host()}, require_https=request.is_secure()
    ):
        return redirect("core:home")
    try:
        match = resolve(urlsplit(next_url).path)
    except Resolver404:
        return redirect("core:home")
    scoped = {
        "sales": ("sales:sale_list", {"store_id": store.pk}),
        "cash_register": ("cash_register:register_list", {"store_id": store.pk}),
        "billing": ("billing:document_list", {"store_id": store.pk}),
        "payments": ("sales:sale_list", {"store_id": store.pk}),
    }
    if match.namespace in scoped:
        route, kwargs = scoped[match.namespace]
        return redirect(route, **kwargs)
    return redirect(next_url)


class ListStoresView(BusinessRequiredMixin, ListView):
    model = Store
    template_name = "stores/list_stores.html"
    context_object_name = "stores"
    paginate_by = 10

    def get_queryset(self):
        user = self.request.user
        business = _business(user)
        if can_manage_stores(user):
            queryset = get_store_admin_list(
                business=business,
                query=self.request.GET.get("q"),
                status=self.request.GET.get("status", "all"),
            )
        else:
            queryset = get_stores_available_for_user(user=user, only_active=False)
            query = (self.request.GET.get("q") or "").strip()
            if query:
                from django.db.models import Q

                queryset = queryset.filter(
                    Q(name__icontains=query)
                    | Q(code__icontains=query)
                    | Q(city__icontains=query)
                )
            status = self.request.GET.get("status", "all")
            if status in {"active", "inactive"}:
                queryset = queryset.filter(is_active=status == "active")
        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        business = _business(self.request.user)
        if can_manage_stores(self.request.user):
            kpis = get_store_kpis(business=business)
        else:
            available = get_stores_available_for_user(
                user=self.request.user, only_active=False
            )
            kpis = {
                "active": available.filter(is_active=True).count(),
                "inactive": available.filter(is_active=False).count(),
                "default": available.filter(is_default=True)
                .values_list("name", flat=True)
                .first(),
            }
        context.update(
            can_manage_stores=can_manage_stores(self.request.user),
            q=(self.request.GET.get("q") or "").strip(),
            status=self.request.GET.get("status", "all"),
            kpis=kpis,
        )
        params = self.request.GET.copy()
        params.pop("page", None)
        context["filter_query"] = params.urlencode()
        return context


class StoreDetailView(StoreAccessRequiredMixin, DetailView):
    model = Store
    template_name = "stores/store_detail.html"
    context_object_name = "store"
    store_kwarg = "pk"

    @staticmethod
    def permission_checker(user, store):
        if user.is_superuser:
            return bool(user.business_id) and user.business_id == store.business_id
        return (
            can_manage_stores(user) and user.business_id == store.business_id
        ) or can_access_store(user, store)

    def get_queryset(self):
        return Store.objects.select_related("business", "business__profile").filter(
            business=_business(self.request.user)
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        tab = self.request.GET.get("tab", "summary")
        if tab not in {"summary", "operation", "team", "settings"}:
            tab = "summary"
        store = self.object
        business = _business(self.request.user)
        context.update(
            tab=tab,
            can_manage_stores=can_manage_stores(self.request.user),
            can_operate=store.is_active and can_access_store(self.request.user, store),
            cash_registers=get_cash_registers_for_store(business=business, store=store),
            team=get_store_team(business=business, store=store),
            active_store_id=self.request.session.get(ACTIVE_STORE_SESSION_KEY),
            operation_links=[
                (
                    "Ventas",
                    "Ir al TPV",
                    reverse("sales:sale_list", kwargs={"store_id": store.pk}),
                ),
                (
                    "Caja",
                    "Ir a caja",
                    reverse(
                        "cash_register:register_list", kwargs={"store_id": store.pk}
                    ),
                ),
                ("Inventario", "Ver stock", reverse("inventory:dashboard")),
                ("Compras", "Ver compras", reverse("purchases:purchase_list")),
                (
                    "Facturación",
                    "Ver documentos",
                    reverse("billing:document_list", kwargs={"store_id": store.pk}),
                ),
            ],
        )
        return context


class StoreCreateView(ManagerOrOwnerRequiredMixin, CreateView):
    model = Store
    form_class = StoreCreateForm
    template_name = "stores/store_create.html"

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["business"] = _business(self.request.user)
        return kwargs

    def form_valid(self, form):
        form.instance.business = _business(self.request.user)
        response = super().form_valid(form)
        messages.success(self.request, "Tienda creada correctamente.")
        return response

    def get_success_url(self):
        return reverse("stores:store_detail", kwargs={"pk": self.object.pk})


class StoreUpdateView(ManagerOrOwnerRequiredMixin, UpdateView):
    model = Store
    form_class = StoreUpdateForm
    template_name = "stores/store_update.html"

    def get_queryset(self):
        return Store.objects.filter(business=_business(self.request.user))

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["business"] = _business(self.request.user)
        return kwargs

    def form_valid(self, form):
        response = super().form_valid(form)
        messages.success(self.request, "Tienda actualizada correctamente.")
        return response

    def get_success_url(self):
        return reverse("stores:store_detail", kwargs={"pk": self.object.pk})


class StoreLifecycleView(ManagerOrOwnerRequiredMixin, View):
    action = None
    template_name = "stores/store_confirm_action.html"

    def store(self, request, pk):
        return get_object_or_404(Store, pk=pk, business=_business(request.user))

    def get(self, request, pk):
        return render(
            request,
            self.template_name,
            {"store": self.store(request, pk), "action": self.action},
        )


class StoreDeactivateView(StoreLifecycleView):
    action = "deactivate"

    def post(self, request, pk):
        store = self.store(request, pk)
        try:
            deactivate_store(business=_business(request.user), store=store)
        except ValidationError as exc:
            messages.error(request, " ".join(exc.messages))
        else:
            messages.success(request, "Tienda desactivada correctamente.")
        return redirect("stores:store_detail", pk=store.pk)


class StoreActivateView(StoreLifecycleView):
    action = "activate"

    def post(self, request, pk):
        store = self.store(request, pk)
        activate_store(business=_business(request.user), store=store)
        messages.success(request, "Tienda activada correctamente.")
        return redirect("stores:store_detail", pk=store.pk)


class StoreSetDefaultView(StoreLifecycleView):
    action = "default"

    def post(self, request, pk):
        store = self.store(request, pk)
        try:
            set_default_store(business=_business(request.user), store=store)
        except ValidationError as exc:
            messages.error(request, " ".join(exc.messages))
        else:
            messages.success(
                request, f"'{store.name}' es ahora la tienda predeterminada."
            )
        return redirect("stores:store_detail", pk=store.pk)


class StoreDeleteView(ManagerOrOwnerRequiredMixin, DeleteView):
    model = Store
    template_name = "stores/store_confirm_delete.html"
    context_object_name = "store"
    success_url = reverse_lazy("stores:store_list")

    def get_queryset(self):
        return Store.objects.filter(business=_business(self.request.user))

    def form_valid(self, form):
        if self.request.POST.get("confirmation") != "ELIMINAR":
            messages.error(
                self.request, "Escribe ELIMINAR para confirmar el borrado definitivo."
            )
            return render(
                self.request, self.template_name, {"store": self.object}, status=422
            )
        pk = self.object.pk
        try:
            name = delete_store(
                business=_business(self.request.user), store=self.object
            )
        except ValidationError as exc:
            messages.error(self.request, " ".join(exc.messages))
            return redirect("stores:store_detail", pk=pk)
        messages.success(
            self.request, f"La tienda '{name}' ha sido eliminada correctamente."
        )
        return redirect(self.success_url)
