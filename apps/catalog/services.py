"""
Servicios del módulo catalog.

Este archivo contiene lógica de negocio relacionada con el catálogo que no debe
vivir directamente en las views.

Ejemplos:
- resolver qué impuesto aplica a un producto
- activar/desactivar entidades del catálogo
- calcular precios derivados
- preparar datos reutilizables para ventas o facturación

Las views deben coordinar la petición HTTP.
Los services deben contener reglas de negocio.
"""

from apps.catalog.models import Tax, Product


class ProductTaxResolutionError(Exception):
    """
    Error lanzado cuando no se puede resolver un impuesto válido
    para un producto.
    """

    pass


def resolve_product_tax(product: Product) -> Tax:
    """
    Resuelve qué impuesto debe aplicarse a un producto.

    Prioridad:
    1. Si el producto tiene un impuesto específico y está activo,
       devuelve ese impuesto.

    2. Si el producto tiene un impuesto específico pero está inactivo,
       lanza un error controlado.

    3. Si el producto no tiene impuesto específico,
       busca el impuesto por defecto activo del mismo negocio.

    4. Si no existe impuesto específico ni impuesto por defecto activo,
       lanza un error controlado.

    Args:
        product: instancia de Product.

    Returns:
        Tax: impuesto aplicable al producto.

    Raises:
        ProductTaxResolutionError: si no existe un impuesto válido.
    """

    if not getattr(product, "business_id", None):
        raise ProductTaxResolutionError(
            "No se puede resolver el impuesto porque el producto no tiene negocio asociado."
        )

    if product.tax_id:
        tax = product.tax

        if not tax.is_active:
            raise ProductTaxResolutionError(
                f"El impuesto '{tax.name}' asignado al producto '{product.name}' está inactivo."
            )

        return tax

    default_tax = Tax.objects.filter(
        business_id=product.business_id,
        is_default=True,
        is_active=True,
    ).first()

    if default_tax:
        return default_tax

    raise ProductTaxResolutionError(
        f"No existe un impuesto por defecto activo para el negocio del producto '{product.name}'."
    )
