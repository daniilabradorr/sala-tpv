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

## `StockAdjustment`

Cabecera de un ajuste de inventario.

- Estado tipico: `draft -> confirmed` o `draft -> cancelled`.
- Crear ajuste no cambia stock.

## `StockAdjustmentLine`

Linea de ajuste para un `InventoryItem` concreto.

- `product`, `system_stock` y `difference` se derivan internamente.
- Usuario introduce sobre todo `inventory_item`, `counted_stock` y notas.

## `StockMovement`

Registro auditable de cada cambio de stock.

Incluye, como minimo conceptual:

- tipo de movimiento,
- cantidad,
- `stock_before`,
- `stock_after`,
- contexto y usuario.

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

---

## 11) Flujo de ajustes de stock

El ajuste esta pensado en dos fases: preparar y aplicar.

### Fase A: preparar (no cambia stock)

1. Crear `StockAdjustment` en `draft`.
2. Agregar `StockAdjustmentLine`.
3. Revisar diferencias.

### Fase B: aplicar (si cambia stock)

1. Confirmar ajuste.
2. Servicio valida estado y lineas.
3. Servicio aplica `counted_stock` sobre cada `InventoryItem`.
4. Servicio crea `StockMovement` por diferencia.
5. Ajuste pasa a `confirmed`.

Si se cancela en `draft`, pasa a `cancelled` y no toca stock.

---

## 12) Por que `StockMovement` es auditoria (y no se edita ni borra)

`StockMovement` es el libro de hechos del inventario.
No es un dato operativo para "corregir a mano".

Si hubo un error historico, la practica correcta es crear un movimiento compensatorio (o un nuevo ajuste), no reescribir el pasado.

Esto mantiene:

- trazabilidad,
- responsabilidad de usuario,
- consistencia en informes,
- capacidad de auditoria.

---

## 13) Pruebas del modulo

En el estado actual del repositorio existen estos archivos:

- `tests/unit/test_models.py`
- `tests/unit/test_forms.py`
- `tests/unit/test_services.py`
- `tests/unit/test_urls.py`
- `tests/integration/test_views.py`
- `tests/factories.py`

Cobertura esperada por tipo:

### Tests de modelos

- propiedades (`available_stock`, `needs_restock`),
- validaciones de dominio,
- coherencia de estados.

### Tests de formularios

- datos validos/invalidos,
- campos expuestos,
- filtros por negocio/tienda,
- reglas de ajuste en borrador/no borrador.

### Tests de selectors

- no hay archivo dedicado aun en esta version.
- recomendable anadir `tests/unit/test_selectors.py` para proteger filtros y consultas de dashboard/listados.

### Tests de services

- operaciones de escritura,
- reglas de negocio,
- cambios de stock,
- generacion de movimientos,
- restricciones de estados de ajustes.

### Tests de URLs

- `reverse()` y `resolve()` de rutas del modulo.

### Tests de views

- flujos HTTP,
- permisos,
- aislamiento por negocio,
- formularios y redirecciones,
- integracion con servicios.

---

## 14) Ejemplos sencillos

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

---

## 15) Checklist de arquitectura para contribuir

Antes de mergear cambios en `inventory`, conviene verificar:

- [ ] Ninguna vista modifica `current_stock` directamente.
- [ ] Ningun formulario modifica stock directamente.
- [ ] Toda escritura de stock pasa por `services.py`.
- [ ] Cada cambio de stock crea `StockMovement`.
- [ ] `selectors.py` se mantiene de solo lectura.
- [ ] Se respeta aislamiento por `business`.
- [ ] Hay tests para el flujo afectado.

---

## Nota final

Este modulo es sensible porque impacta operaciones reales del negocio.

Si hay que elegir entre "hacerlo rapido" y "dejar trazabilidad", aqui la trazabilidad manda.
Un inventario confiable depende de mantener estricta la separacion entre lectura, validacion, orquestacion y escritura.
