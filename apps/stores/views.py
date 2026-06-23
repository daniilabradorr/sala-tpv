from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.urls import reverse_lazy, reverse
from django.views import View
from django.views.generic import (
    CreateView,
    DeleteView,
    DetailView,
    ListView,
    UpdateView,
)
from django.shortcuts import redirect, get_object_or_404

from apps.users.mixins import ManagerOrOwnerRequiredMixin
from apps.stores.models import Stores
from apps.stores.forms import StoreCreateForm, StoreUpdateForm


class ListStoresView(ListView):
    model = Stores
    template_name = "stores/list_stores.html"
    context_object_name = "stores"
    paginate_by = 10

    def get_queryset(self):
        queryset = super().get_queryset()
        return queryset.filter(business=self.request.user.business)


class StoreDetailView(DetailView):
    model = Stores
    template_name = "stores/store_detail.html"
    context_object_name = "store"

    def get_queryset(self):
        queryset = super().get_queryset()
        return queryset.filter(business=self.request.user.business)


class StoreCreateView(ManagerOrOwnerRequiredMixin, CreateView):
    model = Stores
    form_class = StoreCreateForm
    template_name = "stores/store_create.html"

    def dispatch(self, request, *args, **kwargs):
        """
        Validamos que el usuario tenga negocio asociado.

        Una tienda no debe crearse suelta, siempre debe pertenecer
        al Business del usuario autenticado.
        """
        if not getattr(request.user, "business_id", None):
            raise PermissionDenied("El usuario no tiene un negocio asociado.")

        return super().dispatch(request, *args, **kwargs)

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["business"] = self.request.user.business
        return kwargs

    def form_valid(self, form):
        """
        Asignamos siempre el negocio desde el usuario autenticado.

        No confiamos en que venga desde el formulario, porque un usuario
        podría intentar enviar otro business por POST.
        """
        form.instance.business = self.request.user.business

        response = super().form_valid(form)

        messages.success(self.request, "Tienda creada exitosamente.")

        return response

    def get_success_url(self):
        return reverse("stores:store_detail", kwargs={"pk": self.object.pk})


class StoreUpdateView(ManagerOrOwnerRequiredMixin, UpdateView):
    model = Stores
    form_class = StoreUpdateForm
    template_name = "stores/store_update.html"

    def get_queryset(self):
        queryset = super().get_queryset()
        return queryset.filter(business=self.request.user.business)

    def form_valid(self, form):
        response = super().form_valid(form)

        messages.success(self.request, "Tienda actualizada exitosamente.")

        return response

    def get_success_url(self):
        return reverse("stores:store_detail", kwargs={"pk": self.object.pk})


class StoreDeactivateView(ManagerOrOwnerRequiredMixin, View):
    """
    Desactiva una tienda sin borrarla de la base de datos.

    Esto mantiene el histórico y evita problemas futuros con ventas,
    cajas, stock, facturas y reportes.
    """

    def post(self, request, pk):
        store = get_object_or_404(
            Stores,
            pk=pk,
            business=request.user.business,
        )

        if not store.is_active:
            messages.info(request, "La tienda ya estaba desactivada.")
            return redirect("stores:store_detail", pk=store.pk)

        store.is_active = False
        store.save()

        messages.success(request, "Tienda desactivada correctamente.")
        return redirect("stores:store_detail", pk=store.pk)


class StoreActivateView(ManagerOrOwnerRequiredMixin, View):
    """
    Reactiva una tienda previamente desactivada.
    """

    def post(self, request, pk):
        store = get_object_or_404(
            Stores,
            pk=pk,
            business=request.user.business,
        )

        if store.is_active:
            messages.info(request, "La tienda ya estaba activa.")
            return redirect("stores:store_detail", pk=store.pk)

        store.is_active = True
        store.save()

        messages.success(request, "Tienda activada correctamente.")
        return redirect("stores:store_detail", pk=store.pk)


class StoreDeleteView(ManagerOrOwnerRequiredMixin, DeleteView):
    """
    Elimina una tienda de la base de datos.

    Recomendación:
    usar esta vista solo para tiendas creadas por error o sin actividad.
    Para tiendas reales con histórico, es mejor desactivar.
    """

    model = Stores
    template_name = "stores/store_confirm_delete.html"
    context_object_name = "store"
    success_url = reverse_lazy("stores:store_list")

    def get_queryset(self):
        queryset = super().get_queryset()
        return queryset.filter(
            business=self.request.user.business,
        )

    def form_valid(self, form):
        store_name = self.object.name

        response = super().form_valid(form)

        messages.success(
            self.request, f"La tienda '{store_name}' ha sido eliminada correctamente."
        )

        return response
