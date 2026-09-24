"""Consultas de lectura del catálogo, siempre aisladas por negocio."""

from django.db.models import Q

from apps.catalog.models import Category, Product


def get_products_for_catalog(business, filters=None):
    filters = filters or {}
    queryset = Product.objects.filter(business=business).select_related(
        "category", "tax"
    )
    search = filters.get("q", "").strip()
    if search:
        queryset = queryset.filter(
            Q(name__icontains=search)
            | Q(sku__icontains=search)
            | Q(barcode__icontains=search)
        )
    category = filters.get("category")
    if category and category.isdigit():
        queryset = queryset.filter(category_id=category)
    if filters.get("type") == "physical":
        queryset = queryset.filter(is_service=False)
    elif filters.get("type") == "service":
        queryset = queryset.filter(is_service=True)
    if filters.get("status") == "active":
        queryset = queryset.filter(is_active=True)
    elif filters.get("status") == "inactive":
        queryset = queryset.filter(is_active=False)
    if filters.get("stock") == "tracked":
        queryset = queryset.filter(track_stock=True)
    elif filters.get("stock") == "untracked":
        queryset = queryset.filter(track_stock=False)
    return queryset.order_by(
        "category__sort_order", "category__name", "sort_order", "name"
    )


def get_category_rows(business, search=""):
    """Devuelve una jerarquía plana presentable, sin recursión en templates."""
    categories = list(
        Category.objects.filter(business=business)
        .select_related("parent")
        .order_by("sort_order", "name")
    )
    by_parent = {}
    for category in categories:
        by_parent.setdefault(category.parent_id, []).append(category)

    rows = []

    def visit(category, depth, path):
        current_path = [*path, category.name]
        rows.append(
            {"category": category, "depth": depth, "path": " / ".join(current_path)}
        )
        for child in by_parent.get(category.pk, []):
            visit(child, depth + 1, current_path)

    for root in by_parent.get(None, []):
        visit(root, 0, [])
    # Include malformed/orphaned trees defensively.
    seen = {row["category"].pk for row in rows}
    for category in categories:
        if category.pk not in seen:
            visit(category, 0, [])
    if search:
        needle = search.casefold()
        rows = [row for row in rows if needle in row["category"].name.casefold()]
    return rows
