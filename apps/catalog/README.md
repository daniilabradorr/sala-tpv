# Módulo `catalog`

## Versión del módulo

**Versión actual:** `0.1.0`
**Estado:** En desarrollo
**Rama de trabajo:** pendiente de merge a `develop`
**Responsabilidad principal:** gestión de catálogo comercial y fiscal del TPV.

---

# 1. Qué es el módulo `catalog`

El módulo `catalog` es el encargado de gestionar la configuración base de los productos, servicios, categorías e impuestos que podrá usar el TPV.

Este módulo **no vende**, **no factura**, **no descuenta stock** y **no envía información fiscal a Verifactu/AEAT**.

Su responsabilidad es preparar la información maestra que otros módulos utilizarán más adelante.

Por ejemplo:

```txt
catalog
    define productos
    define servicios
    define categorías
    define impuestos
    define precios base sin IVA
    Tax representa una plantilla fiscal reutilizable dentro del negocio. No genera facturas ni envía datos fiscales; solo guarda la configuración fiscal que podrán usar los productos y, más adelante, los módulos de ventas y facturación.
```

Luego otros módulos usarán estos datos:

```txt
sales
    usará Product para crear líneas de venta

billing
    copiará datos de Product y Tax en documentos fiscales

inventory
    usará Product para controlar stock

verifactu / fiscal
    usará los datos fiscales copiados desde Tax
```

---

# 2. Qué NO debe hacer este módulo

Es muy importante mantener los límites del módulo.

`catalog` no debe encargarse de:

```txt
- Crear ventas.
- Crear tickets.
- Crear facturas.
- Enviar datos a Verifactu.
- Enviar datos a AEAT.
- Descontar stock.
- Crear movimientos de inventario.
- Guardar históricos fiscales definitivos.
- Registrar pagos.
- Gestionar caja.
```

Esto es importante porque `catalog` representa la configuración actual del negocio.

Una venta o factura futura no debe depender de que el producto cambie después.

Ejemplo:

```txt
Hoy:
    Producto: Coca-Cola
    Precio base: 2.00 €
    IVA: 21%

Mañana:
    Producto: Coca-Cola
    Precio base: 2.50 €
    IVA: 21%

Una venta hecha hoy debe conservar 2.00 €, aunque mañana cambie el producto.
```

Por eso más adelante las ventas y facturas copiarán los datos relevantes en sus propias tablas históricas.

---

# 3. Responsabilidad general del módulo

El módulo contiene tres conceptos principales:

```txt
Category
    Agrupa productos y servicios.

Tax
    Define tratamientos fiscales reutilizables.

Product
    Define productos físicos y servicios vendibles.
```

Cada uno pertenece siempre a un `Business`.

Esto es una regla central del proyecto:

```txt
Todo dato de negocio debe pertenecer a un Business.
```

Por tanto, en `catalog` ningún usuario debe poder ver, crear, editar, activar o desactivar información de otro negocio.

---

# 4. Modelos principales

## 4.1. `Category`

Representa una categoría comercial dentro del catálogo.

Ejemplos:

```txt
Bebidas
Comida
Postres
Servicios
Menú del día
```

Sirve para ordenar y agrupar productos en el TPV.

### Responsabilidades de `Category`

```txt
- Agrupar productos.
- Permitir jerarquía mediante parent.
- Ordenar visualmente categorías con sort_order.
- Activar/desactivar categorías.
- Generar slug automático si no se informa.
- Garantizar que el slug sea único dentro del mismo Business.
```

### Campos importantes

```txt
business
    Negocio al que pertenece la categoría.

name
    Nombre visible de la categoría.

slug
    Identificador legible para URLs o uso interno.

parent
    Categoría padre opcional.

sort_order
    Orden visual de la categoría.

is_active
    Indica si la categoría está activa.
```

### Reglas de negocio de `Category`

Una categoría no puede ser padre de sí misma.

```txt
Categoría Bebidas
    parent = Bebidas  -> no permitido
```

Una categoría padre debe pertenecer al mismo negocio.

```txt
Negocio A
    Categoría Bebidas

Negocio B
    Categoría Comida

No se puede hacer:
    Bebidas.parent = Comida
```

El `slug` debe ser único por negocio.

```txt
Negocio A:
    bebidas

Negocio B:
    bebidas

Esto sí está permitido porque son negocios distintos.
```

---

## 4.2. `Tax`

Representa una configuración fiscal reusable.

Ejemplos:

```txt
IVA 21%
IVA 10%
IVA 4%
Exento artículo 20
No sujeto
IVA 21% con recargo de equivalencia
```

Este modelo es muy importante porque contiene la base fiscal que después se copiará a ventas, facturas y documentos Verifactu.

### Responsabilidades de `Tax`

```txt
- Definir tipo de impuesto.
- Definir porcentaje de impuesto.
- Definir clave de régimen fiscal.
- Definir calificación de operación.
- Definir operación exenta si aplica.
- Definir recargo de equivalencia si aplica.
- Permitir un impuesto por defecto por Business.
- Validar coherencia fiscal básica.
```

### Campos importantes

```txt
business
    Negocio al que pertenece el impuesto.

name
    Nombre visible del impuesto.

code
    Código interno único por negocio.

tax_type
    Tipo de impuesto. Por ejemplo IVA, IGIC, IPSI u otro.

rate
    Porcentaje del impuesto.

clave_regimen
    Clave de régimen fiscal.

calificacion_operacion
    Calificación de la operación.

operacion_exenta
    Código de operación exenta si aplica.

has_equivalence_surcharge
    Indica si aplica recargo de equivalencia.

equivalence_surcharge_rate
    Porcentaje del recargo de equivalencia.

is_default
    Indica si es el impuesto por defecto del negocio.

is_active
    Indica si el impuesto está activo.
```

---

# 5. Reglas fiscales implementadas en `Tax`

Este punto es crítico.

`Tax` no es una factura.
`Tax` es una plantilla fiscal.

Pero debe validar ciertas reglas para evitar configuraciones incoherentes.

---

## 5.1. El porcentaje no puede ser negativo

No tiene sentido fiscal tener:

```txt
IVA -21%
```

Por eso `rate` debe ser mayor o igual que cero.

---

## 5.2. Una operación exenta debe tener tipo 0%

Si se informa `operacion_exenta`, entonces `rate` debe ser `0.00`.

Ejemplo válido:

```txt
name = Exento artículo 20
rate = 0.00
operacion_exenta = E1
```

Ejemplo inválido:

```txt
name = Exento artículo 20
rate = 21.00
operacion_exenta = E1
```

Una operación no puede ser exenta y a la vez llevar IVA del 21%.

---

## 5.3. Una operación exenta no debe tener `calificacion_operacion`

Si existe `operacion_exenta`, el modelo debe limpiar la calificación de operación.

Ejemplo:

```txt
operacion_exenta = E1
calificacion_operacion = None
```

Esto evita mezclar dos conceptos fiscales distintos.

---

## 5.4. Operaciones no sujetas `N1` / `N2`

Si la operación es no sujeta:

```txt
calificacion_operacion = N1
calificacion_operacion = N2
```

entonces el porcentaje también debe ser `0.00`.

Ejemplo válido:

```txt
calificacion_operacion = N1
rate = 0.00
```

Ejemplo inválido:

```txt
calificacion_operacion = N1
rate = 21.00
```

---

## 5.5. Operaciones sujetas normales

Para una venta normal con IVA, lo habitual es:

```txt
clave_regimen = 01
calificacion_operacion = S1
rate = 21.00 / 10.00 / 4.00
```

Si la operación no está exenta y no se informa calificación, el modelo puede completar `S1`.

---

## 5.6. Recargo de equivalencia

Si `has_equivalence_surcharge` está marcado, debe existir `equivalence_surcharge_rate`.

Ejemplo válido:

```txt
has_equivalence_surcharge = True
equivalence_surcharge_rate = 5.20
```

Ejemplo inválido:

```txt
has_equivalence_surcharge = True
equivalence_surcharge_rate = None
```

---

## 5.7. No puede haber porcentaje de recargo si el recargo no está activo

Ejemplo inválido:

```txt
has_equivalence_surcharge = False
equivalence_surcharge_rate = 5.20
```

Esto sería incoherente.

---

## 5.8. Recargo de equivalencia y clave de régimen

Cuando hay recargo de equivalencia, el modelo fuerza:

```txt
clave_regimen = 18
```

Esto centraliza la regla fiscal y evita que las vistas o formularios tengan que acordarse de hacerlo.

---

## 5.9. Solo puede haber un impuesto por defecto por negocio

Cada negocio puede tener un único `Tax` con:

```txt
is_default = True
```

Esto permite resolver el impuesto de un producto cuando el producto no tiene impuesto específico.

Regla:

```txt
Producto con tax específico
    usa ese tax

Producto sin tax específico
    usa el Tax por defecto del Business

Business sin Tax por defecto
    error controlado
```

---

# 6. Modelo `Product`

Representa un producto físico o un servicio vendible.

Ejemplos de productos físicos:

```txt
Coca-Cola 500ml
Café con leche
Bocadillo de lomo
Camiseta
```

Ejemplos de servicios:

```txt
Servicio de instalación
Mano de obra
Consultoría
Reparación
```

---

## 6.1. Responsabilidades de `Product`

```txt
- Definir nombre comercial del producto.
- Definir SKU interno.
- Definir código de barras si aplica.
- Definir categoría.
- Definir impuesto específico opcional.
- Definir precio base sin IVA.
- Definir coste.
- Definir unidad de venta.
- Diferenciar producto físico y servicio.
- Controlar si gestiona stock.
- Permitir ordenar productos dentro de una categoría.
- Activar/desactivar productos.
```

---

## 6.2. Campos importantes

```txt
business
    Negocio al que pertenece el producto.

category
    Categoría comercial del producto.

tax
    Impuesto específico opcional.

name
    Nombre visible del producto.

sku
    Código interno del producto.

barcode
    Código de barras o código escaneable.

base_price
    Precio base sin IVA.

cost_price
    Coste interno.

unit
    Unidad de venta.

sort_order
    Orden visual dentro de su categoría.

track_stock
    Indica si el producto controla stock.

is_service
    Indica si es servicio.

is_active
    Indica si está activo.
```

---

# 7. Regla crítica: `base_price` siempre es sin IVA

Esta es una de las reglas más importantes del módulo.

```txt
Product.base_price = precio sin IVA
```

No debe guardar el precio final con IVA incluido.

Ejemplo:

```txt
base_price = 10.00
IVA = 21%

Precio con IVA = 12.10
```

El precio con IVA se calcula, pero no se guarda como precio principal en `Product`.

Esto es importante porque después:

```txt
SaleLine
    copiará precio aplicado en el momento de la venta.

BillingDocumentLine
    copiará precio y datos fiscales para la factura.

BillingTaxBreakdown
    guardará desglose fiscal agrupado.

Verifactu
    enviará importes calculados desde los documentos fiscales.
```

---

# 8. Regla crítica: `Product` es configuración actual, no histórico

`Product` representa el estado actual del catálogo.

Si mañana cambia el precio, el producto cambia.

Pero una venta antigua no debe cambiar.

Por eso en el futuro:

```txt
Product
    configuración actual

SaleLine
    snapshot comercial de la venta

BillingDocumentLine
    snapshot fiscal de la factura

BillingTaxBreakdown
    agrupación fiscal para factura / Verifactu
```

---

# 9. Productos físicos vs servicios

Un producto físico puede controlar stock.

```txt
is_service = False
track_stock = True
barcode = PRD000001
```

Un servicio no debe controlar stock ni tener código de barras físico.

```txt
is_service = True
track_stock = False
barcode = None
```

Si un producto se marca como servicio, el modelo debe forzar:

```txt
track_stock = False
barcode = None
```

Esto evita incoherencias.

---

# 10. Activar/desactivar en vez de borrar

En este módulo no se recomienda borrar datos.

Se usa:

```txt
is_active = True
is_active = False
```

Razón:

Un producto, impuesto o categoría puede haber sido usado en ventas, tickets o facturas.

Si se borra físicamente, se puede romper el histórico.

Por eso:

```txt
Borrar producto
    no recomendado

Desactivar producto
    recomendado
```

Lo mismo para categorías e impuestos.

---

# 11. Estructura de archivos del módulo

La estructura recomendada del módulo es:

```txt
apps/catalog/
├── __init__.py
├── admin.py
├── apps.py
├── forms.py
├── models.py
├── urls.py
├── views.py
├── README.md
├── migrations/
│   └── ...
└── tests/
    ├── __init__.py
    ├── factories.py
    ├── unit/
    │   ├── __init__.py
    │   ├── test_models.py
    │   ├── test_forms.py
    │   └── test_urls.py
    └── integration/
        ├── __init__.py
        └── test_views.py
```

---

# 12. Responsabilidad de cada archivo

## 12.1. `apps/catalog/apps.py`

Archivo de configuración de la app Django.

Responsabilidades:

```txt
- Registrar la aplicación catalog.
- Definir default_auto_field.
- Definir verbose_name para Django Admin.
```

Ejemplo:

```python
from django.apps import AppConfig


class CatalogConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.catalog"
    verbose_name = "Catálogo"
```

Este archivo no debe contener lógica de negocio.

---

## 12.2. `apps/catalog/models.py`

Es el archivo más importante del módulo.

Contiene los modelos:

```txt
Category
Tax
Product
```

Responsabilidades:

```txt
- Definir estructura de base de datos.
- Definir relaciones entre modelos.
- Definir constraints.
- Definir índices.
- Definir validaciones internas.
- Definir normalizaciones.
- Definir generación automática de slug, SKU, code o barcode.
```

Este archivo debe proteger las reglas más importantes aunque alguien use el ORM directamente.

Ejemplo:

```txt
Aunque una vista esté mal hecha,
Product.clean() debe impedir asignar un tax de otro business.
```

Por eso las validaciones críticas deben vivir aquí y no solo en los formularios.

---

## 12.3. `apps/catalog/admin.py`

Configura cómo se ven los modelos en Django Admin.

Responsabilidades:

```txt
- Registrar Category, Tax y Product.
- Mejorar list_display.
- Añadir filtros.
- Añadir búsqueda.
- Añadir orden.
- Añadir autocomplete_fields.
- Añadir readonly_fields.
```

Este archivo sirve para administración interna, depuración y gestión manual.

No debe contener lógica de negocio crítica.

Ejemplo:

```txt
admin.py puede facilitar editar un producto,
pero la validación de precio negativo debe estar en models.py.
```

---

## 12.4. `apps/catalog/forms.py`

Contiene los formularios usados por las vistas HTML.

Formularios esperados:

```txt
CategoryCreateForm
CategoryUpdateForm

TaxCreateForm
TaxUpdateForm

ProductCreateForm
ProductUpdateForm
```

Responsabilidades:

```txt
- Definir qué campos se muestran al usuario.
- Excluir campos peligrosos como business.
- Excluir is_active en creación.
- Excluir is_default de Tax para gestionarlo con una vista específica.
- Filtrar opciones por business.
- Pasar business a la instancia.
- Normalizar algunos datos de entrada.
```

---

# 13. Regla importante de formularios: el usuario nunca elige `business`

Ningún formulario debe exponer:

```txt
business
```

El negocio se asigna siempre desde:

```python
request.user.business
```

Esto evita que alguien manipule el POST y cree datos en otro negocio.

Ejemplo de ataque que debe ignorarse:

```txt
POST:
    name = Coca-Cola
    business = 999
```

La vista debe ignorarlo y usar:

```txt
request.user.business
```

---

# 14. Formularios de creación

En creación, normalmente no se muestran campos de estado interno.

Por ejemplo:

```txt
CategoryCreateForm
    no muestra business
    no muestra is_active

TaxCreateForm
    no muestra business
    no muestra is_default
    no muestra is_active

ProductCreateForm
    no muestra business
    no muestra is_active
    no muestra track_stock
```

Razón:

```txt
is_active
    por defecto True

track_stock
    por defecto True en modelo
    si es servicio, el modelo lo fuerza a False

is_default
    se gestiona con TaxSetDefaultView
```

---

# 15. Formularios de edición

En edición sí tiene sentido mostrar más campos.

```txt
CategoryUpdateForm
    muestra is_active

TaxUpdateForm
    muestra is_active
    no muestra is_default

ProductUpdateForm
    muestra is_active
    muestra track_stock
```

`is_default` no se muestra ni en crear ni en editar impuestos porque cambiar el impuesto por defecto requiere una acción de negocio especial:

```txt
TaxSetDefaultView
```

---

## 12.5. `apps/catalog/views.py`

Contiene las vistas HTML del módulo.

Responsabilidades:

```txt
- Mostrar listados.
- Mostrar detalles.
- Crear objetos.
- Editar objetos.
- Activar/desactivar objetos.
- Marcar impuesto por defecto.
- Aplicar permisos.
- Filtrar por business.
- Pasar business a los formularios.
- Redirigir después de operaciones correctas.
- Mostrar mensajes de éxito/error.
```

---

# 16. Patrón de permisos en views

## 16.1. Vistas de lectura

Para listar o ver detalle basta con que el usuario esté logueado y tenga business.

```txt
ListView
DetailView
```

Ejemplo:

```txt
CategoryListView
CategoryDetailView
TaxListView
TaxDetailView
ProductListView
ProductDetailView
```

Estas vistas usan:

```txt
LoginRequiredMixin
BusinessScopedQuerysetMixin
```

El objetivo es:

```txt
- El usuario debe iniciar sesión.
- Solo puede ver datos de su negocio.
```

---

## 16.2. Vistas de escritura

Para crear, editar, activar, desactivar o marcar por defecto hace falta ser owner o manager.

```txt
CreateView
UpdateView
View con POST
```

Estas vistas usan:

```txt
ManagerOrOwnerRequiredMixin
BusinessRequiredMixin
```

o:

```txt
ManagerOrOwnerRequiredMixin
BusinessScopedQuerysetMixin
```

según el caso.

---

# 17. Diferencia entre `BusinessRequiredMixin` y `BusinessScopedQuerysetMixin`

## `BusinessRequiredMixin`

Valida que el usuario tenga un negocio asociado.

Se usa cuando todavía no existe un objeto que filtrar.

Ejemplos:

```txt
CatalogDashboardView
CategoryCreateView
TaxCreateView
ProductCreateView
CategoryActivateView
ProductDeactivateView
TaxSetDefaultView
```

---

## `BusinessScopedQuerysetMixin`

Filtra el queryset por el negocio del usuario.

Se usa cuando la vista trabaja con objetos existentes.

Ejemplos:

```txt
CategoryListView
CategoryDetailView
CategoryUpdateView
TaxListView
TaxDetailView
TaxUpdateView
ProductListView
ProductDetailView
ProductUpdateView
```

Esto evita accesos cruzados entre negocios.

Ejemplo:

```txt
Usuario del Negocio A intenta entrar en:
/catalog/products/999/

Pero el producto 999 pertenece al Negocio B.

Resultado:
    404
```

---

# 18. `apps/catalog/urls.py`

Define las rutas del módulo.

Responsabilidades:

```txt
- Mapear URLs a views.
- Definir app_name = "catalog".
- Mantener nombres de rutas estables.
```

Nombres esperados:

```txt
catalog:dashboard

catalog:category_list
catalog:category_create
catalog:category_detail
catalog:category_update
catalog:category_activate
catalog:category_deactivate

catalog:tax_list
catalog:tax_create
catalog:tax_detail
catalog:tax_update
catalog:tax_activate
catalog:tax_deactivate
catalog:tax_set_default

catalog:product_list
catalog:product_create
catalog:product_detail
catalog:product_update
catalog:product_activate
catalog:product_deactivate
```

Estos nombres se usan en:

```txt
templates
redirect()
reverse()
tests
```

Por eso cambiar un nombre de URL es un cambio delicado.

---

# 19. `apps/catalog/tests/factories.py`

Contiene funciones auxiliares para crear datos en tests.

Responsabilidades:

```txt
- Crear categorías de prueba.
- Crear impuestos de prueba.
- Crear productos de prueba.
- Reducir duplicación en tests.
```

Ejemplos:

```txt
create_category()
create_tax()
create_product()
```

Este archivo no se usa en producción.

Solo sirve para tests.

---

# 20. `apps/catalog/tests/unit/test_models.py`

Tests unitarios de modelos.

Responsabilidades:

```txt
- Validar reglas de Category.
- Validar reglas fiscales de Tax.
- Validar reglas de Product.
- Validar constraints.
- Validar generación automática de campos.
```

Debe cubrir como mínimo:

```txt
Category:
    - __str__
    - slug automático
    - slug único por business
    - parent del mismo business
    - no parent a sí misma

Tax:
    - code automático
    - code único por business
    - un default por business
    - rate no negativo
    - exento requiere rate 0
    - exento limpia calificacion_operacion
    - N1/N2 requiere rate 0
    - recargo requiere porcentaje
    - porcentaje de recargo requiere flag
    - recargo fuerza clave_regimen 18

Product:
    - __str__
    - SKU automático
    - barcode automático en producto físico
    - servicio no controla stock
    - servicio no tiene barcode
    - precio base no negativo
    - coste no negativo
    - categoría del mismo business
    - tax del mismo business
    - tax activo
    - base_price representa precio sin IVA
```

---

# 21. `apps/catalog/tests/unit/test_forms.py`

Tests unitarios de formularios.

Responsabilidades:

```txt
- Validar que los forms aceptan datos correctos.
- Validar que los forms rechazan datos incorrectos.
- Validar que business no se expone.
- Validar que los querysets se filtran por business.
- Validar que CreateForm y UpdateForm exponen campos distintos.
```

Debe cubrir como mínimo:

```txt
CategoryCreateForm:
    - válido con datos correctos
    - asigna business a instance
    - no expone business
    - no expone is_active
    - parent solo del mismo business

CategoryUpdateForm:
    - expone is_active
    - no expone business
    - excluye a sí misma como parent

TaxCreateForm:
    - válido con datos fiscales correctos
    - asigna business
    - no expone business
    - no expone is_default
    - no expone is_active

TaxUpdateForm:
    - expone is_active
    - no expone business
    - no expone is_default

ProductCreateForm:
    - válido con datos correctos
    - asigna business
    - no expone business
    - no expone is_active
    - no expone track_stock
    - category filtrada por business
    - tax filtrado por business
    - tax activo

ProductUpdateForm:
    - expone is_active
    - expone track_stock
    - no expone business
```

---

# 22. `apps/catalog/tests/unit/test_urls.py`

Tests unitarios de URLs.

Responsabilidades:

```txt
- Comprobar que cada reverse funciona.
- Comprobar que cada URL resuelve a la view correcta.
```

Estos tests protegen contra errores como:

```txt
Cambiar el nombre de una ruta.
Borrar una ruta sin querer.
Importar una view equivocada.
```

Ejemplo:

```python
url = reverse("catalog:product_detail", kwargs={"pk": 1})
self.assertEqual(resolve(url).func.view_class, ProductDetailView)
```

---

# 23. `apps/catalog/tests/integration/test_views.py`

Tests de integración de vistas.

Responsabilidades:

```txt
- Probar login.
- Probar permisos.
- Probar filtros por business.
- Probar creación real en BD.
- Probar edición real en BD.
- Probar activar/desactivar.
- Probar TaxSetDefaultView.
- Probar que business manipulado por POST se ignora.
```

Debe cubrir como mínimo:

```txt
Dashboard:
    - requiere login
    - funciona con usuario logueado con business

Category:
    - lista solo categorías del negocio
    - detalle no permite acceso cross-business
    - owner puede crear
    - cashier no puede crear
    - manager puede editar
    - owner puede activar/desactivar

Tax:
    - lista solo impuestos del negocio
    - owner puede crear
    - cashier no puede crear
    - set_default cambia default
    - set_default activa el impuesto
    - no se puede desactivar el impuesto por defecto
    - se puede activar/desactivar un impuesto no default

Product:
    - lista solo productos del negocio
    - detalle no permite acceso cross-business
    - owner puede crear
    - cashier no puede crear
    - manager puede editar
    - owner puede activar/desactivar
```

---

# 24. Migraciones

Las migraciones viven en:

```txt
apps/catalog/migrations/
```

Responsabilidades:

```txt
- Crear tablas.
- Añadir campos.
- Añadir constraints.
- Añadir índices.
- Registrar cambios en base de datos.
```

Regla importante:

```txt
Nunca editar una migración ya mergeada y compartida.
```

Si el cambio ya llegó a `develop` o `main`, se crea una migración nueva.

---

# 25. Índices y rendimiento

El módulo debe tener índices pensados para los accesos más frecuentes.

Ejemplos:

```txt
Category:
    business + is_active + sort_order + name

Tax:
    business + is_active

Product:
    business + is_active + name
    business + category + is_active + sort_order + name
```

Esto es importante porque las vistas normalmente listan datos filtrados por negocio.

---

# 26. Orden visual

El catálogo tiene dos niveles de orden:

```txt
Category.sort_order
    Orden de las categorías.

Product.sort_order
    Orden de los productos dentro de una categoría.
```

Ejemplo:

```txt
Bebidas           sort_order = 1
Comida            sort_order = 2

Dentro de Bebidas:
    Agua           sort_order = 1
    Coca-Cola      sort_order = 2
    Fanta          sort_order = 3
```

Query recomendada para productos:

```python
.order_by(
    "category__sort_order",
    "category__name",
    "sort_order",
    "name",
)
```

---

# 27. Flujo de creación de una categoría

```txt
Usuario owner/manager entra en crear categoría
    ↓
CategoryCreateView
    ↓
get_form_kwargs() pasa business al form
    ↓
CategoryCreateForm filtra parent por business
    ↓
form_valid() asigna business a la instancia
    ↓
Category.save()
    ↓
Category.clean()
    ↓
Se genera slug si hace falta
    ↓
Se guarda
    ↓
Redirección a category_detail
```

---

# 28. Flujo de creación de un impuesto

```txt
Usuario owner/manager entra en crear impuesto
    ↓
TaxCreateView
    ↓
get_form_kwargs() pasa business al form
    ↓
TaxCreateForm valida datos fiscales
    ↓
form_valid() asigna business
    ↓
Tax.save()
    ↓
Tax.clean()
    ↓
Se genera code si hace falta
    ↓
Se validan reglas fiscales
    ↓
Se guarda
    ↓
Redirección a tax_detail
```

---

# 29. Flujo de marcar impuesto por defecto

```txt
Usuario owner/manager pulsa "Marcar por defecto"
    ↓
TaxSetDefaultView recibe POST
    ↓
Busca tax por pk + business
    ↓
Abre transaction.atomic()
    ↓
Quita is_default a otros Tax del negocio
    ↓
Marca este Tax como is_default=True
    ↓
Marca este Tax como is_active=True
    ↓
Guarda
    ↓
Cierra transacción
    ↓
Redirige al detalle del impuesto
```

Aquí se usa `transaction.atomic()` porque hay varias escrituras que forman una única acción de negocio.

La operación debe completarse entera o no completarse.

---

# 30. Por qué `transaction.atomic()` se usa en `TaxSetDefaultView`

Cambiar el impuesto por defecto implica varias escrituras:

```txt
1. Quitar el default anterior.
2. Marcar el nuevo default.
```

Sin transacción podría pasar esto:

```txt
Se quita el default anterior
Falla algo antes de marcar el nuevo default
Resultado: el negocio queda sin impuesto por defecto
```

Por eso se usa:

```python
with transaction.atomic():
```

En cambio, crear una categoría, crear un producto o activar/desactivar normalmente es una sola escritura principal.

Por eso no necesitan transacción explícita.

---

# 31. Flujo de creación de producto

```txt
Usuario owner/manager entra en crear producto
    ↓
ProductCreateView
    ↓
get_form_kwargs() pasa business al form
    ↓
ProductCreateForm filtra:
    - categorías del business
    - impuestos activos del business
    ↓
form_valid() asigna business
    ↓
Product.save()
    ↓
Product.clean()
    ↓
Valida:
    - precio no negativo
    - coste no negativo
    - categoría del mismo business
    - impuesto del mismo business
    - impuesto activo
    - si es servicio, no stock y no barcode
    ↓
Se genera SKU si hace falta
    ↓
Se genera barcode si es físico y falta
    ↓
Se guarda
    ↓
Redirección a product_detail
```

---

# 32. Versionado del módulo

El módulo `catalog` debe versionarse de forma interna aunque el proyecto completo tenga su propio versionado.

El versionado recomendado es semántico:

```txt
MAJOR.MINOR.PATCH
```

Ejemplo:

```txt
0.1.0
```

---

## 32.1. Cuándo subir `PATCH`

Subir `PATCH` cuando se corrigen errores sin cambiar comportamiento público ni estructura de datos.

Ejemplos:

```txt
0.1.0 -> 0.1.1

- Corregir un mensaje.
- Corregir un test.
- Corregir un typo en verbose_name.
- Ajustar un template.
- Corregir una validación mal aplicada sin cambiar el modelo.
```

---

## 32.2. Cuándo subir `MINOR`

Subir `MINOR` cuando se añade funcionalidad compatible.

Ejemplos:

```txt
0.1.0 -> 0.2.0

- Añadir selectors.py.
- Añadir services.py.
- Añadir dashboard con métricas.
- Añadir filtros de búsqueda.
- Añadir exportación de catálogo.
- Añadir importación básica de productos.
- Añadir más tests.
```

---

## 32.3. Cuándo subir `MAJOR`

Subir `MAJOR` cuando se rompe compatibilidad o cambia una regla central.

Ejemplos:

```txt
0.x.x -> 1.0.0
1.x.x -> 2.0.0

- Cambiar el significado de Product.base_price.
- Cambiar la relación Product -> Tax.
- Cambiar reglas fiscales ya usadas por billing.
- Borrar campos importantes.
- Cambiar nombres de rutas públicas.
- Cambiar modelo de multiempresa.
```

Cambiar `base_price` de “sin IVA” a “con IVA” sería un cambio mayor porque afecta a ventas, facturación y fiscalidad.

---

# 33. Versión actual `0.1.0`

## Incluye

```txt
- Modelos base:
    Category
    Tax
    Product

- Reglas multiempresa:
    todos los modelos tienen business

- Reglas fiscales básicas en Tax

- Reglas de producto:
    base_price sin IVA
    servicio sin stock
    servicio sin barcode

- Formularios:
    CategoryCreateForm
    CategoryUpdateForm
    TaxCreateForm
    TaxUpdateForm
    ProductCreateForm
    ProductUpdateForm

- Views CRUD:
    dashboard
    list
    detail
    create
    update
    activate
    deactivate
    set_default_tax

- URLs del módulo

- Admin del módulo

- Tests:
    modelos
    forms
    urls
    views
```

---

# 34. Roadmap del módulo

## `0.2.0` — Selectors y Services

Añadir:

```txt
apps/catalog/selectors.py
apps/catalog/services.py
```

### `selectors.py`

Responsabilidad:

```txt
Centralizar queries de lectura.
```

Ejemplos:

```txt
get_categories_for_business()
get_products_for_business()
get_taxes_for_business()
get_default_tax_for_business()
```

### `services.py`

Responsabilidad:

```txt
Centralizar acciones de negocio.
```

Ejemplos:

```txt
activate_product()
deactivate_product()
set_default_tax()
resolve_product_tax()
calculate_price_with_tax()
```

---

## `0.3.0` — Dashboard real

Mejorar `CatalogDashboardView` con métricas:

```txt
- productos activos
- servicios activos
- categorías activas
- impuestos activos
- impuesto por defecto
- productos sin categoría
- productos sin impuesto específico
- últimos productos creados
```

---

## `0.4.0` — Preparación para inventario

Añadir integración con futuro módulo `inventory`.

Posibles reglas:

```txt
- producto físico con track_stock=True debe tener configuración de stock
- servicio nunca genera movimiento de inventario
- producto desactivado no aparece en compras/ventas nuevas
```

---

## `0.5.0` — Preparación para ventas

Añadir selectores específicos para TPV:

```txt
get_active_products_for_pos()
get_active_categories_for_pos()
get_product_for_sale()
```

---

## `1.0.0` — Catálogo estable

Se considerará estable cuando:

```txt
- Modelos estén cerrados.
- Tests estén completos.
- Integración con sales esté definida.
- Integración con billing esté definida.
- Reglas fiscales estén documentadas.
- El dashboard sea funcional.
- El módulo esté mergeado en develop.
```

---

# 35. Reglas de compatibilidad

Antes de cambiar cualquier cosa, revisar:

```txt
¿Esto afecta a ventas?
¿Esto afecta a facturas?
¿Esto afecta a Verifactu?
¿Esto cambia el significado de base_price?
¿Esto cambia el impuesto por defecto?
¿Esto rompe URLs?
¿Esto rompe tests?
¿Esto rompe datos históricos?
```

Si la respuesta es sí, el cambio debe considerarse delicado.

---

# 36. Comandos útiles

Ejecutar todos los tests de catálogo:

```bash
python manage.py test apps.catalog
```

Ejecutar solo modelos:

```bash
python manage.py test apps.catalog.tests.unit.test_models
```

Ejecutar solo forms:

```bash
python manage.py test apps.catalog.tests.unit.test_forms
```

Ejecutar solo URLs:

```bash
python manage.py test apps.catalog.tests.unit.test_urls
```

Ejecutar solo views:

```bash
python manage.py test apps.catalog.tests.integration.test_views
```

Crear migraciones:

```bash
python manage.py makemigrations catalog
```

Aplicar migraciones:

```bash
python manage.py migrate
```

---

# 37. Checklist antes de mergear

Antes de mergear el módulo `catalog` a `develop`, comprobar:

```txt
[ ] Los modelos tienen full_clean() coherente.
[ ] Las constraints funcionan.
[ ] Las reglas fiscales están testeadas.
[ ] Product.base_price está documentado como precio sin IVA.
[ ] Los formularios no exponen business.
[ ] ProductCreateForm no expone is_active.
[ ] ProductCreateForm no expone track_stock.
[ ] TaxCreateForm no expone is_default.
[ ] TaxUpdateForm no expone is_default.
[ ] Las views filtran por business.
[ ] Las acciones POST filtran por pk + business.
[ ] Las URLs resuelven correctamente.
[ ] Los tests de modelos pasan.
[ ] Los tests de forms pasan.
[ ] Los tests de URLs pasan.
[ ] Los tests de views pasan.
[ ] El README está actualizado.
[ ] La versión del módulo está actualizada.
```

---

# 38. Decisiones de diseño importantes

## 38.1. `catalog` no guarda históricos

El catálogo es configuración viva.

Los históricos se guardarán en otros módulos.

---

## 38.2. `base_price` es sin IVA

Regla no negociable del módulo.

---

## 38.3. `Tax` es una plantilla fiscal

No es una factura.

No es una línea fiscal histórica.

---

## 38.4. No se borra, se desactiva

Evita romper ventas/facturas futuras o pasadas.

---

## 38.5. `business` nunca viene del usuario

Siempre se obtiene desde:

```python
request.user.business
```

---

## 38.6. `is_default` se gestiona con vista propia

No desde `TaxCreateForm` ni `TaxUpdateForm`.

Esto evita conflictos con la regla de un único impuesto por defecto.

---

# 39. Resumen final

El módulo `catalog` es la base comercial y fiscal del TPV.

Debe ser muy estable porque otros módulos dependerán de él:

```txt
sales
billing
inventory
reports
verifactu
```

Las reglas más importantes son:

```txt
- Todo pertenece a un Business.
- El usuario nunca elige business.
- Product.base_price siempre es sin IVA.
- Tax centraliza reglas fiscales base.
- Solo un Tax por defecto por Business.
- Producto físico puede controlar stock.
- Servicio nunca controla stock.
- No se borran datos sensibles, se desactivan.
- Las ventas/facturas futuras copiarán snapshots.
```

Este README debe mantenerse actualizado con cada cambio importante del módulo.
