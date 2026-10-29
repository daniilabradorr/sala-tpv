# Fase 3, Bloque C — integridad y recuperación

Base verificada: `453e9c61de9c2a61b0c628c8e966b1c4983b03fc`; rama `fix/tpv-checkout-audit-phase3`; origin/main `cdbf88c7df6b5c9d75ccdeda84c8ac8b67b03983`. Los once archivos sin commit de B se preservan por hash. No se incorpora main ni se crea otra rama.

## Matriz inicial de estados reales — antes de modificar código

Fuentes: `apps/sales/models.py:12`, `:30`; `apps/payments/models.py:41`; `apps/billing/models.py:31`; `apps/sales/checkout.py:68`, `:218`; `apps/payments/services.py:285`; `apps/billing/services.py:722`.

| Situación | Sale.status | Payment.status y payment_status | pending_amount | CashSession | Stock/movimientos | Billing esperado | Identidad | UI/acción segura |
|---|---|---|---|---|---|---|---|---|
| Antes de cobrar | open | Sin Payment / unpaid | total | open si exigida | Sin salida por cierre | Ausente | UUID formulario de pago/partes y Billing; cart UUID separados | Confirmar tras validar carrito |
| Fallo en T1 | open tras rollback | Sin Payment / unpaid | total | Contexto persistido | Ninguna salida de T1 | Ausente | Se conserva intención para replay | Corregir y reintentar |
| T1 confirmada, T2 pendiente | completed | Sin Payment completed / unpaid | total | open o cerrada entre commits | Una salida por línea física controlada | Ausente | UUID de pago aún no confirmado | Consultar; recuperar cobro, sin completar Sale otra vez |
| Split parcialmente confirmado | completed | Primera parte completed / partial | restante > 0 | Puede cerrar entre partes | Stock ya descontado una vez | Ausente | Cada parte conserva su UUID; no es el UUID del formulario principal | Consultar; replay compatible de las partes |
| T2 confirmada, T3 falla | completed | Payment(s) completed / paid | 0 | Histórica; puede cerrar | Stock aplicado | Ausente; borrador/número de T3 fallida revierten | Payment conserva UUID; Billing mantiene intención/fingerprint | Mostrar pago; emisión pendiente, H01 funcional pendiente |
| T3 confirmada, HTTP perdido | completed | completed / paid | 0 | Histórica | Stock aplicado | issued del tipo esperado | Documento/Payment conservan identidad | GET de estado; éxito, imprimir; no otro cobro |
| Resultado desconocido en UI | No es un estado persistido | No se deduce de timeout/500 | Desconocido hasta GET | Desconocida para UI | No asumir rollback | No asumir ausencia | Conservar intención; no UUID nuevos automáticos | Aviso desconocido y consulta autorizada antes de reintento |
| Finalizada | completed | completed / paid | 0 | Histórica | Una salida por línea | issued esperado F1/F2 | Identidades inmutables de efectos confirmados | Imprimir/nueva venta |

Discrepancias con la matriz conceptual: Sale tiene además draft/cancelled/returned; Payment tiene pending/failed/cancelled, pero register_sale_payment inserta completed, sin un estado persistido “processing” del checkout. Sale.payment_status también admite refunded. Billing tiene draft/issued; “pendiente de emisión” puede ser ausencia, no un estado nuevo. complete exige estado completed + paid + pendiente cero + issued del tipo solicitado. Stock puede no moverse con control desactivado/servicio/no track_stock. La sesión histórica de Sale puede diferir de la sesión válida de un pago recuperado por Payments: B lo ensayó; C no reasigna sesiones.

## Fronteras auditadas

T1: atomic de run_checkout, lock Sale, comprobación de versión, estado y preflight; complete_sale e Inventory anidados, lock sesión antes de stock, SaleLine ordenadas y InventoryItem; totales, completed y auditoría. Error revierte toda T1.

T2: cada register_sale_payment atomic independiente, lock Sale, autorización/método/UUID, sesión cuando asociada, saldo autoritativo, Payment, CashMovement físico, estado económico, cuenta cliente y auditoría. Una segunda parte fallida no revierte la primera.

T3: issue_sale_document atomic independiente, lock Sale, autorización/UUID/fingerprint, snapshots, hijos, lock BillingSeries y numeración, issued y auditoría. Fallo revierte T3, no T1/T2. Render fuera de estos commits puede fallar tras éxito económico. Muerte de proceso: transacción abierta revierte; commits anteriores permanecen. La muerte real de worker no se ensaya; se verifican fallos controlados entre fronteras durables. Esta arquitectura permanece intacta.

Cierre: cash_register.services.close_cash_session toma lock de sesión y confirma cierre/count/auditoría en su atomic. No hay reserva persistida de “checkout en vuelo” que abarque T1/T2. Recuperación utiliza los servicios existentes, con sus locks/permisos; no se crea una transacción global.

## Decisiones previas a cambios

| ID | Problema | Causa | Propuesta | Cambia contrato | Autorizado |
|---|---|---|---|---|---|
| H01 visual | Error de método oculto cuando paid | Campo oculto y bloque de errores condicionado a pendiente | Resumen accesible de errores y enlace GET de estado | No | Sí: presentación/tests |
| H01 funcional | is_valid rechaza método histórico antes de emisión | CheckoutForm usa métodos activos; vista valida antes de run_checkout | Recuperación solo emisión determinada en servidor bajo autorización y lock | Sí: altera decisión/contrato | PENDIENTE DE AUTORIZACIÓN |
| R01 | Timeout/abort/500 sin recuperación segura | Resultado incierto y eventos no cubiertos | Feedback, conservar intención, consulta GET existente y replay explícito | No modifica backend | Sí: frontend/tests |
| R03 | Cierre entre commits | Sesión puede cerrar entre T1 y T2 | Flujo explícito de pago pendiente en sesión válida | Requiere diseño de dominio/operación | PENDIENTE DE AUTORIZACIÓN |
| H02/H03 | Trabajo repetido/por línea | Medido en B | Optimización posterior separada | Por determinar | No |
| H04 | Validaciones fiscales tardías | Estado parcial durable previsto | Evaluar preflight informativo y revalidación fiscal | Puede cambiar contrato | PENDIENTE DE AUTORIZACIÓN |

La matriz anterior se escribió antes de editar aplicación; los resultados se detallan a continuación.

## Identidad y protecciones existentes

CartOperation conserva un recibo/fingerprint por Sale y UUID de operación de carrito; no identifica un cobro ni una emisión. Un replay de carrito ya confirmado no se trata como una operación nueva aunque la versión haya avanzado. UUID/payload distinto produce conflicto en el test de contrato.

Payment (`apps/payments/services.py:151`, `:285`) bloquea Sale y compara UUID por Business y compatibilidad de Sale, método, tipo, importe, devolución y sesión. El saldo autoritativo impide cobrar de nuevo con una clave distinta cuando ya está pagada. Un método inactivo o un usuario sin permiso actual puede bloquear incluso un replay; el UUID no sustituye autorización. External_reference no forma por sí sola el contrato de identidad comparada.

Billing (`apps/billing/services.py:299`, `:671`, `:722`) bloquea Sale y serie; mantiene identidad/fingerprint, comprobación de documento inicial existente, numeración y atomicidad de snapshots/emisión. Dos ventas comparten serie sin compartir número; dos claves no permiten dos documentos iniciales de la misma venta en las pruebas. El servicio puede devolver documento histórico con serie inactiva; el formulario HTTP puede rechazarlo antes. No se cambian hashes, impuestos o encadenamiento fiscal.

Inventory (`apps/sales/services.py:1004`, `:1050`, `:1067`; `apps/inventory/services.py:514`) queda dentro de T1, con bloqueo de Sale, líneas y existencias. Reintentar una venta completed no repite complete_sale. C04 prueba la última unidad entre ventas y sesiones distintas, con stock final cero y una sola salida; no basta la inspección del lock como evidencia de carrera.

En el checkout ya completo, la versión se comprueba antes del retorno temprano; después puede responder éxito sin consumir todas las intenciones remitidas. No se debe afirmar que todo POST tardío incompatible es rechazado: el rechazo probado corresponde a los servicios y rutas que sí consumen esa intención. P01 requiere definir esa compatibilidad explícitamente antes de cambiarla.

## Fallos reproducidos y consecuencias

- H01: Payment confirmado + Billing fallida + método desactivado produce422 antes de emisión. La corrección aplicada hace visible el error oculto; no cambia esa decisión del formulario.
- R01: timeout, abort, respuesta perdida después de T1/T2/T3 y500 tras render con commits durables. El cliente no conoce rollback ni éxito hasta leer; la UI ya no afirma rechazo ni habilita repetición ciega.
- R03: cierre tras T1 deja completed/unpaid, stock aplicado, Payment0, documento0; cierre entre partes deja Payment1/partial. Durante T1 el closer espera lock, pero puede cerrar después de ese commit. La recuperación visible completa con otra sesión no está implementada.
- Billing fallida después de Payment no borra el cobro; T3 fallida revierte su número/documento y T1/T2 permanecen. Los replays ensayados no duplican efectos. Un fallo de render después de T3 mantiene documento emitido y GET lo presenta como éxito.

Riesgo operativo: cajero puede entregar bienes de una venta completed aún unpaid, o repetir una intención sin conocer su resultado. Riesgo económico/fiscal si una futura recuperación altera claves, mezcla partes confirmadas con pendientes, escribe sobre sesión cerrada o sustituye una serie incompatible. Los cambios de este bloque no implementan esos atajos. No se ha reproducido doble cobro, doble salida ni documento inicial duplicado en las carreras ejecutadas; esto no prueba todas las planificaciones y servicios externos posibles.

## Correcciones implementadas dentro del alcance

1. `static/js/core/checkout-recovery.js`: journal de intención en sessionStorage por usuario/Business/Store/Sale, allowlist sin CSRF/cookies/credenciales, memoria de respaldo si storage está bloqueado. Conserva claves de pago/partes/Billing, versión y payload; solo POST explícito tras GET autorizado. Journal dañado o acción discordante bloquea formulario. Los datos del navegador nunca autorizan omitir controles económicos.
2. `static/js/core/htmx-events.js`: feedback honesto para timeout/sendError/sendAbort/500, limpieza de processing/loading, bloqueo de submit mientras no se consulta, acción GET existente, limpieza de feedback asociada a operación/contexto. No hay polling ni POST automático.
3. `_checkout.html`: estado real de Sale, errores de campos ocultos y formset activo en resumen accesible; conserva los422. No se evalúa el formset split en modo single, para evitar validación incidental durante render. Venta cancelled no muestra formulario de cobro.
4. `checkout.html`: contenedor `#checkout-panel` para que la consulta HTMX también funcione en página standalone después de recarga.
5. Tests permanentes de presentación/HTTP/PostgreSQL/Chromium. E2E existentes adaptados a consulta antes del retry; selector opcional TPV_CHROMIUM usa Chromium instalado sin añadir dependencia ni cambiar comportamiento normal de CI.

Tras la consulta: paid sin documento muestra emisión pendiente; partial conserva partes originales; unpaid advierte que el POST anterior puede seguir activo; complete muestra documento y permite imprimir/nueva venta sin otro POST. El replay explícito conserva exactamente la intención original: un conflicto de versión o método desactivado sigue siendo decisión del servidor. Un500 no se traduce en cobro rechazado. El efectivo entregado/cambio no persistido no se reconstruye desde GET.

## Evidencia, regresiones y pendientes

La matriz detallada, HTTP y persistencia están en `tpv-phase3-block-c-scenarios.md`; evidencia numérica sintética en `tpv-phase3-block-c-evidence.json`; comandos, resultados finales y Git en `tpv-phase3-block-c-report.md`. C01–C10: tres repeticiones por escenario; seis posiciones de cierre; contratos de identidad; 27 ejecuciones Chromium sobre1440/820/390 y doble submit.

P01/H01 funcional y P02/recuperación de caja quedan **PENDIENTES DE AUTORIZACIÓN**. P03/H02-H03 y P04/preflight fiscal son propuestas separadas. Pseudocódigo, riesgos, compatibilidad y tests de aceptación están en `tpv-phase3-block-c-proposals.md`. No hay cambios de servicios, views/forms del backend, locks, límites de commits, numeración, constraints ni migraciones.

## Limitaciones y fuentes

Se contrastaron A y los tres informes B, incluido JSON de84 muestras/12 escenarios y los728 tests comunicados con su base. Medianas de tarjeta/F2 verificadas: POST274/588/1146ms para1/20/50 líneas; Inventory18/269/645, Payments48/39/41, Billing54/139/289ms (redondeados). Son tramos solapados; no se suman. El incidente original de unos20s sigue sin reproducirse espontáneamente; una pausa inyectada de20,98s no acredita causa de producción.

No estaban disponibles los dos DOCX maestros ni el checklist maestro; no se inventa contenido. No hay pruebas sobre producción, red fiscal real, TPV físico, procesos terminados por SIGKILL, caída física de PostgreSQL ni navegadores distintos de Chromium. Los fallos se inyectan en fronteras; no equivalen a ensayar todas las interrupciones de proceso. sessionStorage conserva intención dentro de pestaña; con almacenamiento bloqueado la memoria no sobrevive recarga. Las garantías económicas sin JS siguen siendo las del backend y se comprueban por HTTP/servicios; el journal es una protección de interacción, no una autoridad económica.
