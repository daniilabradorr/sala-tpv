# P01/P02 — cierre de la implementación autorizada

Autorización del usuario:28/10/2026. Reanudación y cierre:29/10/2026 (Europe/Madrid). Rama `fix/tpv-checkout-audit-phase3`; HEAD inicial y final `453e9c61de9c2a61b0c628c8e966b1c4983b03fc`, más el diff local revisable. Sin commit, push, PR, merge ni despliegue.

P01 y P02 se implementan dentro de la autorización posterior al Bloque C. Los informes originales B/C se conservan como evidencia histórica del estado anterior; este informe y los dos documentos de implementación describen el cambio autorizado. No se realizan P03/P04 ni optimizaciones de Inventory/Billing.

## Resultado funcional e invariantes

**P01:** Sale completed/paid/pending0 y balance de Payments persistidos deciden la recuperación. Los datos históricos de pago no crean intenciones nuevas ni exigen método activo. El lock de Sale revalida estado, saldo, versión y permiso; Billing mantiene sus validaciones fiscales y su numeración. La misma identidad documental devuelve el mismo documento; otra identidad sobre un documento ya emitido produce conflicto, sin duplicarlo. Se conserva efectivo exacto/cambio como presentación del pago confirmado.

**P02:** formulario explícito para una parte pendiente de una Sale completed cuya sesión histórica está cerrada. No se preselecciona otra sesión; hay confirmación obligatoria. El saldo se obtiene de Payments persistidos y se comprueba bajo lock; la T2 existente valida destino, método, permisos e identidad. Sale y documento conservan caja/sesión histórica. Solo el nuevo Payment y, cuando corresponda, su CashMovement se asocian a la sesión destino. Nunca se reabre caja, mueve un pago confirmado ni se escribe efectivo sobre sesión cerrada.

La identidad de la única parte pendiente conocida se conserva. Un GET fresco o varias partes no identificadas crean una nueva intención explícita para saldo restante, sin utilizar la correlación principal de un split como UUID de una parte. Un reintento del POST conserva importe/UUID/destino; una clave ya confirmada no se duplica ni se traslada. Una clave existente pending/cancelled devuelve409, no una confirmación ficticia. Estado/versión/permiso revocados, recursos ajenos y sobrepagos se rechazan.

T1/T2/T3 permanecen separados. La recuperación controlada agrupa exclusivamente los guards y una llamada a Payments dentro de una T2, con orden Sale→CashSession destino; no engloba Inventory ni Billing. Payments, Inventory, CashRegister, Billing y Sales.services permanecen byte a byte como en la base. También permanecen modelos, constraints, migraciones, impuestos, hashes, reglas fiscales y numeración.

## Comparación económica antes/después

| Situación | Antes, Bloque C | Después autorizado | Invariantes comprobadas |
|---|---|---|---|
| H01, método desactivado tras cobrar |422, Payment1, documento0, stock aplicado1 | Recuperación de emisión; Payment1, documento1, stock1 | Mismo UUID/importe/sesión de Payment; identidad documental conservada |
| Cierre entre T1/T2 | completed/unpaid, Payment0, documento0, stock1; sesión cerrada | Elegir y confirmar sesión válida; Payment1 y documento1, stock1 | No se reabre ni reasigna sesión histórica; efectivo solo en destino válido |
| Cierre entre partes cash/card | Cash6,05 confirmado en histórica; pendiente6,05 | Card6,05 en sesión nueva; total12,10, Payment2, documento1 | Primera parte/UUID/CashMovement intactos; card no crea movimiento físico |
| Respuesta perdida tras parte recuperada | Resultado desconocido para el cliente | GET reconoce esa clave confirmada; solo ofrece el saldo restante | No repite parte confirmada; no POST automático ni sobrepago |
| Billing falla tras recuperar Payment | Pago durable, documento pendiente | P01 recupera documento, incluso con método desactivado | No se revierte ni repite la T2 confirmada |
| Impresión/nueva venta después de recuperación | Debía verificarse el contexto cerrado | Vista impresa del mismo documento y nueva Sale bajo reglas de apertura existentes | Sale anterior mantiene historia; no se intenta abrir nueva venta sobre sesión cerrada |

La comparación automática de los38 snapshots económicos del Bloque C con la regresión autorizada arroja **38/38 idénticos**, normalizando únicamente el orden de ventas/sesiones de las carreras. Se comparan estados, saldos, importes, cantidades de Payments/documents/movimientos, numeración, stock y caja. Cambian respuestas HTTP en C07 (ahora se exige formulario explícito de recuperación) y C08 (identidad documental incompatible); en C04 cambió el orden ganador/perdedor. No se presenta el HTTP200 como prueba suficiente de corrección. Los nuevos efectos legítimos de P01/P02 se verifican en sus propios escenarios.

## Archivos del incremento autorizado

Aplicación:

- `apps/sales/checkout.py`, `apps/sales/forms.py`, `apps/sales/views.py`.
- `templates/sales/partials/_checkout.html`, nuevo `_checkout_pending_payment.html`, `templates/sales/sale_detail.html`.
- `static/js/core/checkout-recovery.js`.

Tests:

- Nuevos `apps/sales/tests/integration/test_billing_recovery_authorized.py`, `test_pending_checkout_authorized.py`, `apps/sales/tests_postgres_authorized.py`, `e2e/browser_checkout_authorized.py`.
- Extensiones de `apps/sales/tests/integration/test_checkout_recovery.py` y `apps/sales/tests_postgres_recovery.py`, para que los tests del estado anterior comprueben el contrato ahora autorizado y conserven sus aserciones económicas.

Documentación nueva: `tpv-phase3-p01-implementation.md`, `tpv-phase3-p02-implementation.md`, este informe y `tpv-phase3-p01-p02-evidence.json`.

Al inicio había25 archivos B/C pendientes. Se guardó manifiesto SHA256 y copia de sus versiones originales en `/workspace/work/phase3-authorized`. Los once archivos B siguen idénticos; también los informes C. Se extienden conscientemente cuatro archivos C (partial de checkout, journal y dos tests) como parte de P01/P02; los otros21 de25 conservan exactamente sus bytes iniciales. No se descartan ni restauran cambios locales ajenos.

## Pruebas y resultados

| Verificación | Resultado |
|---|---|
| P01 específico antes de implementar P02 |41 tests PASS,18,704s; seis carreras HTTP reales de dos usuarios con método inactivo |
| P01/P02 integración inicial |20 tests PASS,8,761s |
| PostgreSQL determinista C/P01/P02 |7 métodos PASS,34,744s; escenarios C×3 y seis cierres históricos, seis carreras P01, seis carreras P02 y cuatro cierres de destino |
| Compatibilidad de efectivo y recuperación |20 tests PASS,13,346s, tras corregir cambio0 de efectivo exacto |
| Clave no completada y carreras P01/P02 |4 métodos PASS,12,690s; pending/cancelled producen409 sin confirmación ficticia |
| Regresión final Sales/Payments/Inventory/CashRegister/Billing |**751 tests PASS,176,892s**, PostgreSQL real; incluye las carreras deterministas y aserciones económicas |
| E2E Chromium conjunto |**26 tests PASS,255,563s**; checkout, UX global, timeout/abort, pérdidas tras T1/T2/T3,500, recarga, reapertura, UUID e impresión |
| Suplemento final de P02 y flujo completo |**14 tests PASS,71,681s**;12 tests de integración y dos métodos E2E con15 ejecuciones nuevas; los12 casos P02 imprimen el documento y crean realmente otra venta en sesión válida |
| pytest completo |**1596 PASS,6 FAIL**,525 subtests PASS,158,88s; no se declara suite verde |
| Contraste de los seis fallos sobre HEAD limpio |**Mismos6 FAIL**,6,99s; comprobados por ID y causa, preexistentes |
| Ruff / formato |PASS;468 archivos con formato correcto |
| Django check / makemigrations --check --dry-run |PASS; ningún problema ni migración |
| Sintaxis JS / whitespace tracked y untracked |PASS |

Evidencia numérica:54 snapshots HTTP/servicios y44 de navegador. Los15 escenarios autorizados de navegador son P01×3 y P02×12 (cash, card, respuesta perdida parcial y cierre tras T1, en1440/820/390); los29 restantes conservan la matriz C y sus casos adicionales. Las comprobaciones de impresión/nueva venta de P02 se realizan en el suplemento final y se incorporan a la misma evidencia. Las suites con BD compartida se ejecutan secuencialmente.

No se repite en esta autorización el comando Django global sin etiquetas; sí se ejecutan las cinco apps financieras completas, pytest completo y los módulos Chromium indicados. No se cuentan los intentos fallidos intermedios como pases.

Los fallos previos de pytest son tres de `ProductTaxResolutionTests` (impuesto inactivo/fixtures con slug duplicado), uno de `TaxFormTests` (is_active esperado) y dos de `CatalogMediaDeleteTests` (import inexistente apps.core.tests.test_media). Se contrastan los mismos seis IDs y causas sobre HEAD exportado, con SECRET_KEY sintética y base aislada. No se corrige catálogo fuera del alcance autorizado. Django y pytest tienen descubrimiento distinto; sus contadores no se suman.

Durante la implementación se detectaron y corrigieron dos regresiones de presentación del cambio0 en efectivo exacto. La revisión final añadió el rechazo explícito de identidades pending/cancelled, reproduciendo antes el200 incorrecto y verificando después409 sin cambios económicos. La acción de nueva venta usa el inicio global existente cuando la sesión histórica ya no es operativa; no altera SaleOpenView ni el contexto de la venta recuperada. Los logs de intentos intermedios quedan separados; no se cuentan como pases.

## Reproducción y límites

Se utiliza `.venv/bin/` existente, sin instalar dependencias. PostgreSQL16-alpine desechable con datos sintéticos, puerto127.0.0.1:55438, base `tpv_diag_phase3authorized`; settings `config.settings.diagnostic_postgres` rechaza bases no diagnósticas. Nunca se prueba producción ni se emite fiscalmente o cobra de verdad. Las suites con estado compartido se ejecutan secuencialmente.

```bash
export TPV_TEST_DATABASE_URL=postgresql://postgres@127.0.0.1:55438/tpv_diag_phase3authorized
export DJANGO_SETTINGS_MODULE=config.settings.diagnostic_postgres
export TPV_DIAGNOSTICS=0
export TPV_CHROMIUM=/usr/bin/chromium
.venv/bin/python manage.py test apps.sales apps.payments apps.inventory apps.cash_register apps.billing --noinput
.venv/bin/python manage.py test e2e.browser_checkout_authorized e2e.browser_checkout_recovery e2e.browser_checkout e2e.browser_htmx_global_ux --noinput
.venv/bin/python -m pytest --ds=config.settings.diagnostic_postgres -q
```

El comando, estado de salida y evidencia por escenario están en el JSON; los registros completos se conservan en `/workspace/work/phase3-authorized`. No se ejecuta toda la colección E2E ajena al checkout, otros navegadores, terminal físico, impresora física, proveedor fiscal externo ni SIGKILL/caída real de PostgreSQL. Impresión se valida mediante vista HTML y llamada window.print en Chromium. No se afirma cubrir toda planificación concurrente ni el incidente original de20s. El journal es por pestaña; con sessionStorage bloqueado la memoria no sobrevive recarga. Un cambio de permiso/método/sesión puede bloquear un replay y exige nueva lectura; no se relajan controles para evitarlo.

PostgreSQL desechable retirado tras comprobar cero conexiones cliente ajenas y cero bases de test pendientes; contenedor eliminado. El entorno gestionado se reinició entre sesiones y el contenedor previo ya no estaba presente al reanudar. La evidencia del cierre distingue esa observación del cierre verificado del contenedor usado el29/10. No quedan servidores de pruebas de esta ejecución activos.
