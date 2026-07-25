from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse, reverse_lazy
from django.views import View
from django.views.generic import (
    CreateView,
    DeleteView,
    DetailView,
    ListView,
    UpdateView,
)

from apps.stores.forms import StoreCreateForm, StoreUpdateForm
from apps.stores.models import Store
from apps.stores.services import (
    activate_store,
    deactivate_store,
    delete_store,
    set_default_store,
)
from apps.users.mixins import (
    BusinessRequiredMixin,
    ManagerOrOwnerRequiredMixin,
    StoreAccessRequiredMixin,
)


class ListStoresView(BusinessRequiredMixin, ListView):
    model = Store
    template_name = "stores/list_stores.html"
    context_object_name = "stores"
    paginate_by = 10

    def get_queryset(self):
        """
        Devuelve únicamente las tiendas pertenecientes al negocio
        del usuario autenticado.
        """
        queryset = super().get_queryset()

        return queryset.filter(
            business=self.request.user.business,
        )


class StoreDetailView(StoreAccessRequiredMixin, DetailView):
    """
    Muestra el detalle de una tienda accesible para el usuario.

    StoreAccessRequiredMixin comprueba que el usuario tenga acceso
    a la tienda antes de mostrarla.
    """

    model = Store
    template_name = "stores/store_detail.html"
    context_object_name = "store"

    # El mixin busca por defecto un parámetro llamado store_id,
    # pero nuestras URLs utilizan <int:pk>.
    store_kwarg = "pk"

    def get_queryset(self):
        """
        Refuerza el aislamiento multiempresa.

        Aunque se manipule el identificador de la URL, nunca se
        devolverá una tienda perteneciente a otro negocio.
        """
        queryset = super().get_queryset()

        if self.request.user.is_superuser:
            return queryset

        return queryset.filter(
            business=self.request.user.business,
        )


class StoreCreateView(ManagerOrOwnerRequiredMixin, CreateView):
    model = Store
    form_class = StoreCreateForm
    template_name = "stores/store_create.html"

    def dispatch(self, request, *args, **kwargs):
        """
        Comprueba que el usuario tenga un negocio asociado.

        Una tienda nunca debe crearse sin pertenecer a un Business.
        """
        if not request.user.is_superuser and not getattr(
            request.user, "business_id", None
        ):
            raise PermissionDenied("El usuario no tiene un negocio asociado.")

        return super().dispatch(request, *args, **kwargs)

    def get_form_kwargs(self):
        """
        Pasa el negocio al formulario desde el usuario autenticado.

        El Business no se recibe desde el formulario para evitar que
        alguien manipule el POST y asigne la tienda a otra empresa.
        """
        kwargs = super().get_form_kwargs()

        if not self.request.user.is_superuser:
            kwargs["business"] = self.request.user.business

        return kwargs

    def form_valid(self, form):
        """
        Asigna el negocio de forma segura antes de guardar.
        """
        if self.request.user.is_superuser:
            raise PermissionDenied(
                "El superusuario debe trabajar dentro de un "
                "contexto de negocio explícito."
            )

        form.instance.business = self.request.user.business

        response = super().form_valid(form)

        messages.success(
            self.request,
            "Tienda creada correctamente.",
        )

        return response

    def get_success_url(self):
        return reverse(
            "stores:store_detail",
            kwargs={"pk": self.object.pk},
        )


class StoreUpdateView(ManagerOrOwnerRequiredMixin, UpdateView):
    model = Store
    form_class = StoreUpdateForm
    template_name = "stores/store_update.html"

    def get_queryset(self):
        """
        Solo permite editar tiendas del negocio autenticado.
        """
        queryset = super().get_queryset()

        if self.request.user.is_superuser:
            return queryset

        return queryset.filter(
            business=self.request.user.business,
        )

    def form_valid(self, form):
        """
        Guarda la tienda utilizando las validaciones de Store.
        """
        response = super().form_valid(form)

        messages.success(
            self.request,
            "Tienda actualizada correctamente.",
        )

        return response

    def get_success_url(self):
        return reverse(
            "stores:store_detail",
            kwargs={"pk": self.object.pk},
        )


class StoreDeactivateView(ManagerOrOwnerRequiredMixin, View):
    """
    Desactiva una tienda sin eliminarla.

    La lógica se delega en deactivate_store(), que protege:

    - El aislamiento multiempresa.
    - Las modificaciones concurrentes.
    - El cambio de tienda predeterminada.
    - La transacción completa.
    """

    def post(self, request, pk):
        store = get_object_or_404(
            Store,
            pk=pk,
            business=request.user.business,
        )

        was_active = store.is_active

        try:
            store = deactivate_store(
                business=request.user.business,
                store=store,
            )
        except ValidationError as exc:
            messages.error(
                request,
                " ".join(exc.messages),
            )

            return redirect(
                "stores:store_detail",
                pk=store.pk,
            )

        if not was_active:
            messages.info(
                request,
                "La tienda ya estaba desactivada.",
            )
        else:
            messages.success(
                request,
                "Tienda desactivada correctamente.",
            )

        return redirect(
            "stores:store_detail",
            pk=store.pk,
        )


class StoreActivateView(ManagerOrOwnerRequiredMixin, View):
    """
    Reactiva una tienda previamente desactivada.

    Cuando no existe otra tienda predeterminada activa, el modelo
    puede convertir la tienda activada en predeterminada.
    """

    def post(self, request, pk):
        store = get_object_or_404(
            Store,
            pk=pk,
            business=request.user.business,
        )

        was_active = store.is_active

        try:
            store = activate_store(
                business=request.user.business,
                store=store,
            )
        except ValidationError as exc:
            messages.error(
                request,
                " ".join(exc.messages),
            )

            return redirect(
                "stores:store_detail",
                pk=store.pk,
            )

        if was_active:
            messages.info(
                request,
                "La tienda ya estaba activa.",
            )
        else:
            messages.success(
                request,
                "Tienda activada correctamente.",
            )

        return redirect(
            "stores:store_detail",
            pk=store.pk,
        )


class StoreSetDefaultView(ManagerOrOwnerRequiredMixin, View):
    """
    Convierte una tienda activa en la predeterminada del negocio.

    El servicio y las constraints garantizan que solo exista una
    tienda predeterminada por negocio.
    """

    def post(self, request, pk):
        store = get_object_or_404(
            Store,
            pk=pk,
            business=request.user.business,
        )

        try:
            store = set_default_store(
                business=request.user.business,
                store=store,
            )
        except ValidationError as exc:
            messages.error(
                request,
                " ".join(exc.messages),
            )

            return redirect(
                "stores:store_detail",
                pk=store.pk,
            )

        messages.success(
            request,
            f"'{store.name}' es ahora la tienda predeterminada.",
        )

        return redirect(
            "stores:store_detail",
            pk=store.pk,
        )


class StoreDeleteView(ManagerOrOwnerRequiredMixin, DeleteView):
    """
    Elimina físicamente una tienda creada por error.

    Para tiendas que ya tengan inventario, ventas u otros datos
    relacionados debe utilizarse la desactivación.
    """

    model = Store
    template_name = "stores/store_confirm_delete.html"
    context_object_name = "store"
    success_url = reverse_lazy("stores:store_list")

    def get_queryset(self):
        """
        Solo permite eliminar tiendas del negocio autenticado.
        """
        queryset = super().get_queryset()

        if self.request.user.is_superuser:
            return queryset

        return queryset.filter(
            business=self.request.user.business,
        )

    def form_valid(self, form):
        """
        Delega el borrado en delete_store().

        No llamamos a super().form_valid(form), porque el servicio ya
        elimina físicamente la tienda.
        """
        store_pk = self.object.pk

        try:
            store_name = delete_store(
                business=self.request.user.business,
                store=self.object,
            )
        except ValidationError as exc:
            messages.error(
                self.request,
                " ".join(exc.messages),
            )

            return redirect(
                "stores:store_detail",
                pk=store_pk,
            )

        messages.success(
            self.request,
            (f"La tienda '{store_name}' ha sido eliminada correctamente."),
        )

        return redirect(self.success_url)
