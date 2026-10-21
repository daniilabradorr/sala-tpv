# Fase 2A — inventario durante el cobro

Implementación: `dfabec1`, desde diagnóstico `94a10e3`, rama local
`perf/tpv-inventory`. Sin push, merge, despliegue ni cobros/documentos reales.
Plan previo: `tpv-inventory-plan.md`. Suite final y comparación A→B→A completadas.

## Cambio y límites de alcance

El cierre mantiene su secuencia: lock de Sale, contexto de caja, líneas ordenadas
por producto/PK, validación económica, inventario, estado y auditoría. Solo cambia
la búsqueda inicial de las fichas y la evaluación de constraints de inventario.

1. complete_sale filtra las mismas líneas físicas controladas y precarga
   identidades InventoryItem activas, siempre por Business/Store/producto.
   No lee stock de esa precarga. Evita el orden por nombre de producto al ordenar
   explícitamente por product_id/PK y solo obtiene PK/product_id.
2. decrease_stock, sin modificar su firma ni implementación, relee y bloquea
   cada ficha y sus relaciones. Verifica activo y stock disponible incluyendo
   reservas, respeta allow_negative y guarda InventoryItem y StockMovement.
3. InventoryItem y StockMovement conservan save/full_clean. Sus CheckConstraint
   estándar comparten una evaluación de la conjunción por objeto, con semántica
   NULL de Django y un savepoint de validación. Todas las condiciones se evalúan.
4. Si una condición falla o no puede evaluarse, se ejecutan las validaciones
   individuales originales; UniqueConstraint siempre sigue su recorrido original.
   Errores SQL o de lectura de resultados no aprueban un grupo: se vuelve al
   recorrido individual. No hay caché de validaciones entre objetos/transacciones.

No se usan bulk_create, bulk_update ni QuerySet.update en la implementación.
No se omiten campos/FKs, model.clean, señales, validación de unicidad ni checks
en la base de datos. No hay cambios de contratos entre módulos ni migraciones.
Compras/devoluciones siguen usando sus servicios y se verifican en regresión.
Billing, Payments, frontend, settings y herramientas 1.5 permanecen intactos.

## SQL eliminado del recorrido válido

- Búsqueda inicial por línea: N consultas → una por venta con stock controlado.
- Cinco checks por línea (tres de ficha y dos de movimiento): cinco SELECT y
  diez comandos de savepoint → dos SELECT y cuatro comandos de savepoint.
- Ahorro esperado: 9N operaciones en decrease_stock + N−1 búsquedas en Sales.
  Las transacciones del dominio y el savepoint de decrease_stock no cambian.
- No se fusionan líneas de un producto: mantienen movimiento, FK SaleLine y
  stock_before/after acumulativo. La relectura por línea evita usar stock obsoleto.

## Tests y comprobaciones

Versión final: 1.576 tests Django, todos OK en PostgreSQL 16, sin skips declarados
en el resumen. Log: work/tpv-inventory/full-suite-final.log, 190,354 s.

Nuevas pruebas incluyen:

- 1/20/50 productos, stock reservado, insuficiente y negativo permitido.
- Producto repetido, suma de cantidades y snapshots consecutivos por línea.
- Control desactivado y producto sin control: ninguna consulta a InventoryItem.
- Ficha inactiva/ausente, aislamiento por negocio/tienda y FKs a Sale/SaleLine.
- Reintento idempotente, fallo tras el primer movimiento, rollback y reintento.
- save/full_clean y pre_save/post_save por cada ficha y movimiento.
- Comparación de constraints con Model.validate_constraints de Django en límites,
  NULL, exclude, unicidad y errores SQL/lectura; conservación de mensajes/códigos.
- PostgreSQL real: dos ventas/cajas sobre mismo producto, última unidad, mismo
  ticket concurrente, órdenes inversos y cambio de stock confirmado tras precarga.
- Suite existente completa: compras/recepciones, devoluciones/restock, caja,
  checkout e idempotencia/concurrencia de los demás módulos.

Ruff check/format, Django check y makemigrations --check --dry-run pasan.

## Método de comparación

BEFORE: árbol funcional de 94a10e3, medido antes de modificar producción.
AFTER: implementación dfabec1. Misma máquina y contenedor PostgreSQL 16.15,
Python 3.12.12, Django 5.2.12, Gunicorn 25.1.0 sync (1 worker/1 thread),
Chromium 151.0.7922.173, conexión directa sin pooler, CONN_MAX_AGE=600.
No se ejecutan otras pruebas durante cada benchmark.

Harness 1.5 idéntico: tests.performance.diagnostic_matrix.BrowserMatrix,
TPV_DIAGNOSTIC_GUNICORN=1, TPV_DIAGNOSTICS=1, diez muestras + un warmup,
datasets sintéticos de 60 productos y tickets frescos de 1/20/50 líneas.
HTTP loopback, viewport 1440×900, recursos externos bloqueados en ambos casos.
Cada POST cobra efectivo exacto, completa stock/pago y emite documento ficticio;
se verifica el resultado persistido. No reutiliza una venta ya completada.

Los tiempos incluyen instrumentación igual en ambos lados. Las etapas son
inclusivas y no se suman; SQL incluye comandos de savepoint. El p95 de diez
muestras (nearest rank) es el máximo; no representa un SLO ni carga de producción.
No se usa el histórico de otra sesión para calcular la mejora.

## Comparación principal obtenida

Tiempos en ms. Cada celda muestra BEFORE → AFTER. Las etapas son inclusivas.

| Líneas | Inventory p50 | Inventory p95 | Checkout HTTP p50 | Checkout HTTP p95 | SQL total |
|---|---:|---:|---:|---:|---:|
| 1 | 17,91 → 15,17 | 28,49 → 18,73 | 292,55 → 267,20 | 334,80 → 323,90 | 334 → 325 |
| 20 | 310,95 → 283,66 | 362,69 → 330,35 | 647,55 → 636,90 | 737,30 → 760,90 | 1.078 → 879 |
| 50 | 770,34 → 676,03 | 1.312,93 → 889,82 | 1.265,60 → 1.175,00 | 1.925,20 → 1.480,60 | 2.248 → 1.749 |

En cincuenta líneas se eliminan 499 operaciones SQL (22,2% del total).
El interior de decrease_stock pasa de 31 a 22 operaciones por línea: 1.550 →
1.100 en ese ticket. Las búsquedas iniciales pasan de 50 a una. Billing conserva
431 operaciones y Payment 113; las demás operaciones de la matriz mantienen sus
contadores SQL. La comparación automática comprueba estas igualdades.

La mediana de inventario en cincuenta líneas baja un 12,2% y la de checkout un
7,2% en esta corrida. No se observa una mejora homogénea de todas las latencias:
el p95 de checkout con veinte líneas sube 23,6 ms (3,2%). Diez muestras no permiten
atribuir esa variación aislada a una regresión ni garantizar un SLO. La reducción
de SQL es determinista; las diferencias temporales se presentan como mediciones
locales; la repetición siguiente cuantifica parte de su variabilidad.

### Repetición de control A→B→A

Se ejecutó de nuevo el harness idéntico de 94a10e3 desde un worktree separado,
con las mismas dependencias, .env y estáticos, y el mismo contenedor PostgreSQL.
Diez muestras + warmup; sin tests simultáneos. El worktree no incorpora la
optimización y vuelve a obtener exactamente 334/1.078/2.248 operaciones SQL.

| Líneas | HTTP p50 A1 / B / A2 | HTTP p95 A2 | Inventory p50 A1 / B / A2 |
|---|---:|---:|---:|
| 1 | 292,55 / 267,20 / 286,55 | 392,40 | 17,91 / 15,17 / 17,02 |
| 20 | 647,55 / 636,90 / 719,55 | 845,90 | 310,95 / 283,66 / 345,70 |
| 50 | 1.265,60 / 1.175,00 / 1.386,10 | 2.043,10 | 770,34 / 676,03 / 846,52 |

B está por debajo de ambas medianas de baseline en estos escenarios. Aun así,
la variación A1→A2 en HTTP de cincuenta líneas es 9,5%, mayor que el 7,2% de
diferencia A1→B. No se presenta ese porcentaje como efecto causal estable ni
garantía de latencia. La mejora confirmada es la reducción determinista de SQL;
las observaciones temporales locales son compatibles con una mejora, pero
requieren más repeticiones/carga real para cuantificar un efecto generalizable.

Evidencia compacta: `tpv-inventory-comparison.json`, con SHA de implementación,
entorno, distribuciones, contadores y SHA-256 de los tres JSON crudos. Evidencia
completa: `work/tpv-inventory/{before,after,before-recheck}/browser.json` y sus
logs Gunicorn/trazas. No se sobrescriben los resultados de fase 1.5.

## Reproducción

Seguir el arranque PostgreSQL efímero en tests/performance/DIAGNOSTIC.md usando
base tpv_diag_phase2a. Con el mismo contenedor y sin procesos de medida paralelos:

```sh
export TPV_TEST_DATABASE_URL='postgresql://tpv_diag:synthetic-local-only@127.0.0.1:55432/tpv_diag_phase2a'
export DJANGO_SETTINGS_MODULE=config.settings.diagnostic_postgres
export TPV_DIAGNOSTICS=1
export TPV_DIAGNOSTIC_GUNICORN=1
export TPV_DIAGNOSTIC_SAMPLES=10
TPV_DIAGNOSTIC_OUTPUT=work/tpv-inventory/after \
  .venv/bin/python manage.py test tests.performance.diagnostic_matrix.BrowserMatrix --noinput
```

Para BEFORE, ejecutar exactamente el mismo comando desde un checkout separado de
94a10e3, con salida distinta. Mantener los mismos estáticos/configuración y
dependencias; no ejecutar dos runners contra la misma test DB a la vez. Ambos
runners crean/destruyen su test_tpv_diag_phase2a y detienen Gunicorn/Chromium.
Los ficheros JSON originales están en work/tpv-inventory/before y after.

## Riesgos y siguiente paso

Los locks de Sale/CashSession/SaleLine/InventoryItem y de relaciones cargadas
siguen intactos, así como su orden. La precarga no bloquea; el estado de stock
solo se usa tras la relectura bloqueada. Se conserva la posible serialización
por locks amplios Business/Store/Product; esta fase no promete mejorarla.
Los tests cubren carreras concretas, no prueban ausencia universal de deadlocks.

La evaluación agrupada depende de Query y del mapa de expresiones de Django 5.2:
revisar al actualizar Django (el proyecto fija <5.3). Los errores ejecutan una
sonda adicional antes del fallback. Una venta usa memoria O(productos distintos).
Los demás flujos que guardan estos dos modelos también reciben la evaluación
agrupada, con las mismas validaciones y con regresiones cubiertas.

La latencia de ~20 s del despliegue sigue sin diagnóstico: faltan SHA desplegado
y trazas reales correlacionadas. Esta fase solo concluye sobre el entorno local.
No aplicar ni inferir cambios de configuración de producción a partir de ella.

Siguiente propuesta, fuera de esta fase: perfilar y diseñar validación compartida
de existencia de FKs dentro de Inventory, que conserva consultas repetidas de
Business/Store/Product. Debe preservar exactamente full_clean y sus errores,
aislamiento y protección transaccional, sin flags de confianza entre módulos.
No se implementa esa propuesta aquí. Para investigar los veinte segundos,
priorizar primero la traza del despliegue real preparada en fase 1.5.
