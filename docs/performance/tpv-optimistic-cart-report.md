# Fase 2B — carrito optimista con confirmación autoritativa

Rama: `feat/tpv-optimistic-cart`, basada en `61fa856` de `perf/tpv-inventory`.
La autorización posterior permite contratos y migraciones de Sales y el push de
esta rama. No se modifica producción, ni se hace merge o despliegue.

## Modelos, migración e idempotencia

`Sale.cart_version` es un entero monotónico, inicialmente 0 para ventas nuevas
**y existentes**. Tiene también DEFAULT 0 en PostgreSQL para que un escritor
anterior pueda insertar durante la preparación del esquema. Eso no hace seguro
mezclar escritores antiguos y nuevos: los antiguos no avanzan la revisión.

`CartOperation` conserva Business, Sale, UUID, tipo, SHA-256 del contenido
normalizado, versión aceptada e ID de línea resultante, además de fechas. La
restricción UNIQUE(Sale, UUID) y el bloqueo de Sale serializan dos peticiones
simultáneas con la misma clave. No almacena datos de clientes ni pagos. El ID
resultante no es FK: un recibo de añadido debe sobrevivir a la eliminación de su
línea para reconocer la repetición.

El recibo y la mutación se confirman en la misma transacción. Primero se validan
ámbito/permisos, después se busca el recibo y se compara su contenido. Solo una
operación nueva debe superar la precondición de versión y los servicios de
negocio existentes. Una repetición devuelve el recibo y el estado **actual**, sin
volver a ejecutar efectos. La versión esperada es una precondición de transporte,
no parte del contenido comercial: tipo, producto/línea y cantidad normalizada.
Metadatos provisionales del navegador no determinan precios ni impuestos.

No hay expiración automática ni borrado por TTL: se conservan los recibos durante
la vida de Sale y solo desaparecen con su eliminación por las relaciones CASCADE
existentes. No ejecutar limpiezas parciales mientras puedan llegar reintentos.
Esto añade almacenamiento proporcional al número de operaciones aceptadas.

Cada añadido, eliminación o cambio efectivo de cantidad/precio/descuento avanza
la versión bajo el bloqueo de Sale. También lo hacen cambios efectivos de
cliente/documento/caja/sesión. Un cambio fallido revierte versión y recibo. Una
cantidad/precio/descuento idénticos valida la línea mediante `full_clean`, registra
el recibo y mantiene la versión; no ejecuta un `save` sin cambios ni sus señales.
No se detectaron señales de SaleLine que exigieran una escritura de ese no-op.
Las escrituras deben pasar por los servicios de Sales, como antes; SQL directo
que cambie líneas fuera de estos servicios no participa en el protocolo.

## Contratos HTTP

- `GET /sales/stores/{store}/sales/{sale}/cart-sync/`: instantánea coherente bajo
  bloqueo de Sale. Devuelve identidad de ámbito, versión, estado, importes
  confirmados y líneas. `pending=UUID,...` consulta hasta 50 recibos para recuperar
  una recarga con respuestas perdidas. No devuelve datos completos de recibos.
- `POST` a esa misma URL: JSON `{key, version, kind, product, quantity}` para
  `kind=add`; `{key, version, kind, line, quantity}` para `quantity`; y
  `{key, version, kind, line}` para `delete`. Cantidades decimales como cadenas,
  positivas y con hasta tres decimales. CSRF y permisos de venta obligatorios.
- HTTP 200: `{cart, key, replayed, accepted_version, line}`. Puede ser repetición;
  `accepted_version` es la versión original y `cart.version` la actual.
- HTTP 409: conflicto de revisión, contenido de clave o línea inexistente, con
  `code=version|key|line`. HTTP 422: entrada o regla de negocio rechazada. Los
  errores de ámbito/permisos siguen respondiendo 403/404.
- Todas las respuestas del protocolo llevan `Cache-Control: no-store`.
- Los formularios HTML existentes siguen disponibles. El POST de checkout exige
  ahora `cart_version`; si falta o queda obsoleto devuelve 409 para revisar.

## Interacción, cola y recuperación

JavaScript vanilla mantiene estado confirmado más intenciones pendientes y
proyecta el carrito visual. Añadir, cambiar cantidad con botones o entrada decimal,
eliminar, actualizar contador e importe provisional se reflejan antes de HTTP.
Las filas se conservan y sus controles se actualizan sin reconstruir el carrito
por cada clic. Los editores manuales conservan su validación original, incluyen
la versión vista y concilian las filas agrupadas mediante JSON al guardar. HTMX mantiene catálogo, búsqueda, cabecera y editores existentes.

La cola usa **sessionStorage por usuario/Business/Store/Sale y pestaña**. Sobrevive
al reload en esa pestaña; cerrar la pestaña termina ese diario local. No promete
conservar intenciones no confirmadas después de cerrar la sesión del navegador.
La idempotencia del servidor permanece persistente independientemente de esto.
Si no está disponible el almacenamiento al iniciar, se mantienen los formularios
progresivos anteriores; el modo optimista requiere sessionStorage operativo.

Hay una mutación en vuelo por cola. El orden se guarda mediante una secuencia
entera, sin depender del reloj ni del orden de iteración del almacenamiento.
Cada intención conserva además la versión sobre la que se preparó. Solo un
avance confirmado de esa misma cola permite actualizar automáticamente la base
de las intenciones aún no enviadas; una lectura más nueva, una recarga o un
recibo repetido con cambios posteriores de otra pestaña exige revisión explícita.
Cada intención se guarda antes de enviarse;
una operación enviada conserva UUID, contenido y versión ante timeout. El timeout
aborta la espera del navegador a los 15 s; **no supone rollback en el servidor**.
La recuperación consulta recibos y reintenta la misma identidad. Las dependencias
de líneas provisionales se resuelven mediante el ID confirmado del añadido.

Cambios consecutivos de cantidad aún no enviados sobre la misma línea se
consolidan en su último valor. Los añadidos conservan sus operaciones y snapshots
comerciales por línea: no se convierten automáticamente en una línea fiscal única.
Solo snapshots equivalentes se agrupan visualmente; precios, descuentos o
impuestos distintos conservan controles separados. En un grupo equivalente,
el incremento se aplica a la última línea y la reducción elimina/reduce desde
las últimas líneas. Los servicios originales recalculan cada línea modificada.

Una respuesta antigua de lectura o mutación no sustituye una versión confirmada
más nueva. Las cantidades inválidas quedan marcadas y bloquean abrir checkout
hasta corregirlas; no se ignora silenciosamente un borrador inválido.
BroadcastChannel avisa a otras pestañas del mismo usuario; la seguridad no depende
de ese aviso, sino de la precondición del servidor. Otra pestaña u otro usuario
pueden provocar un 409; no se rebasan automáticamente cantidades antiguas.

Ante 409 se muestra el total y las cantidades confirmadas para revisar antes de
aplicar de nuevo la intención o descartar pendientes. Un rechazo definitivo 422
permite descartar pendientes y recuperar el estado real. Un fallo de conexión o
respuesta desconocida conserva la operación para reintento sin duplicados; no
ofrece descartarla suponiendo que no se confirmó. No se guardan pagos en la cola.

## Checkout

Se muestra inmediatamente la carcasa, se bloquean las ediciones de la venta, se
vacía la cola y se recupera la instantánea autoritativa. El checkout muestra el
total definitivo y avisa si difiere del provisional. No se presenta su formulario
de confirmación mientras la cola siga pendiente o tenga errores.

`run_checkout` bloquea Sale, verifica la versión y hace preflight/completado de
Sales en una transacción acotada. Las ediciones concurrentes usan el mismo
bloqueo: o se aceptan antes y la confirmación obtiene conflicto, o el completado
ocurre primero y la edición ya no se admite. `complete_sale` conserva todas sus
validaciones, inventario y orden de locking. Payments y Billing se ejecutan
**después** de esa transacción, con su idempotencia y recuperación parcial
existentes. Un fallo de emisión no revierte un pago que ya se confirmó.

## Ejecución local reproducible

Usar Python y dependencias del proyecto, PostgreSQL 16 temporal y Chromium local.
Los settings `diagnostic_postgres` exigen una base dedicada `tpv_diag_*`; no usar
DATABASE_URL de producción. Ejemplo con un PostgreSQL local autorizado:

```bash
export DJANGO_SETTINGS_MODULE=config.settings.diagnostic_postgres
export TPV_DIAGNOSTICS=0
export TPV_TEST_DATABASE_URL=postgresql://postgres:local-diagnostic-only@127.0.0.1:55432/tpv_diag_phase2b
export TPV_CHROMIUM=/usr/bin/chromium
.venv/bin/python manage.py test --noinput
mkdir -p work/tpv-optimistic-cart
TPV_CART_BROWSER_REPORT=work/tpv-optimistic-cart/browser-measurements.json \
  .venv/bin/python manage.py test e2e.browser_optimistic_cart --noinput
TPV_CART_BROWSER_REPORT=work/tpv-optimistic-cart/visual-matrix.json \
  .venv/bin/python manage.py test tests.performance.optimistic_cart_matrix.VisualMatrix --noinput
```

No ejecutar estos comandos de test simultáneamente sobre la misma base de test:
el runner crea y destruye su esquema. Las emisiones de esas pruebas son locales,
con datos ficticios; no hay cobros ni envíos fiscales reales. Playwright requiere
su bucle de eventos; solo el arnés de navegador relaja temporalmente el guard de
ORM síncrono en ese hilo, y lo restaura al finalizar la clase.

## Preparación del esquema y rollback

La migración incremental `0007` añade columna y tabla; no reescribe históricas.
En PostgreSQL 16 el default constante evita un backfill de filas en Python; el
ALTER requiere bloqueo de esquema, por lo que debe planificarse en staging.
Se valida la aplicación desde una base creada por el runner y la ausencia de
migraciones pendientes. No se ha aplicado el esquema en producción.

Para desplegar en el futuro: copia de seguridad, pausar ediciones/cobros, drenar
workers antiguos, aplicar migración y arrancar todos los workers compatibles.
Recargar páginas abiertas para renovar JS y formularios (los antiguos no llevan
la versión de checkout). No operar el carrito con una mezcla de escritores
antiguos y nuevos. Eso requiere autorización de despliegue independiente.

Rollback preferible: pausar/drenar y retirar la interfaz optimista manteniendo
los servicios nuevos que avanzan revisiones. Si se vuelve al código anterior,
conservar columna y recibos; antes de reactivar el protocolo habrá que conciliar
las colas y avanzar las revisiones de las ventas afectadas de forma controlada,
porque el código antiguo no registra sus cambios en esa versión. Revertir `0007` destruye los recibos y pierde protección frente
a reintentos; no hacerlo con colas de navegador pendientes. Cualquier reversión
destructiva necesita planificación y copia de seguridad, no un borrado rutinario.

## Verificación y mediciones

Resultados obtenidos en el entorno local de prueba:

- Suite completa PostgreSQL ejecutada: **1.613 tests correctos**, 223,912 s.
  Incluía 15 casos de navegador. Después se separaron los casos de navegador en
  `e2e/browser_optimistic_cart.py`, siguiendo la estructura de CI existente.
- Tras los ajustes finales de recuperación: **54 tests específicos correctos**,
  57,567 s, con **19 pruebas de navegador**, 16 del protocolo, 6 de carreras
  PostgreSQL y 13 de edición existente. Se comprueban también respuesta perdida
  seguida de cambios externos, base obsoleta al recargar, orden de añadido →
  cantidad → eliminación con almacenamiento desordenado e input inválido.
- La suite general actual no descubre automáticamente `e2e/browser_*.py`;
  ejecutarlos explícitamente como en los comandos anteriores. El job existente
  de CI que instala Chromium incluye ahora `e2e.browser_optimistic_cart`.
- Suite completa anterior de inventario/ventas/pagos/emisión conservada; no se
  han modificado Billing, Payments, Inventory ni sus migraciones.
- Ruff, sintaxis JavaScript, `manage.py check`, `makemigrations --check` y
  `git diff --check`: correctos.
- Migración atrás/adelante sobre base PostgreSQL desechable: venta existente con
  versión 0, importe y línea preservados. No se usa esto como recomendación de
  borrar recibos al hacer rollback en un entorno con operaciones reales.
- 20 añadidos rápidos al mismo producto: 20 unidades persistidas, sin duplicados
  por reintento; agrupación visual y snapshots comerciales separados.
- 20 incrementos consecutivos de cantidad aún no enviados: una mutación HTTP de
  cantidad, resultado de 1 a 21 unidades, probado con dos recibos incluyendo el
  añadido inicial.
- Reintento de respuesta perdida/timeout conserva UUID. El test de timeout
  comprime el temporizador de 15 s a 40 ms en el navegador de prueba y conserva
  el mismo camino de AbortController y recuperación.

Comparación visual al añadir un producto; 10 muestras por celda, sin warmup
separado. p95 por rango más próximo: con 10 muestras corresponde al máximo;
no es una estimación robusta del percentil de producción. Tiempos en ms:

| Líneas previas | HTMX visual p50 / p95 | Optimista visual p50 / p95 | HTTP HTMX p50 | HTTP optimista p50 |
| --- | ---: | ---: | ---: | ---: |
| 1 | 491,55 / 521,5 | 13,5 / 20,3 | 469,8 | 463,95 |
| 20 | 506,1 / 514,4 | 16,5 / 22,1 | 473,55 | 462,6 |
| 50 | 552,2 / 586,4 | 23,15 / 31,2 | 495,0 | 463,5 |

30 de los 30 casos optimistas de esta matriz estuvieron por debajo de 50 ms en la
cota de presentación; esto no garantiza ese tiempo en todos los dispositivos.
Los cambios locales se ven antes de HTTP, que sigue pendiente.

El tiempo HTTP incluye la demora impuesta, procesamiento y respuesta; no mide
red pura ni prueba que la red se haya acelerado.

Matriz final ejecutada sobre `752ad68`: 60 muestras, prueba correcta en 76,839 s.

La matriz compara ambos frontends con datos y backend actuales y una demora
artificial de 400 ms. No compara commits de backend ni representa Render/red real.
La medida de dos frames es una cota de presentación, no el instante exacto del
píxel pintado. Las trazas locales no identifican la causa de los 20 segundos del
despliegue real.


## Archivos, riesgos y siguiente paso

- Backend: `apps/sales/cart.py`, `models.py`, `services.py`, `checkout.py`,
  `views.py`, `urls.py`, migración `0007` y tags `templatetags/cart_display.py`.
- Frontend: `static/js/sales_cart.js`, estilos `static/css/sales_tpv.css`,
  `sale_workspace.html`, `sale_line_form.html` y parciales de producto, línea,
  editor y checkout. `sales_tpv.js` se conserva para las funciones existentes.
- CI: `.github/workflows/ci.yml` añade el módulo al job de navegador existente;
  no cambia jobs de despliegue.
- Pruebas: protocolo y fixtures de checkout en `apps/sales/tests/integration/`,
  `apps/sales/tests_postgres_cart.py`, `e2e/browser_optimistic_cart.py`.
- Medición: `tests/performance/optimistic_cart_matrix.py`. El generador HTTP
  existente `diagnostic_matrix.py` incorpora la revisión requerida por checkout.
- Diseño histórico, este informe y muestras/percentiles en
  `docs/performance/tpv-optimistic-cart-measurements.json`.

Persisten las esperas de confirmación HTTP y de inventario/cobro; esta fase quita
su dependencia para la respuesta visual del carrito. Un conflicto requiere una
decisión explícita; no se promete fusionar intenciones incompatibles entre
pestañas. El almacenamiento local tiene la vida de la pestaña y no es una copia
de seguridad de intenciones sin confirmar. Los recibos del servidor no caducan.

La agrupación reduce filas visibles y combina cantidades compatibles, conservando
los snapshots subyacentes. No se agrupan a ciegas todos los añadidos en una sola
mutación: cambiar su granularidad podría alterar redondeos o precios históricos.
La cola secuencial conserva seguridad, por lo que una ráfaga larga todavía puede
tardar en quedar confirmada aunque se vea inmediatamente.

Siguiente paso recomendado: validar esta rama en staging con latencia y
configuración representativas y capturar la traza del despliegue real. La causa
de los 20 s sigue sin estar identificada; estas mediciones no permiten atribuirla
a red, cola, locks o renderizado en producción.


Commits funcionales: `1002cc0` (protocolo, modelos e interfaz) y `752ad68`
(recuperación de pendientes, orden estable, validación local e integración CI).
El commit de documentación incorpora diseño, instrucciones y muestras.
