from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.views import View
from django.views.generic import (
    TemplateView,
    ListView,
    DetailView,
    CreateView,
    UpdateView,
)

from apps.catalog.models import Category, Tax, Product
from apps.catalog.forms import (
    CategoryCreateForm,
    CategoryUpdateForm,
    TaxCreateForm,
    TaxUpdateForm,
    ProductCreateForm,
    ProductUpdateForm,
)
from apps.users.mixins import (
    ManagerOrOwnerRequiredMixin,
    BusinessRequiredMixin,
    BusinessScopedQuerysetMixin,
)


class PageTitleMixin:
    """
    Añade page_title al contexto de los templates.

    Así podemos usar en los templates:
    {{ page_title }}
    """

    page_title = ""

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["page_title"] = self.page_title
        return context


class CatalogDashboardView(
    PageTitleMixin,
    LoginRequiredMixin,
    BusinessRequiredMixin,
    TemplateView,
):
    """
    Dashboard principal del módulo catálogo.

    De momento lo dejamos básico.
    Más adelante se puede mejorar con:
    - productos activos
    - servicios activos
    - categorías activas
    - impuestos activos
    - impuesto por defecto
    - productos sin categoría
    - productos sin impuesto específico
    """

    template_name = "catalog/dashboard.html"
    page_title = "Dashboard del catálogo"


# ==========================
# Categorías
# ==========================


class CategoryListView(
    PageTitleMixin,
    LoginRequiredMixin,
    BusinessScopedQuerysetMixin,
    ListView,
):
    """
    Lista las categorías del negocio del usuario autenticado.

    No hace falta ser manager/owner porque solo estamos consultando datos.
    """

    model = Category
    template_name = "catalog/categories/category_list.html"
    context_object_name = "categories"
    page_title = "Listado de categorías"

    def get_queryset(self):
        return (
            super()
            .get_queryset()
            .select_related("business", "parent")
            .order_by("sort_order", "name")
        )


class CategoryDetailView(
    PageTitleMixin,
    LoginRequiredMixin,
    BusinessScopedQuerysetMixin,
    DetailView,
):
    """
    Muestra el detalle de una categoría concreta.

    BusinessScopedQuerysetMixin evita que alguien pueda ver una categoría
    de otro negocio cambiando el ID en la URL.
    """

    model = Category
    template_name = "catalog/categories/category_detail.html"
    context_object_name = "category"
    page_title = "Detalle de categoría"

    def get_queryset(self):
        return (
            super()
            .get_queryset()
            .select_related("business", "parent")
            .order_by("sort_order", "name")
        )


class CategoryCreateView(
    PageTitleMixin,
    ManagerOrOwnerRequiredMixin,
    BusinessRequiredMixin,
    CreateView,
):
    """
    Crea una categoría nueva.

    Solo manager/owner pueden crear.
    El business no se muestra en el formulario.
    Se asigna automáticamente desde request.user.business.
    """

    model = Category
    form_class = CategoryCreateForm
    template_name = "catalog/categories/category_form.html"
    page_title = "Crear categoría"

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["business"] = self.request.user.business
        return kwargs

    def form_valid(self, form):
        form.instance.business = self.request.user.business

        response = super().form_valid(form)

        messages.success(
            self.request,
            "Categoría creada correctamente.",
        )

        return response

    def get_success_url(self):
        return reverse(
            "catalog:category_detail",
            kwargs={"pk": self.object.pk},
        )


class CategoryUpdateView(
    PageTitleMixin,
    ManagerOrOwnerRequiredMixin,
    BusinessScopedQuerysetMixin,
    UpdateView,
):
    """
    Edita una categoría existente.

    BusinessScopedQuerysetMixin evita editar categorías de otro negocio.
    """

    model = Category
    form_class = CategoryUpdateForm
    template_name = "catalog/categories/category_form.html"
    context_object_name = "category"
    page_title = "Editar categoría"

    def get_queryset(self):
        return super().get_queryset().select_related("business", "parent")

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["business"] = self.request.user.business
        return kwargs

    def form_valid(self, form):
        response = super().form_valid(form)

        messages.success(
            self.request,
            "Categoría actualizada correctamente.",
        )

        return response

    def get_success_url(self):
        return reverse(
            "catalog:category_detail",
            kwargs={"pk": self.object.pk},
        )


class CategoryActivateView(
    ManagerOrOwnerRequiredMixin,
    BusinessRequiredMixin,
    View,
):
    """
    Activa una categoría.

    Solo se ejecuta por POST.
    """

    def post(self, request, *args, **kwargs):
        category = get_object_or_404(
            Category,
            pk=kwargs["pk"],
            business=request.user.business,
        )

        category.is_active = True
        category.save(update_fields=["is_active", "updated_at"])

        messages.success(
            request,
            "Categoría activada correctamente.",
        )

        return redirect(
            "catalog:category_detail",
            pk=category.pk,
        )


class CategoryDeactivateView(
    ManagerOrOwnerRequiredMixin,
    BusinessRequiredMixin,
    View,
):
    """
    Desactiva una categoría.

    No la borramos porque puede tener productos asociados.
    """

    def post(self, request, *args, **kwargs):
        category = get_object_or_404(
            Category,
            pk=kwargs["pk"],
            business=request.user.business,
        )

        category.is_active = False
        category.save(update_fields=["is_active", "updated_at"])

        messages.success(
            request,
            "Categoría desactivada correctamente.",
        )

        return redirect(
            "catalog:category_detail",
            pk=category.pk,
        )


# ==========================
# Impuestos
# ==========================


class TaxListView(
    PageTitleMixin,
    LoginRequiredMixin,
    BusinessScopedQuerysetMixin,
    ListView,
):
    """
    Lista los impuestos/tratamientos fiscales del negocio.

    Solo lectura, por eso basta con estar logueado.
    """

    model = Tax
    template_name = "catalog/taxes/tax_list.html"
    context_object_name = "taxes"
    page_title = "Listado de impuestos"

    def get_queryset(self):
        return (
            super()
            .get_queryset()
            .select_related("business")
            .order_by("-is_default", "name")
        )


class TaxDetailView(
    PageTitleMixin,
    LoginRequiredMixin,
    BusinessScopedQuerysetMixin,
    DetailView,
):
    """
    Muestra el detalle de un impuesto.

    El queryset queda filtrado por business, así que no se pueden ver
    impuestos de otro negocio cambiando la URL.
    """

    model = Tax
    template_name = "catalog/taxes/tax_detail.html"
    context_object_name = "tax"
    page_title = "Detalle de impuesto"

    def get_queryset(self):
        return super().get_queryset().select_related("business")


class TaxCreateView(
    PageTitleMixin,
    ManagerOrOwnerRequiredMixin,
    BusinessRequiredMixin,
    CreateView,
):
    """
    Crea un impuesto/tratamiento fiscal.

    No se permite elegir business desde el form.
    El business se asigna automáticamente.
    """

    model = Tax
    form_class = TaxCreateForm
    template_name = "catalog/taxes/tax_form.html"
    page_title = "Crear impuesto"

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["business"] = self.request.user.business
        return kwargs

    def form_valid(self, form):
        form.instance.business = self.request.user.business

        response = super().form_valid(form)

        messages.success(
            self.request,
            "Impuesto creado correctamente.",
        )

        return response

    def get_success_url(self):
        return reverse(
            "catalog:tax_detail",
            kwargs={"pk": self.object.pk},
        )


class TaxUpdateView(
    PageTitleMixin,
    ManagerOrOwnerRequiredMixin,
    BusinessScopedQuerysetMixin,
    UpdateView,
):
    """
    Edita un impuesto existente.

    Solo manager/owner.
    El impuesto debe pertenecer al business del usuario.
    """

    model = Tax
    form_class = TaxUpdateForm
    template_name = "catalog/taxes/tax_form.html"
    context_object_name = "tax"
    page_title = "Editar impuesto"

    def get_queryset(self):
        return super().get_queryset().select_related("business")

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["business"] = self.request.user.business
        return kwargs

    def form_valid(self, form):
        response = super().form_valid(form)

        messages.success(
            self.request,
            "Impuesto actualizado correctamente.",
        )

        return response

    def get_success_url(self):
        return reverse(
            "catalog:tax_detail",
            kwargs={"pk": self.object.pk},
        )


class TaxActivateView(
    ManagerOrOwnerRequiredMixin,
    BusinessRequiredMixin,
    View,
):
    """
    Activa un impuesto.

    Solo se ejecuta por POST.
    """

    def post(self, request, *args, **kwargs):
        tax = get_object_or_404(
            Tax,
            pk=kwargs["pk"],
            business=request.user.business,
        )

        tax.is_active = True
        tax.save(update_fields=["is_active", "updated_at"])

        messages.success(
            request,
            "Impuesto activado correctamente.",
        )

        return redirect(
            "catalog:tax_detail",
            pk=tax.pk,
        )


class TaxDeactivateView(
    ManagerOrOwnerRequiredMixin,
    BusinessRequiredMixin,
    View,
):
    """
    Desactiva un impuesto.

    Regla importante:
    No permitimos desactivar el impuesto por defecto.
    El negocio debe tener siempre un impuesto por defecto usable.
    """

    def post(self, request, *args, **kwargs):
        tax = get_object_or_404(
            Tax,
            pk=kwargs["pk"],
            business=request.user.business,
        )

        if tax.is_default:
            messages.error(
                request,
                "No puedes desactivar el impuesto por defecto. "
                "Primero marca otro impuesto como predeterminado.",
            )

            return redirect(
                "catalog:tax_detail",
                pk=tax.pk,
            )

        tax.is_active = False
        tax.save(update_fields=["is_active", "updated_at"])

        messages.success(
            request,
            "Impuesto desactivado correctamente.",
        )

        return redirect(
            "catalog:tax_detail",
            pk=tax.pk,
        )


class TaxSetDefaultView(
    ManagerOrOwnerRequiredMixin,
    BusinessRequiredMixin,
    View,
):
    """
    Marca un impuesto como impuesto por defecto del negocio.

    Usamos transaction.atomic() porque hay dos operaciones relacionadas:
    1. Quitar is_default al resto de impuestos del negocio.
    2. Marcar este impuesto como is_default=True.

    Así evitamos estados intermedios raros.
    """

    def post(self, request, *args, **kwargs):
        tax = get_object_or_404(
            Tax,
            pk=kwargs["pk"],
            business=request.user.business,
        )

        with transaction.atomic():
            Tax.objects.filter(
                business=request.user.business,
                is_default=True,
            ).exclude(
                pk=tax.pk,
            ).update(
                is_default=False,
            )

            tax.is_default = True
            tax.is_active = True
            tax.save(update_fields=["is_default", "is_active", "updated_at"])

        messages.success(
            request,
            "Impuesto marcado como predeterminado correctamente.",
        )

        return redirect(
            "catalog:tax_detail",
            pk=tax.pk,
        )


# ==========================
# Productos
# ==========================


class ProductListView(
    PageTitleMixin,
    LoginRequiredMixin,
    BusinessScopedQuerysetMixin,
    ListView,
):
    """
    Lista productos y servicios del negocio.

    Solo lectura.
    """

    model = Product
    template_name = "catalog/products/product_list.html"
    context_object_name = "products"
    page_title = "Listado de productos"

    def get_queryset(self):
        return (
            super()
            .get_queryset()
            .select_related("business", "category", "tax")
            .order_by(
                "category__sort_order",
                "category__name",
                "sort_order",
                "name",
            )
        )


class ProductDetailView(
    PageTitleMixin,
    LoginRequiredMixin,
    BusinessScopedQuerysetMixin,
    DetailView,
):
    """
    Muestra el detalle de un producto/servicio.

    El objeto queda protegido por business.
    """

    model = Product
    template_name = "catalog/products/product_detail.html"
    context_object_name = "product"
    page_title = "Detalle de producto"

    def get_queryset(self):
        return super().get_queryset().select_related("business", "category", "tax")


class ProductCreateView(
    PageTitleMixin,
    ManagerOrOwnerRequiredMixin,
    BusinessRequiredMixin,
    CreateView,
):
    """
    Crea un producto o servicio.

    El business se asigna automáticamente.
    El form recibe business para poder filtrar:
    - categorías del negocio
    - impuestos activos del negocio
    """

    model = Product
    form_class = ProductCreateForm
    template_name = "catalog/products/product_form.html"
    page_title = "Crear producto"

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["business"] = self.request.user.business
        return kwargs

    def form_valid(self, form):
        form.instance.business = self.request.user.business

        response = super().form_valid(form)

        messages.success(
            self.request,
            "Producto creado correctamente.",
        )

        return response

    def get_success_url(self):
        return reverse(
            "catalog:product_detail",
            kwargs={"pk": self.object.pk},
        )


class ProductUpdateView(
    PageTitleMixin,
    ManagerOrOwnerRequiredMixin,
    BusinessScopedQuerysetMixin,
    UpdateView,
):
    """
    Edita un producto o servicio.

    BusinessScopedQuerysetMixin evita editar productos de otro negocio.
    """

    model = Product
    form_class = ProductUpdateForm
    template_name = "catalog/products/product_form.html"
    context_object_name = "product"
    page_title = "Editar producto"

    def get_queryset(self):
        return super().get_queryset().select_related("business", "category", "tax")

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["business"] = self.request.user.business
        return kwargs

    def form_valid(self, form):
        response = super().form_valid(form)

        messages.success(
            self.request,
            "Producto actualizado correctamente.",
        )

        return response

    def get_success_url(self):
        return reverse(
            "catalog:product_detail",
            kwargs={"pk": self.object.pk},
        )


class ProductActivateView(
    ManagerOrOwnerRequiredMixin,
    BusinessRequiredMixin,
    View,
):
    """
    Activa un producto o servicio.

    Solo se ejecuta por POST.
    """

    def post(self, request, *args, **kwargs):
        product = get_object_or_404(
            Product,
            pk=kwargs["pk"],
            business=request.user.business,
        )

        product.is_active = True
        product.save(update_fields=["is_active", "updated_at"])

        messages.success(
            request,
            "Producto activado correctamente.",
        )

        return redirect(
            "catalog:product_detail",
            pk=product.pk,
        )


class ProductDeactivateView(
    ManagerOrOwnerRequiredMixin,
    BusinessRequiredMixin,
    View,
):
    """
    Desactiva un producto o servicio.

    No lo borramos porque puede aparecer en ventas, tickets,
    facturas o documentos históricos.
    """

    def post(self, request, *args, **kwargs):
        product = get_object_or_404(
            Product,
            pk=kwargs["pk"],
            business=request.user.business,
        )

        product.is_active = False
        product.save(update_fields=["is_active", "updated_at"])

        messages.success(
            request,
            "Producto desactivado correctamente.",
        )

        return redirect(
            "catalog:product_detail",
            pk=product.pk,
        )
