# NETXODO — Bloque E: hallazgos y propuestas

Base `ad110fe46b777bf7522444ed72353fdba5177128`, cierre30/10/2026 (Europe/Madrid). Las propuestas de dominio no están implementadas. [Auditoría](tpv-phase3-block-e-audit.md), [escenarios](tpv-phase3-block-e-scenarios.md) y [mediciones](tpv-phase3-block-e-measurements.json) conservan la evidencia. Ninguna prueba favorable se presenta como certificación legal.

## Hallazgos confirmados

| ID | Impacto | Evidencia | Estado |
|---|---|---|---|
| E-H01 | Alto para configuraciones no EUR | Formulario y `update_business_profile` aceptan USD; BillingDocument no guarda moneda; impresión muestra12,10€. Probe `E02-currency-mismatch-observed`, una venta/pago/documento y número1 | Defecto de aplicación confirmado; sin corrección monetaria autorizada |
| E-H02 | Alto si un writer elude los servicios | save/delete bloquean; QuerySet.update, bulk_update, SQL y borrado queryset de hijos eluden guards. Una inserción bulk que supera los constraints actuales admite segundo F2 de la misma Sale con otro número. Todo dentro de scopes revertidos | Límite de protección ya documentado en modelos, ahora medido. No se demuestra bypass por una vista pública; servicios actuales mantienen lock/exclusión |
| E-H03 | Límite funcional/fiscal | Billing admite IVA/régimen01/S1 sin exención ni recargo; catálogo más amplio. Casos no soportados se rechazan, incluso después del pago | Comportamiento autoritativo conservado; definir negocios/operaciones admitidos y procedimiento operativo |
| E-H04 | Dependencia externa/legal | No adapter/submission/registro/huella fiscal/encadenamiento/QR/ack/cancelación externa. ISSUED es interno, fingerprint es idempotencia | No implementado; no se inventa ni envía información externa |
| E-H05 | Coste medido | F2 de50 líneas:431 operaciones SQL; full_clean de líneas216,17ms inclusivos y creación de hijos261,83ms, T3 mediana316,87ms | Optimización posible por estudiar, sin omitir validaciones/locks |
| E-H06 | Semántica de primera emisión | Product/Tax se congelan en SaleLine, pero emisor/receptor se capturan al primer issue. Branding/logo/pie actuales se leen al imprimir | Contrato actual. Tras issue se conservan valores fiscales; no se promete reconstruir identidad de cliente anterior a issue |
| E-H07 | Cobertura comercial | Billing directo admite completed no pagada; checkout exige saldo cero. F3 y R1/R5 añaden documentos legítimos relacionados; R2/R3/R4 no tienen flujo automático | Distinguir contratos; confirmar política de facturación independiente/crédito; no imponer unicidad de todo documento por Sale |

## E-P01 — Acotar el MVP a EUR y tratar el legado monetario

**Prioridad alta. Requiere autorización.** Origen: `BusinessProfile.currency_code` es CharField expuesto sin opciones de moneda; el servicio de configuración lo persiste; Sale/Payment/Billing no conservan un contrato multidivisa equivalente y las vistas imprimen€.

Propuesta revisable, sin implementarla:

1. Definir explícitamente el MVP como EUR y validar ese límite en formulario **y servicio** de alta/actualización de configuración, con error visible. Una restricción solo HTML no es autoritativa.
2. Antes de habilitar negocios reales, inventariar de forma autorizada perfiles no EUR y ventas/documentos previos. No convertir importes ni asignar moneda histórica a partir del perfil actual.
3. Rechazar nuevas confirmaciones de ventas abiertas bajo configuración no soportada antes de T1/Payment. Delimitar el tratamiento operativo de ventas ya cobradas pendientes de emisión; no alterar silenciosamente P01/P02 ni bloquear su recuperación EUR válida.
4. Mantener impresión histórica como lectura y no reescribir documentos. Si se quiere multidivisa, diseñar aparte moneda/snapshots/conversiones/identidad y migraciones con datos históricos demostrados.

Pruebas propuestas: EUR vigente sin regresión; rechazo USD/GBP por formulario y llamada directa; ninguna salida de stock/pago/número ante nueva venta rechazada; perfiles legados detectados sin mutación; P01/P02 y reimpresión EUR intactas; operación pagada no EUR con procedimiento explícito. Criterio de aceptación: no aceptar una moneda y etiquetar silenciosamente otra. Este bloque solo aporta la reproducción, no toca `apps/business_config`, Sales o Billing de aplicación.

## E-P02 — Protección de historia frente a escrituras fuera del contrato

**Requiere autorización de modelos/migraciones/transacciones y diseño previo.** Los guards actuales son útiles y las rutas de emisión/lectura probadas los respetan. No hay evidencia de que una vista pública permita hacer las escrituras bulk de la sonda. El límite importa ante comandos, futuros writers o acceso SQL con privilegios.

Propuesta: inventariar todos los writers y permisos del rol DB; definir bloqueo de UPDATE/DELETE de issued y sus hijos/relaciones en BD, sin impedir construcción del draft y transición atómica a issued. Los privilegios de un administrador/superusuario DB quedan fuera de una garantía absoluta de estos guards: el diseño debe definir rol y amenaza. Estudiar defensa adicional de unicidad del inicial F1/F2 por Sale. No imponer unique(Sale) a cualquier BillingDocument: F2→F3, rectificativas y F3 complementarias son historias legítimas. El diseño debe preservar también tenant, numeración y mantenimiento autorizado.

Pruebas propuestas: save/delete/queryset/bulk/SQL rechazados para históricos; campos y relaciones protegidos; transacción de emisión y auditoría funcional; F3/R1/R5 y compañero F3 conservados; rollback número y carreras mismas/distintas claves; restauración/importación autorizadas con política explícita. La reproducción actual revierte cada sonda y deja el documento original intacto.

## E-P03 — Cobertura fiscal e integración externa

**Requiere especificación y autorización fiscal separadas.** Definir matriz de operaciones soportadas, identificación del emisor/receptor, moneda, fechas de F3/compañero y rectificativas, casos exentos/recargos y los requisitos externos aplicables a cada negocio. Validar con asesoría competente, sin inferir obligación/calendario legal a partir del repositorio.

Si procede integrar un proveedor/administración, especificar software/registro/payload, huella/encadenamiento/firma, estados, ACK, cancelación y reintentos. Mantener Billing interno como fuente histórica. No reaprovechar el fingerprint interno como huella fiscal ni añadir un QR ficticio. No se realiza ningún envío de prueba externo en E.

## E-P04 — Rendimiento sin pérdida de garantías

Propuesta independiente: perfilar validaciones por hijo y relecturas dentro de una misma frontera consistente. En F2/50 predominan64 SAVEPOINT y64 RELEASE, SELECT de documento59, Business56, SaleLine51,50 INSERT y50 SELECT de línea fiscal. Son grupos por primer identificador SQL, no planes ni un mapa exhaustivo de todos los joins.

La selección previa de serie se deja fuera del temporizador final de T3. Una sonda separada de reimpresión warm mide10 consultas constantes y render entre0,98 y3,88ms según tipo/tamaño; el GET Client completo incluye permisos/selectores y tarda más. No se mezclan ambas sondas ni se equipara Client con una impresora.

Se pueden estudiar validaciones equivalentes con datos ya materializados, pero FK/tenant/constraints/unique/model.clean y auditoría no son trabajo prescindible por defecto. La impresión ya usa prefetch; no se demuestra un N+1 de líneas en el render. No se autoriza bulk de aplicación, supresión de full_clean, cambio de locks o transacciones. Primero medir ON/OFF de una instrumentación comparable y luego equivalencia semántica y fallos concurrentes. Las cifras de B y E tienen arneses distintos y no prueban mejora causal.

## Correcciones realizadas y justificación de los seis tests

| Test original | Problema | Corrección autorizada | Protección conservada/reforzada |
|---|---|---|---|
| `ProductTaxResolutionTests.test_inactive_specific_tax_is_an_error` | Product.full_clean rechazaba crear la fixture antes de llamar al resolver | Crear relación válida y desactivar después; añadir default activo para probar que no hay fallback silencioso | Sigue exigiendo ProductTaxResolutionError; test nuevo prueba rechazo de asignación inicial inválida |
| `test_one_default_per_business_and_defaults_for_two_businesses` | Slug predeterminado duplicado en la segunda empresa | Slug explícito distinto | Sigue exigiendo unicidad del default por empresa y permite defaults de empresas distintas |
| `test_other_business_default_is_never_used` | Mismo defecto de slug ocultaba la prueba de aislamiento | Slug distinto | Sigue rechazando default ajeno |
| `TaxFormTests.test_tax_update_form_exposes_is_active_but_not_business_or_is_default` | Expectativa antigua contraria al Meta actual y las acciones dedicadas activar/desactivar | Renombrar a `test_tax_update_form_excludes_lifecycle_and_tenant_fields` | Sigue excluyendo tenant/default y ahora verifica que POST extra is_active no activa el impuesto; evita eludir la protección del default en la acción dedicada |
| `CatalogMediaDeleteTests.test_protected_delete_keeps_media` | Import a paquete inexistente | Ruta real `apps.core.test_media.image_upload` | Misma aserción de conservación del archivo cuando ProtectedError bloquea borrar |
| `test_successful_product_delete_cleans_media_after_commit` | Mismo import inexistente | Mismo helper real | Misma aserción de cleanup tras commit |

Se reproducen antes los seis FAIL en7,41s. Los tres módulos después:44 PASS en8,03s. Pytest completo:1604 PASS y525 subtests PASS; los dos tests añadidos explican el incremento respecto a los1602 casos previos (1596 PASS+6 FAIL). No se elimina un test, no se omite un error ni se cambia Catálogo de aplicación. El README histórico de catálogo conserva afirmaciones antiguas sobre is_active que no describen el formulario actual; se explicita aquí la discrepancia, sin usarla para modificar la regla de activación.

`e2e/browser_billing.py` solo incorpora TPV_CHROMIUM opcional, manteniendo sus aserciones. La prueba de popup inicial falló porque un flag no bloqueó un enlace con gesto de usuario; la final mantiene la exigencia de una pestaña y cero peticiones, y añade comprobación del retorno nulo de window.open ante un bloqueo real sin activación. No se modifica código de impresión para acomodar ese fallo del arnés.

## Política de emisión independiente

La sonda `E01-direct-billing-unpaid-contract` confirma por POST HTTP que el endpoint Billing permite emitir F2 de Sale completed/unpaid:302 a documento, Payment0, documento1/número1; Sale sigue unpaid. Checkout conserva su gate paid. Es comportamiento actual distinto, no prueba de una política de crédito completa o formalmente aceptada. Antes de operar, confirmar si este flujo es el previsto y con qué controles; cualquier cambio de esa decisión exige autorización. No se añade una regla de saldo al servicio Billing en E.
