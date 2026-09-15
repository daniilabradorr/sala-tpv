# Reports: contrato arquitectónico

`reports` es la capa **read-only** de lectura y agregación de Netxodo. En el
MVP calcula resultados mediante consultas dinámicas sobre los modelos de dominio
que son fuente de verdad; no constituye una segunda contabilidad y no persiste
ejecuciones, métricas ni snapshots. La persistencia solo se reconsiderará ante
una necesidad real de rendimiento, precálculo o exports históricos.

## Límites obligatorios

Todo selector futuro:

- recibe un `Business` obligatorio y aplica ese tenant en todas sus consultas;
- admite `Store` como filtro opcional solo cuando el concepto lo permita y
  valida que pertenezca al mismo negocio;
- nunca mezcla datos de dos negocios;
- es read-only: no muta el dominio ni escribe snapshots;
- no usa `AuditEvent` como contabilidad ni fuente económica primaria;
- no obtiene fiscalidad definitiva de `Sale.tax_amount`, ni reconstruye el
  pasado con la configuración actual de `Product` o `Tax`;
- mantiene la lógica de informes fuera de los Django Templates.

Las fuentes autoritativas son `Sale`, `SaleLine`, `SaleReturn` y
`SaleReturnLine`; `Payment` y `PaymentMethod`; `CashRegister`, `CashSession`,
`CashMovement` y `CashCount`; `BillingDocument`, `BillingDocumentLine`,
`BillingTaxBreakdown` y `BillingDocumentRelation`; `InventoryItem` y
`StockMovement`; y `Supplier`, `Purchase`, `PurchaseLine`, `PurchaseReceipt` y
`PurchaseReceiptLine`.

## Periodos y zona horaria

Los filtros temporales usan datetimes aware y el intervalo semiabierto
`[start, end)`: inicio inclusivo y fin exclusivo. Las fechas de negocio de una
API son inclusivas y se convierten en medianoches locales; nunca se fabrica un
fin `23:59:59.999999`, se filtra mediante `__date` ni se presupone que un día
dura 24 horas. `periods.py` respeta la zona Django activa, incluidos cambios DST.

Cada hecho usa su propio timestamp. Una devolución no se desplaza a la fecha de
la venta, ni una recepción a la fecha del pedido.

## Semántica acordada

### Ventas, devoluciones, tickets y unidades

El histórico comercial incluye ventas con estado `completed` **o** `returned`.
Una venta totalmente devuelta sigue siendo una venta histórica; por ello
`status="completed"` nunca será la única base.

- `gross_sales`: suma de `Sale.total_amount` para esas ventas cuyo
  `Sale.completed_at` cae en el periodo.
- `returns_amount`: suma de `SaleReturn.total_amount` de devoluciones
  `completed`, según su propio `SaleReturn.completed_at`.
- `net_sales = gross_sales - returns_amount`.
- `ticket_count`: número de ventas originales completadas en el periodo. Una
  devolución no crea un ticket negativo y una venta devuelta sigue contando.
- `average_ticket = gross_sales / ticket_count`; sin tickets devuelve
  `Decimal("0.00")`. No se usa `net_sales` en este cálculo.
- `units_sold`: suma de `SaleLine.quantity` de las ventas del periodo comercial.
- `units_returned`: suma de `SaleReturnLine.quantity` de devoluciones completadas
  en su periodo de devolución.

Por ejemplo, una venta de 100 EUR el lunes y una devolución de 20 EUR el jueves
producen 100 EUR de bruto el lunes y 20 EUR de devoluciones el jueves. La futura
agrupación por categoría usará exclusivamente `SaleLine.category_source_id`,
`category_name` y `category_slug`, nunca la categoría actual del producto.

### Pagos

Solo cuentan pagos `completed`. `SALE_PAYMENT` es entrada económica y `REFUND`
es salida. Los métodos soportados por el dominio son `cash`, `card`, `bizum` y
`transfer`; no se inventa `other`. Mientras `Payment` no tenga un
`completed_at`/`processed_at` propio, el eje temporal es `Payment.created_at`.

Total cobrado no equivale a efectivo físico: un pago cash representa la
operación económica; `CashMovement` representa el movimiento físico.

### Caja

La autoridad del efectivo físico es `CashSession`, `CashMovement` y `CashCount`.
Las métricas distinguirán movimientos `sale_cash`, `refund_cash`, `cash_in`,
`cash_out` y ajustes de entrada/salida. `CashSession` aporta `opening_amount`,
`expected_cash_amount`, `counted_cash_amount` y `difference_amount`. La suma de
los cierres de varias sesiones no se denominará «efectivo actual».

### Billing y fiscalidad

La fiscalidad definitiva procede de documentos **emitidos** en
`BillingDocument` y de `BillingTaxBreakdown`, que aporta
`taxable_base_amount`, `tax_amount`, `tax_type`, `tax_rate` y clasificación
fiscal. Nunca procede de `Sale.tax_amount`. Las rectificativas ya almacenan
importes negativos: Reports no invierte de nuevo el signo.

El dominio contempla F1, F2, F3, R1, R2, R3, R4 y R5, con relaciones
`RECTIFIES` y `SUBSTITUTES`. Una implementación posterior separará
`document_counts` (histórico documental) de `effective_tax_totals` (importes
fiscales efectivos sin doble contabilización de documentos sustituidos).

El eje fiscal predeterminado es `BillingDocument.issued_at`. `operation_date`
solo podrá pedirse como eje alternativo explícito; nunca se intercambiarán de
forma silenciosa.

### Inventario

`InventoryItem` es el estado actual y `StockMovement` el histórico de
movimientos. No se reconstruye el stock actual sumando movimientos cuando ya
existe el estado autoritativo de `InventoryItem`.

### Compras y recepciones

`Purchase.ordered_at` fecha las métricas de compras/pedidos;
`PurchaseReceipt.received_at` fecha la recepción física. No se mezclan.
`ordered`, `partially_received` y `received` son estados de pedido confirmados;
`draft` y `cancelled` se excluyen del importe comprado confirmado.

La cantidad recibida procede de `PurchaseReceiptLine`/`quantity_received` y la
pendiente es `quantity_ordered - quantity_received`. No se modelan devoluciones
a proveedor hasta que el dominio tenga ese flujo.

## Implementado en PR 2

`selectors.py` implementa `sales_summary`, `sales_timeseries`,
`sales_by_store`, `sales_by_product`, `sales_by_category`, `payment_summary`,
`payments_by_method`, `cash_summary`, `cash_sessions_summary` y
`cash_session_summary`.

`cash_summary` agrega únicamente movimientos, aperturas y cierres ocurridos en
el periodo solicitado; sus totales de cierres históricos no representan el
efectivo actual. `cash_session_summary` describe la sesión completa.
`cash_sessions_summary` selecciona sesiones cuya vida operativa intersecta el
periodo (`opened_at < end` y cierre nulo o `closed_at >= start`), pero también
describe los movimientos completos de cada sesión, no solo la fracción que cae
en el periodo. La consulta de sesiones y la agregación de movimientos son bulk.

## Implementado en PR 3

`selectors.py` implementa `billing_documents_summary`, `tax_summary`,
`tax_by_rate`, `inventory_summary`, `inventory_movements_summary`,
`purchase_summary`, `purchases_by_supplier`, `purchases_by_store`,
`purchases_by_product` y `purchase_receipts_summary`.

Los informes fiscales usan exclusivamente documentos emitidos y los snapshots
autoritativos de `BillingTaxBreakdown`. Los importes efectivos excluyen el target
de una relación `SUBSTITUTES` cuando el documento source está emitido; el source
permanece. `RECTIFIES` no elimina el original y sus importes se agregan con el
signo ya almacenado. Los conteos emitidos conservan la historia documental. La
realidad fiscal efectiva es dinámica respecto al estado actual de las relaciones,
sin snapshots históricos «as of».

`inventory_summary` lee la foto actual de los `InventoryItem` activos. El
histórico procede de `StockMovement.occurred_at` y se agrupa por producto, tipo y
dirección; no se suman globalmente unidades heterogéneas. Los nombres y SKU de
los movimientos son labels actuales de `Product`, no snapshots históricos;
`product_id` es su identidad operacional estable.

Las compras confirmadas se fechan por `Purchase.ordered_at`, mientras que las
recepciones se fechan independientemente por `PurchaseReceipt.received_at`.
`purchases_by_product` usa los snapshots de la línea y muestra el fulfillment
acumulado actual del pedido, incluso si una recepción fue posterior al periodo
del pedido. `purchase_receipts_summary` representa, en cambio, los eventos de
recepción ocurridos dentro del periodo.

## API prevista para PR posteriores

- Dashboard: `dashboard_summary`.

Esta lista documenta nombres y alcance; no se reservan con stubs. VeriFactu no
existe en este contrato y no se crean modelos, DTOs, selectors ni placeholders.
