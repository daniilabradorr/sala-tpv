# Fase 2A — plan previo a la implementación

Fecha: 2026-10-20. Rama `perf/tpv-inventory`, desde `94a10e3`.
No hay cambios funcionales al redactar este plan. Instrumentación 1.5 intacta.

## Fuentes revisadas

- [Master backend citado por el repositorio](https://drive.google.com/file/d/1m6JcYr1zbqNberV4C8H51pQ-HKQVrfQp/view), leído mediante Drive:
  `TPV_Backlog_backend_detallado_Verifacti_Verifactu_HASH_COMPLETO.docx`,
  modificado 2026-06-08. Bloques 8/10 y reglas enable_stock_control,
  allow_sale_without_stock, track_stock, aislamiento por tienda, restock.
  No se afirma equivalencia con otras revisiones numeradas del Master.
- `apps/inventory/README.md`, `apps/sales/README.md`, servicios/modelos/tests
  de ambos dominios y contratos de recepción de `apps/purchases/README.md`.
- Resultados crudos fase 1.5 y `tests/performance/DIAGNOSTIC.md`.

## Coste confirmado

complete_sale consulta una InventoryItem por línea; decrease_stock la relee y
bloquea con relaciones. Su save y el de StockMovement ejecutan full_clean.
En PostgreSQL 16 / Django 5.2.12, decrease_stock genera 31 operaciones SQL
por línea. Cinco CheckConstraint causan quince de ellas: Q.check crea su
savepoint, evalúa una condición y libera el savepoint. Hay además lecturas FK,
validación de unicidad y las dos escrituras indispensables.

## Cambios previstos

1. Precargar una vez las InventoryItem activas de business/store para los
   productos físicos controlados. Solo cargar PK/product_id: decrease_stock
   sigue releyendo y bloqueando la fila autoritativa en cada invocación.
2. En InventoryItem y StockMovement, agrupar únicamente CheckConstraint estándar
   al validar constraints. La conjunción verifica todas sus condiciones en una
   consulta. Si no se puede evaluar (campos excluidos) o hay una infracción,
   ejecutar las validaciones individuales originales para conservar mensajes,
   códigos y agregación de errores. UniqueConstraint sigue validándose siempre.
3. Mantener completas las validaciones de campos, FKs, clean, unicidad y checks
   de BD. No usar bulk_create/bulk_update/update ni saltar save o señales.
4. Conservar transacciones, savepoints del servicio y bloqueos existentes.
   No estrechar locks sobre relaciones en esta fase: implicaría estudiar aparte
   cambios concurrentes en configuración/catálogo. Orden de Sales intacto:
   Sale → CashSession → SaleLine por producto/PK → InventoryItem por producto.
5. Duplicados de producto no se fusionan: cada SaleLine conserva su movimiento,
   stock_before/after acumulativo y FKs. Cada decrease_stock vuelve a leer bajo
   lock; no hay caché compartida ni reutilización tras rollback.

Las firmas públicas complete_sale/decrease_stock y su contrato entre módulos
no cambian. La agrupación de checks es interna a Inventory; las demás rutas
siguen pasando por sus save/full_clean, con tests de equivalencia y regresión.
No tocar Billing, Payments, frontend ni reglas fiscales.

## Validación antes de cerrar

- Matriz 1/20/50, producto repetido, reserva, stock insuficiente/negativo,
  control desactivado/producto no controlado, inactivo/ficha ausente, tenants.
- Idempotencia, movimientos por línea, signals/save, fallo tras primera línea,
  rollback y reintento. Comparación de errores agrupados con Django original,
  incluidos exclude, FK inválida, checks y UniqueConstraint.
- PostgreSQL: ventas distintas, dos cajas, mismo ticket repetido, stock
  limitado y productos en órdenes inversos; ninguna cantidad perdida/oversell.
- Regresiones Sales/Inventory/Purchases/devoluciones/restock y gates de locking.
- Benchmark BEFORE/AFTER en mismo PostgreSQL 16 efímero, misma máquina y
  datasets/harness/worker/flags; diez muestras HTTP + warmup, sin otra carga.
  Conservar JSON crudo y comparar SQL, inventario, checkout p50/p95. Repetir
  baseline después si hay ruido. No usar el histórico de otra sesión como
  prueba de mejora. No afirmar resuelta la demora del despliegue.

## Riesgos a vigilar

La agrupación usa la misma semántica Q.check de Django 5.2 y su mapa de
expresiones de campos; es una dependencia a verificar al actualizar Django.
Errores recorren una validación adicional antes del fallback. La precarga usa
memoria O(productos distintos). Se conservan los locks amplios actuales, por lo
que no se promete resolver contención entre terminales. La seguridad precede
a reducir las consultas restantes.
