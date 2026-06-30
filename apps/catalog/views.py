from django.views.generic import TemplateView
from apps.catalog.models import Category, Tax, Product
from apps.catalog.forms import (
    CategoryCreateForm,
    CategoryUpdateForm,
    TaxCreateForm,
    TaxUpdateForm,
    ProductCreateForm,
    ProductUpdateForm,
)


class CategoryBasePlaceholderView(TemplateView):
    """
    Vista base temporal para el módulo Category.

    De momento solo sirve para que las urls funcionen
    y podamos crear los templates poco a poco.
    """

    template_name = "Category/placeholder.html"
    page_title = "Catálogo"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["page_title"] = self.page_title
        return context


class CategoryDashboardView(CategoryBasePlaceholderView):
    page_title = "Dashboard del catálogo"


# ==========================
# Categorías
# ==========================


class CategoryListView(CategoryBasePlaceholderView):
    page_title = "Listado de categorías"


class CategoryDetailView(CategoryBasePlaceholderView):
    page_title = "Detalle de categoría"


class CategoryCreateView(CategoryBasePlaceholderView):
    page_title = "Crear categoría"
    model = Category
    form_class = CategoryCreateForm


class CategoryUpdateView(CategoryBasePlaceholderView):
    page_title = "Editar categoría"
    model = Category
    form_class = CategoryUpdateForm


class CategoryActivateView(CategoryBasePlaceholderView):
    page_title = "Activar categoría"
    # hacer el post


class CategoryDeactivateView(CategoryBasePlaceholderView):
    page_title = "Desactivar categoría"
    # hacer el post


# ==========================
# Impuestos
# ==========================


class TaxListView(CategoryBasePlaceholderView):
    page_title = "Listado de impuestos"


class TaxDetailView(CategoryBasePlaceholderView):
    page_title = "Detalle de impuesto"


class TaxCreateView(CategoryBasePlaceholderView):
    page_title = "Crear impuesto"
    model = Tax
    form_class = TaxCreateForm


class TaxUpdateView(CategoryBasePlaceholderView):
    page_title = "Editar impuesto"
    model = Tax
    form_class = TaxUpdateForm


class TaxActivateView(CategoryBasePlaceholderView):
    page_title = "Activar impuesto"
    # post


class TaxDeactivateView(CategoryBasePlaceholderView):
    page_title = "Desactivar impuesto"
    # post


class TaxSetDefaultView(CategoryBasePlaceholderView):
    page_title = "Marcar impuesto por defecto"
    # post


# ==========================
# Productos
# ==========================


class ProductListView(CategoryBasePlaceholderView):
    page_title = "Listado de productos"


class ProductDetailView(CategoryBasePlaceholderView):
    page_title = "Detalle de producto"


class ProductCreateView(CategoryBasePlaceholderView):
    page_title = "Crear producto"
    model = Product
    form_class = ProductCreateForm


class ProductUpdateView(CategoryBasePlaceholderView):
    page_title = "Editar producto"
    model = Product
    form_class = ProductUpdateForm


class ProductActivateView(CategoryBasePlaceholderView):
    page_title = "Activar producto"
    # post


class ProductDeactivateView(CategoryBasePlaceholderView):
    page_title = "Desactivar producto"
    # post
