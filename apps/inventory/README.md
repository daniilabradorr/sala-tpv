# Modulo `inventory`

## Resumen rapido

`inventory` es el modulo que mantiene el stock real de productos fisicos por tienda.
Su trabajo principal es doble:

1. Decir cuanto stock hay ahora.
2. Dejar trazabilidad de como se llego a ese stock.

En este modulo, una regla manda sobre todo lo demas:

> Nunca se modifica `current_stock` sin crear un `StockMovement`.

---

## 1) Que es el modulo `inventory`

Es el dominio de inventario del TPV/ERP. Trabaja sobre productos ya definidos en `catalog`, y controla existencias por `Business` y por `Store`.

No define precios, impuestos ni facturacion. Define estado fisico del stock y su auditoria.

---

## 2) Que problema resuelve dentro del TPV/ERP

En una operacion real, no basta con saber que producto existe: hay que saber cuantas unidades hay, donde estan y quien cambio ese numero.

`inventory` resuelve eso:

- centraliza el stock actual por producto y tienda,
- permite ajustes cuando el conteo real no coincide con el sistema,
- permite salidas que dejen stock negativo solo cuando el servicio recibe una decision explicita,
- registra cada cambio con historial auditado.

Ejemplo corto:

```txt
Sistema: Coca-Cola = 20
Conteo fisico: Coca-Cola = 17
Accion: crear ajuste y confirmarlo
Resultado: current_stock pasa a 17 y se crea un StockMovement de -3
```

---

## 3) Que hace el modulo

Responsabilidades actuales del modulo:

- Mantener `InventoryItem` (foto actual del stock por producto/tienda).
- Crear y gestionar `StockAdjustment` y sus lineas.
- Confirmar o cancelar ajustes segun reglas.
- Registrar `StockMovement` en cada cambio real de stock.
- Exponer vistas, formularios, rutas y consultas del dominio.

---

## 4) Que NO debe hacer el modulo

Para no mezclar responsabilidades, `inventory` no debe:

- crear productos o servicios (`catalog`),
- definir precios o impuestos (`catalog`/`billing`),
- crear ventas, tickets o facturas (`sales`/`billing`),
- gestionar pagos o caja (`payments`/`cash_register`),
- ejecutar compras completas (`purchases`),
- cambiar stock directamente desde `views.py`, `forms.py` o `admin.py`.

Si cambia stock, tiene que pasar por `services.py`.

---

## 5) Relacion con otros modulos

### `catalog`

- Define `Product`.
- Decide si un producto es servicio (`is_service`) y si controla stock (`track_stock`).
- `inventory` solo opera con productos fisicos que controlan stock.

### `stores`

- Define `Store`.
- `inventory` controla stock por tienda.

### `sales`

- Debe consumir stock en operaciones de venta (flujo futuro o en expansion).
- El descuento real debe terminar en servicios de `inventory` para mantener auditoria.

### `billing`

- Factura operaciones.
- No debe modificar stock directamente.

### `purchases`

- Al recibir mercancia, deberia incrementar stock via servicios de `inventory`.

### `reports`

- Lee datos de inventario y movimientos para informes.
- No modifica estado.

---

## 6) Modelos del modulo

## `InventoryItem`

Representa el estado actual del inventario de un producto en una tienda.

Ejemplo:

```txt
Business: Bar Centro
Store: Tienda Centro
Product: Agua 500ml
current_stock: 40
reserved_stock: 5
available_stock: 35
```

Responsabilidades clave:

- guardar stock actual y reservado,
- guardar min/max de referencia,
- calcular propiedades (`available_stock`, `needs_restock`),
- evitar duplicados por `business + store + product`.

Reglas actuales importantes:

- `current_stock` puede ser negativo. Esto permite representar casos reales como una venta permitida sin stock suficiente.
- `reserved_stock` no puede ser negativo.
- `minimum_stock` no puede ser negativo.
- `maximum_stock` puede estar vacio, pero si se informa no puede ser negativo.
- `maximum_stock` no puede ser menor que `minimum_stock`.
- `available_stock` se calcula en memoria como:

```txt
available_stock = current_stock - reserved_stock
```

- `needs_restock` usa `available_stock`, no `current_stock` directamente.

Ejemplo:

```txt
current_stock = 10
reserved_stock = 8
minimum_stock = 3
available_stock = 2

needs_restock = True, porque 2 <= 3
```

## `StockAdjustment`

Cabecera de un ajuste de inventario.

- Estado tipico: `draft -> confirmed` o `draft -> cancelled`.
- Crear ajuste no cambia stock.

## `StockAdjustmentLine`

Linea de ajuste para un `InventoryItem` concreto.

- `product`, `system_stock` y `difference` se derivan internamente.
- Usuario introduce sobre todo `inventory_item`, `counted_stock` y notas.
- `system_stock` puede ser negativo si el sistema ya estaba en negativo.
- `counted_stock` no puede ser negativo porque representa el conteo fisico real.
- `difference` se calcula siempre como `counted_stock - system_stock`.

Ejemplo valido:

```txt
system_stock = -3
counted_stock = 2
difference = 5
```

## `StockMovement`

Registro auditable de cada cambio de stock.

Incluye, como minimo conceptual:

- tipo de movimiento,
- cantidad siempre positiva,
- `stock_before`,
- `stock_after`,
- contexto y usuario.

Reglas actuales importantes:

- `quantity` siempre es positiva.
- El tipo de movimiento indica si la cantidad entra o sale.
- `stock_before` y `stock_after` pueden ser negativos.
- Para una entrada, `stock_after` debe ser `stock_before + quantity`.
- Para una salida, `stock_after` debe ser `stock_before - quantity`.

Ejemplo valido de salida:

```txt
stock_before = 2
quantity = 5
stock_after = -3
```

---

## 7) Responsabilidad de cada archivo

### `apps.py`

Configura la app Django (`InventoryConfig`).
No contiene reglas de negocio.

### `models.py`

Define estructura de datos, relaciones, constraints y reglas criticas del dominio.
Debe proteger invariantes incluso si alguien usa ORM directamente.

### `forms.py`

Valida entrada de usuario para UI HTML.
Filtra querysets por negocio/tienda y evita exponer campos peligrosos.
No debe modificar stock.

### `views.py`

Orquesta requests HTTP.
Hace esto: autenticar, instanciar formularios, usar selectors para lectura, usar services para escritura, mostrar mensajes y redirigir.
No debe contener logica pesada de inventario.

### `urls.py`

Mapea rutas del modulo (`app_name = "inventory"`) y mantiene nombres estables para `reverse()`/templates/tests.

### `selectors.py`

Solo lectura.
Centraliza consultas y filtros del dominio (listas, dashboard, detalles).
No hace `create()`, `update()`, `delete()`, `save()`.

### `services.py`

Logica de escritura y reglas transaccionales.
Aqui viven operaciones criticas: stock inicial, ajustes, confirmaciones, cancelaciones y creacion de movimientos.

### `admin.py`

Configuracion del admin de Django para visualizar/gestionar sin romper auditoria.
No deberia permitir atajos peligrosos sobre stock o movimientos.

### `tests/`

Pruebas unitarias e integracion del modulo.
Factories para crear datos de test sin duplicar setup.

---

## 8) Donde vive cada tipo de logica

Regla practica para mantener el modulo limpio:

- `models.py`: invariantes del dominio y coherencia de datos.
- `forms.py`: validacion de entrada del usuario y normalizacion basica.
- `views.py`: coordinacion HTTP, no negocio complejo.
- `selectors.py`: lectura y filtros.
- `services.py`: escritura, transacciones y reglas de negocio.

Ejemplo rapido:

```txt
Usuario confirma ajuste desde UI
-> view valida formulario
-> view llama confirm_stock_adjustment(...)
-> service aplica cambios de stock y crea StockMovement
-> view muestra mensaje y redirige
```

---

## 9) Regla mas importante: no tocar `current_stock` sin `StockMovement`

Esta es la garantia de trazabilidad del modulo.

Si alguien cambia `current_stock` a mano y no deja movimiento:

- se pierde historial,
- no se puede auditar quien lo hizo,
- los reportes dejan de cuadrar,
- el inventario deja de ser confiable.

Por eso:

- las vistas no editan stock directamente,
- los formularios no editan stock directamente,
- los cambios se ejecutan en servicios,
- cada cambio genera su movimiento asociado.

---

## 10) Flujo de stock inicial

Caso de uso: se crea la ficha de inventario y se carga la cantidad inicial.

Flujo:

1. Usuario abre formulario de stock inicial.
2. `InitialStockForm` valida cantidad.
3. La vista llama `create_initial_stock(...)`.
4. El servicio valida reglas (por ejemplo, que aplique como carga inicial).
5. El servicio actualiza `current_stock`.
6. El servicio crea `StockMovement` tipo inicial.
7. La vista informa resultado y redirige.

La carga inicial no debe usarse como atajo para corregir stock despues de que ya existen movimientos. Para correcciones posteriores se debe usar un ajuste.

---

## 11) Entradas, salidas y stock negativo opcional

Las operaciones base de stock viven en `services.py`.

### Entradas con `increase_stock(...)`

`increase_stock(...)` aumenta `current_stock` y crea un `StockMovement` de entrada.

Reglas principales:

- la cantidad debe ser mayor que cero,
- `movement_type` debe ser un tipo de entrada,
- la ficha de inventario debe estar activa,
- se bloquea el `InventoryItem` con `select_for_update()`,
- todo ocurre dentro de `transaction.atomic()`,
- se guarda `stock_before`,
- se calcula `stock_after = stock_before + quantity`,
- se actualiza `current_stock`,
- se crea `StockMovement`.

Si la ficha esta inactiva, el servicio lanza `ValidationError` y no modifica stock.

### Salidas con `decrease_stock(...)`

`decrease_stock(...)` reduce `current_stock` y crea un `StockMovement` de salida.

El servicio acepta el parametro:

```python
allow_negative=False
```

El valor por defecto es `False` para evitar permitir stock negativo por accidente.

Comportamiento:

- con `allow_negative=False`, una salida que supere el stock disponible se bloquea,
- con `allow_negative=True`, la salida se permite aunque no haya stock suficiente,
- si la operacion se completa, siempre se crea un `StockMovement`,
- `quantity` sigue siendo positiva,
- el tipo de movimiento sigue determinando si es entrada o salida,
- no se usan cantidades negativas para representar salidas.

Ejemplo:

```python
from decimal import Decimal

from apps.inventory.models import StockMovement
from apps.inventory.services import decrease_stock

decrease_stock(
    inventory_item=item,
    quantity=Decimal("5.000"),
    movement_type=StockMovement.TYPE_SALE,
    allow_negative=True,
)
```

Si antes habia 2 unidades:

```txt
stock_before = 2
quantity = 5
stock_after = -3
current_stock = -3
```

### Quien decide si se permite vender sin stock

`inventory` no consulta `POSSettings`.

La decision de permitir o no vender sin stock corresponde al flujo que llama al servicio. Por ejemplo, en un flujo futuro de ventas, `sales` podra leer su configuracion y pasar explicitamente:

```python
allow_negative=pos_settings.allow_sale_without_stock
```

Esto mantiene separadas las responsabilidades:

- `sales` decide si una venta concreta puede continuar sin stock suficiente,
- `inventory` aplica la operacion de stock de forma segura y auditable.

---

## 12) Flujo de ajustes de stock

El ajuste esta pensado en dos fases: preparar y aplicar.

### Fase A: preparar (no cambia stock)

1. Crear `StockAdjustment` en `draft`.
2. Agregar `StockAdjustmentLine`.
3. Actualizar lineas si hace falta.
4. Revisar diferencias.

Los servicios que preparan lineas tambien protegen la regla de ficha activa:

- `add_stock_adjustment_line(...)` rechaza `InventoryItem` inactivo.
- `update_stock_adjustment_line(...)` rechaza `InventoryItem` inactivo.
- Esta proteccion vive en `services.py`, no solo en los formularios.
- No se pueden dejar borradores nuevos asociados a fichas inactivas usando los
  servicios directamente.

### Fase B: aplicar (si cambia stock)

1. Confirmar ajuste.
2. Servicio valida estado y lineas.
3. Servicio bloquea cada `InventoryItem` con `select_for_update()`.
4. Servicio comprueba que la ficha siga activa.
5. Servicio comprueba que el stock actual siga coincidiendo con el
   `system_stock` guardado en la linea.
6. Servicio aplica `counted_stock` sobre cada `InventoryItem`.
7. Servicio crea `StockMovement` por diferencia.
8. Ajuste pasa a `confirmed`.

Si se cancela en `draft`, pasa a `cancelled` y no toca stock.

La comprobacion de `system_stock` evita confirmar recuentos obsoletos.

Ejemplo:

```txt
1) Se prepara una linea con system_stock = -3 y counted_stock = 2
2) Antes de confirmar, entra mercancia y current_stock pasa a 7
3) Al confirmar, el servicio detecta que 7 != -3
4) Resultado: se lanza ValidationError, no se modifica stock y no se crea movimiento
```

La comprobacion de ficha activa evita modificar inventario que fue desactivado
despues de preparar el ajuste. Si cualquier linea falla durante la confirmacion,
la transaccion completa se revierte: no quedan cambios parciales ni movimientos
huérfanos.

---

## 13) Selectors de stock bajo y sin stock

Los selectors usan stock disponible, no solo stock fisico.

La regla actual es:

```txt
available = current_stock - reserved_stock
```

### Stock bajo

Un item se considera con stock bajo cuando:

```txt
available > 0
available <= minimum_stock
```

Ejemplo:

```txt
current_stock = 10
reserved_stock = 8
minimum_stock = 3
available = 2

Resultado: stock bajo
```

### Sin stock

Un item se considera sin stock cuando:

```txt
available <= 0
```

Ejemplo:

```txt
current_stock = 2
reserved_stock = 2
available = 0

Resultado: sin stock
```

Un mismo `InventoryItem` no debe contarse a la vez como stock bajo y como sin stock en los indicadores del dashboard.

---

## 14) Por que `StockMovement` es auditoria (y no se edita ni borra)

`StockMovement` es el libro de hechos del inventario.
No es un dato operativo para "corregir a mano".

Si hubo un error historico, la practica correcta es crear un movimiento compensatorio (o un nuevo ajuste), no reescribir el pasado.

Esto mantiene:

- trazabilidad,
- responsabilidad de usuario,
- consistencia en informes,
- capacidad de auditoria.

---

## 15) Pruebas del modulo

En el estado actual del repositorio existen estos archivos:

- `tests/unit/test_models.py`
- `tests/unit/test_forms.py`
- `tests/unit/test_selectors.py`
- `tests/unit/test_services.py`
- `tests/unit/test_urls.py`
- `tests/integration/test_views.py`
- `tests/factories.py`

Cobertura esperada por tipo:

### Tests de modelos

- propiedades (`available_stock`, `needs_restock`),
- validaciones de dominio,
- coherencia de estados,
- ajustes con `system_stock` negativo,
- rechazo de `counted_stock` negativo.

### Tests de formularios

- datos validos/invalidos,
- campos expuestos,
- filtros por negocio/tienda,
- reglas de ajuste en borrador/no borrador.

### Tests de selectors

- filtros de stock bajo usando `available`,
- filtros de sin stock usando `available <= 0`,
- indicadores del dashboard sin doble conteo entre stock bajo y sin stock.

### Tests de services

- operaciones de escritura,
- reglas de negocio,
- cambios de stock,
- generacion de movimientos,
- restricciones de estados de ajustes,
- salidas con y sin `allow_negative`,
- rechazo de modificaciones sobre fichas inactivas,
- rechazo de fichas inactivas al crear lineas de ajuste,
- rechazo de fichas inactivas al actualizar lineas de ajuste,
- recuperacion desde stock negativo,
- rollback de `decrease_stock` si falla la creacion del movimiento,
- confirmacion valida de ajuste desde stock negativo,
- ajustes obsoletos,
- rollback completo de ajustes con varias lineas,
- validaciones de `get_or_create_inventory_item`.

### Tests de URLs

- `reverse()` y `resolve()` de rutas del modulo.

### Tests de views

- flujos HTTP,
- permisos,
- aislamiento por negocio,
- formularios y redirecciones,
- integracion con servicios.

---

## 16) Ejemplos sencillos

### Ejemplo A: crear item y cargar stock inicial

```txt
1) Creo InventoryItem para Producto X en Tienda Y (stock nace en 0)
2) Cargo stock inicial = 25
3) Resultado:
   - InventoryItem.current_stock = 25
   - StockMovement tipo initial con before=0 y after=25
```

### Ejemplo B: ajuste por descuadre

```txt
Sistema dice 12, conteo real 9
-> Creo ajuste draft
-> Agrego linea con counted_stock=9
-> Confirmo ajuste
Resultado:
- current_stock pasa a 9
- se registra StockMovement de salida por 3
```

### Ejemplo C: venta permitida sin stock suficiente

```txt
Sistema dice 2, venta intenta sacar 5
-> El llamador decide permitir stock negativo
-> Llama decrease_stock(..., allow_negative=True)
Resultado:
- current_stock pasa a -3
- StockMovement guarda before=2, quantity=5 y after=-3
```

### Ejemplo D: venta bloqueada por defecto

```txt
Sistema dice 2, venta intenta sacar 5
-> decrease_stock(...) se llama sin allow_negative
Resultado:
- se lanza ValidationError
- current_stock sigue en 2
- no se crea StockMovement
```

### Ejemplo E: recuperacion desde stock negativo

```txt
Stock inicial del sistema: -3
Entrada de mercancia: 10

Resultado:
- current_stock = 7
- StockMovement.stock_before = -3
- StockMovement.quantity = 10
- StockMovement.stock_after = 7
```

---

## 17) Checklist de arquitectura para contribuir

Antes de mergear cambios en `inventory`, conviene verificar:

- [ ] Ninguna vista modifica `current_stock` directamente.
- [ ] Ningun formulario modifica stock directamente.
- [ ] Toda escritura de stock pasa por `services.py`.
- [ ] Cada cambio de stock crea `StockMovement`.
- [ ] `add_stock_adjustment_line` rechaza fichas inactivas.
- [ ] `update_stock_adjustment_line` rechaza fichas inactivas.
- [ ] `confirm_stock_adjustment` rechaza fichas inactivas.
- [ ] La confirmacion comprueba `current_stock == system_stock`.
- [ ] Un ajuste obsoleto no sobrescribe movimientos posteriores.
- [ ] Si falla una linea, se revierte toda la confirmacion.
- [ ] `increase_stock` puede recuperar un stock negativo.
- [ ] `decrease_stock` revierte `current_stock` si falla `StockMovement`.
- [ ] Las salidas que puedan dejar stock negativo pasan `allow_negative=True` de forma explicita.
- [ ] `allow_negative` mantiene `False` como valor predeterminado.
- [ ] Inventory no consulta `POSSettings`.
- [ ] Las operaciones criticas usan `transaction.atomic()`.
- [ ] Las modificaciones criticas usan `select_for_update()`.
- [ ] `quantity` permanece positiva.
- [ ] `selectors.py` se mantiene de solo lectura.
- [ ] Se respeta aislamiento por `business`.
- [ ] Hay tests para el flujo afectado.

---

## Nota final

Este modulo es sensible porque impacta operaciones reales del negocio.

Si hay que elegir entre "hacerlo rapido" y "dejar trazabilidad", aqui la trazabilidad manda.
Un inventario confiable depende de mantener estricta la separacion entre lectura, validacion, orquestacion y escritura.
