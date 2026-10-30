# Fase 3 — Implementación E-P01: restricción temporal a EUR

Trabajo sobre `fix/tpv-checkout-audit-phase3`, base `ad110fe46b777bf7522444ed72353fdba5177128`. Autorización: impedir nuevas inconsistencias monetarias; sin migraciones, conversión, cambio fiscal ni publicación. Se leyeron íntegramente los hallazgos e informe E y la revisión global. Los doce archivos locales de E se copiaron y se registraron sus SHA-256 antes de editar.

## Política y fuente autoritativa

`apps/business_config/currency.py` consulta `BusinessProfile.currency_code` en la base de datos, sin utilizar la relación `business.profile` que puede estar en caché. Solo el valor exacto `EUR` habilita escrituras monetarias. No se normalizan ni actualizan valores históricos al leerlos.

El contrato anterior de un Business sin BusinessProfile es EUR implícito: no existe otra fuente de moneda y las operaciones usan el valor predeterminado EUR. Se conserva ese caso, sin crear un perfil automáticamente; se prueba expresamente. Un perfil presente con USD, GBP, JPY, valor vacío o cualquier valor distinto de EUR bloquea las operaciones. Este fallback no demuestra la moneda de datos importados mediante SQL ni sustituye una revisión de esos datos.

El modelo BusinessProfile valida creación y cambios mediante `clean`/`full_clean`/`save`, de modo que formulario, servicios y Django Admin comparten la regla. EUR→USD se rechaza. Un perfil histórico no EUR puede conservar su moneda y editar datos no monetarios; cambiar su moneda, trasladarlo a otro Business o eliminarlo mediante `delete()` se rechaza. Admin impide borrar perfiles no EUR y rechaza íntegramente una selección colectiva que los contenga, ya que esa ruta elude `Model.delete`. El borrado EUR mantiene su contrato anterior.

No se cambia un símbolo para aparentar conversión. No se crean perfiles, pagos, movimientos ni documentos como reparación automática.

## Inventario real de entradas

| Área | Fuente / escritura existente | Restricción |
|---|---|---|
| Business y alta | Business no tiene moneda; onboarding crea su configuración expresamente en EUR | Alta de BusinessProfile solo EUR; servicio de configuración y modelo rechazan USD |
| Store | No tiene moneda independiente | Toda operación monetaria de tienda usa el Business propietario; se conservan controles de pertenencia y permisos |
| Settings | POSSettings no tiene moneda; BusinessProfileForm expone currency_code | Formulario explica la restricción; validación autoritativa del perfil también en POST directo y Admin. Campos extra de otros formularios no asignan moneda |
| Sales | Sale, SaleLine, SaleReturn, SaleReturnLine no guardan moneda | Guards en validación de modelos impiden crear/guardar operaciones no EUR. Checkout valida antes de llamar T1 y Sales antes de descontar stock; los comandos conservan sus transacciones y guards de modelo como segunda barrera |
| Payments | Payment no guarda moneda | Validación de moneda en cobro, devolución, deuda de venta y cancelación pendiente; guard de modelo. No se crean pagos para reparar Billing |
| Caja | CashSession, CashMovement, CashCount no guardan moneda | Guards de modelo bloquean apertura, movimientos, arqueos y cierre con nuevos importes; no se reabre ni reasigna una sesión histórica |
| Billing | Documentos, líneas, grupos y relaciones sin snapshot de moneda | F1/F2, F3 y rectificativas validan moneda antes de emitir, después de resolver el replay autorizado de un documento existente. Guards de modelo mantienen la barrera al guardar |
| Cuenta de cliente | CustomerAccount y CustomerAccountEntry | Guards impiden nuevas escrituras de saldo, límites monetarios y apuntes no EUR; contactos históricos siguen consultables |
| Compras | Purchase, PurchaseLine, PurchaseReceipt, PurchaseReceiptLine | Guards de modelo impiden nuevas escrituras económicas no EUR; no se cambian importes ni recepción histórica |
| Catálogo | Product.base_price / cost_price | Creación y cambio de precios requieren EUR; metadatos sin cambio de precios pueden conservarse |
| Inventory | StockMovement.unit_cost opcional | Si hay coste monetario requiere EUR. No se optimiza Inventory ni se cambian cantidades, cálculo o locks |
| Reportes | Selectores de lectura; CSV de ventas | Lecturas conservadas; aviso contextual para no EUR, también como fila informativa del CSV sin modificar sus cifras. CSV EUR mantiene su formato |
| Impresión | Plantillas con €; no existe moneda documental persistida | No se reetiquetan los importes. Reimpresión con aviso visible sobre moneda no verificable, sin escritura ni nueva numeración |

No existe una API REST independiente de moneda en estas áreas. Los comandos HTTP/HTMX usan los servicios y modelos anteriores. Payment Admin no permite alta ni borrado y tiene campos de solo lectura; Sales, CashRegister y Billing no tienen modelos registrados. Compras usa Admin de solo lectura; el perfil y los precios editables tienen validación de modelo. La restricción sigue los contratos reales, sin inventar una nueva API.

## Recuperaciones e historia

| Estado no EUR | Comportamiento | Recuperación autorizada ahora |
|---|---|---|
| Venta abierta o parcialmente completada | Bloqueo de nuevos efectos de venta/inventario económico/pago | Consultar y conservar el estado; ninguna conversión o reasignación |
| Sale completed, pago parcial, sesión histórica cerrada (P02) | Bloqueo del nuevo Payment incluso si se elige una sesión válida distinta | Consultar Payments persistidos, UUID, importes y sesiones; la parte pendiente requiere propuesta adicional |
| Sale completed/paid/pending=0, documento pendiente (P01) | Bloqueo de nueva emisión; no se repite ningún Payment | Conservar venta, pagos, UUID y series. Una emisión segura exige establecer primero la moneda histórica con autorización adicional |
| Documento ya emitido, mismo UUID e identidad compatible | Billing puede devolver el documento existente después de los controles actuales de autorización e identidad | Lectura sin nueva fila, número, Payment ni movimiento |
| Reintento de Payment confirmado | Se bloquea en no EUR, porque el servicio puede reparar deuda además de devolver Payment | Consultar el pago existente; no regenerar UUID ni repetir cobro |
| Documento emitido / histórico de caja y pagos | Lectura autorizada y reimpresión con aviso; datos persistidos intactos | Consulta; el aviso no certifica que el documento sea válido en EUR o en la moneda configurada |

Para cualquiera de los pendientes: identificar Business/Store/Sale/Payments/sesiones/documentos y claves originales, conciliar importes persistidos y evidencias externas sin cambiarlos, y presentar una propuesta de recuperación concreta. Si exige transformar historia, añadir snapshots de moneda, rectificar documentos o alterar numeración/contabilidad, necesita autorización adicional. E-P01 no implementa ese procedimiento de transformación. Tampoco cierra automáticamente una caja antigua no EUR con nuevos arqueos.

## Transacciones, concurrencia y límites de defensa

No se añaden locks ni fronteras transaccionales. Las lecturas de moneda se realizan dentro de las rutas existentes. Los escritores de configuración admitidos ya no pueden cambiar EUR a no EUR, ni trasladar o borrar un perfil histórico no EUR; por ello no se necesita un nuevo protocolo de locks para coordinar una transición monetaria ahora prohibida. Los rechazos se propagan como ValidationError a las respuestas actuales.

EUR conserva importes, impuestos, redondeos, numeración, fingerprints y claves. La nueva validación añade SELECTs; no se afirma equivalencia de rendimiento ni se optimizan Billing/Inventory.

QuerySet.update/bulk_update/bulk_create, SQL y roles privilegiados pueden eludir `save`/`clean`, como ya documentó E-H02. No son los escritores monetarios de producción encontrados en este recorrido; las inserciones masivas de los datasets son exclusivamente sintéticas. La simulación de perfiles legados en tests usa deliberadamente QuerySet.update, identificada como fixture. No se presenta la restricción de aplicación como constraint de BD; E-P02 y posibles migraciones siguen pendientes de autorización.

## Archivos

- Política y configuración: `apps/business_config/{currency.py,models.py,forms.py,admin.py}`.
- Guards: `apps/{sales,payments,cash_register,billing,customers,purchases}/models.py`, `apps/sales/{services.py,checkout.py}`, `apps/payments/services.py`, `apps/billing/{services.py,views.py}`, `apps/catalog/models.py`, `apps/inventory/models.py`.
- Avisos de consulta/impresión/exportación: `apps/core/context_processors.py`, `config/settings/base.py`, `templates/base.html`, `templates/includes/currency_warning.html`, `templates/billing/document_print.html`, `apps/reports/views.py`.
- Pruebas: `apps/business_config/tests/test_currency_policy.py`, `e2e/browser_currency_policy.py`; presupuestos de consultas en `tests/performance/test_queries.py` con límite anterior para consultas ajenas a moneda y coste monetario separado; adaptación de la sonda E02 en `tests/performance/phase3_billing_audit.py` a la corrección ahora autorizada. Su evidencia original permanece intacta en los entregables E.
- Entrega: este documento, `tpv-phase3-e-p01-report.md` y actualización de `tpv-phase3-final-review.md`.

Los cambios de catálogo y navegador que ya pertenecían a E se conservan; no se atribuyen a E-P01. El informe de validación distingue ejecuciones nuevas de resultados históricos.

No se puede reconstruir una moneda histórica a partir de un perfil que ya hubiera sido cambiado antes de E-P01, ni de importaciones sin procedencia verificable. El caso EUR implícito sin perfil conserva el contrato anterior, no acredita la moneda de una importación. Para operación real debe existir configuración fiscal válida y revisarse cualquier antecedente dudoso; E-P01 no certifica ese legado.
