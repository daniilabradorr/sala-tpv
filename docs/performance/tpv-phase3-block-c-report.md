# Fase 3, Bloque C — informe de cierre

Base inicial y final: `453e9c61de9c2a61b0c628c8e966b1c4983b03fc`. Rama: `fix/tpv-checkout-audit-phase3`. `origin/main` verificado: `cdbf88c7df6b5c9d75ccdeda84c8ac8b67b03983`. Se audita esa base **más el diff local C**, sin incorporar main. B estaba sin commit y sus once archivos se conservan idénticos por SHA256. No hay commit, push, PR, merge ni despliegue: el encargo C restringe expresamente esas acciones, aunque el encargo inicial A pidió subir una rama.

## Resultado por categoría

| Categoría | Resultado |
|---|---|
| Corregido | Error oculto H01 y errores de campos ocultos visibles; timeout/abort/network/500 con aviso honesto, identidad conservada, bloqueo de retry ciego y consulta GET; recuperación de página standalone/recarga/reapertura; estado cancelled sin formulario de cobro |
| Confirmado y pendiente | H01 funcional sigue422 con método histórico inactivo; cierre entre T1/T2 o partes deja estado parcial durable; formulario puede rechazar serie histórica inactiva; contrato de retorno temprano del checkout completo |
| No reproducido | Doble cobro, doble salida de inventario o documento inicial duplicado en escenarios probados; tampoco se acredita causa espontánea de los20s originales de producción |
| No evaluable aquí | Incidente de producción, terminales/adquirentes, emisión fiscal externa, toda planificación de carreras, otros navegadores, muerte real de worker/BD, documentos maestros ausentes |
| Requiere autorización | P01 ruta funcional solo emisión; P02 recuperación explícita de saldo en sesión válida y política de permisos; P03/P04 si se eligen cambios de rendimiento/preflight de dominio |

## Diez respuestas ejecutivas

1. **¿Doble cobro?** No en C01/C02/C06/C08, replays de UUID ni pérdida de respuesta ensayados. Sale bloqueada, compatibilidad de Payment y saldo autoritativo impiden duplicar en esas pruebas. Dos partes legítimas de split son dos Payments, no doble cobro. No se afirma una garantía universal sobre integraciones externas no ensayadas.
2. **¿Doble stock?** No en reintentos ni última unidad concurrente: T1 y locks protegen efectos y la venta completed no se completa otra vez. C04 deja stock0 y una salida; los replays dejan una por línea física controlada. Stock de servicios/productos no controlados sigue su contrato existente.
3. **¿Documento inicial duplicado?** No observado. Replays de Billing, UUID distintos sobre venta ya emitida, carreras de checkout y serie compartida verifican documento único por venta y números distintos. Sale/serie bloqueadas y controles existentes se mantienen; no se toca fiscalidad.
4. **¿Falla Billing después del pago?** Sale completed/paid, pending0, Payment durable y documento ausente. T3 revierte sus cambios; T1/T2 no revierten. Recuperación de emisión existente puede funcionar; H01 bloquea replay histórico si se desactiva el método, y su solución funcional es P01.
5. **¿Se pierde HTTP tras commit?** Se muestra resultado desconocido, se conserva la intención y no se envía automáticamente otro POST. GET autorizado diferencia unpaid/partial/paid/documento. Si T3 confirmó, muestra éxito sin otro POST; si falta efecto, permite replay explícito con UUID/payload original sujeto a validaciones del servidor.
6. **¿Cierre entre T1 y T2?** Reproducido409: completed/unpaid, stock aplicado1, Payment0 y documento0; entre partes queda partial y Payment1. No se escribe sobre sesión cerrada. El servicio existente permite registrar una intención no confirmada en sesión válida, conservando historia; falta el flujo visible autorizado P02.
7. **¿H01 corregido?** Presentación sí: resumen accesible y test permanente sin JS. Decisión funcional no: continúa422 y queda PENDIENTE DE AUTORIZACIÓN. No se transforma una intención por un flag del cliente.
8. **¿Timeout sin feedback corregido?** Sí en pruebas Chromium: timeout250ms, abort, pérdida después de T1/T2/T3,500 tras commits, reload/reopen; tres tamaños incluidos touch. Consulta previa obligatoria en UI, claves conservadas, sin POST automático ni efectos repetidos. El backend conserva garantías sin JS.
9. **¿Qué aprobar?** P01, prioridad alta: decidir recuperación solo emisión por estado persistido y bajo lock, sin validar método histórico como pago nuevo. P02, prioridad alta: flujo explícito de partes pendientes en sesión válida, permisos y relación con caja histórica. P03/P04 solo con aprobación aparte; no se propone unir transacciones ni cambiar fiscalidad.
10. **¿Bloque D?** Puede continuar análisis y planificación con estos hallazgos. H01 y recuperación operativa de caja no se consideran resueltos ni aptos para declarar cierre funcional completo. Si D exige modificar dominio o asumir esos flujos corregidos, primero aprobar e implementar P01/P02 con sus tests.

## Archivos del bloque C

Aplicación:

- `static/js/core/checkout-recovery.js` (nuevo): journal de intención, lectura y recuperación visual.
- `static/js/core/htmx-events.js`: eventos timeout/abort/error, bloqueo y feedback por contexto.
- `templates/sales/partials/_checkout.html`: errores visibles, estado autoritativo de presentación y restricciones visuales de estados terminales.
- `templates/sales/checkout.html`: target de consulta standalone.

Tests:

- `apps/sales/tests/integration/test_checkout_recovery.py` (nuevo).
- `apps/sales/tests_postgres_recovery.py` (nuevo).
- `e2e/browser_checkout_recovery.py` (nuevo).
- `e2e/browser_checkout.py`: adaptar recuperación incierta a GET previo y Chromium opcional por variable de entorno.
- `e2e/browser_htmx_global_ux.py`: selector opcional de Chromium instalado; sin cambio de expectativas.

Documentación nueva: los cuatro `tpv-phase3-block-c-{integrity,scenarios,proposals,report}.md` y `tpv-phase3-block-c-evidence.json`. Los once archivos B sin commit no forman parte del cambio C; se enumeran y verifican en la evidencia. Los tests C reutilizan helpers de diagnóstico B conservados en este árbol: una publicación futura debe conservar también esos archivos, sin atribuirlos al diff C. No se modifican modelos, servicios, views/forms, locks, constraints, migraciones, cálculos, impuestos, series, numeración ni VeriFactu.

## Validación reproducible

Se usa `.venv/bin/` del entorno ya instalado, equivalente a `uv run` sin resolver ni instalar dependencias. PostgreSQL16-alpine local desechable en127.0.0.1:55437, sin volumen persistente, base sintética `tpv_diag_phase3c`; Django crea/destruye `test_tpv_diag_phase3c`. Nunca se usa DATABASE_URL de producción. Suites con estado mutable ejecutadas secuencialmente.

```bash
export TPV_TEST_DATABASE_URL=postgresql://postgres@127.0.0.1:55437/tpv_diag_phase3c
export DJANGO_SETTINGS_MODULE=config.settings.diagnostic_postgres
export TPV_DIAGNOSTICS=0
export TPV_CHROMIUM=/usr/bin/chromium
.venv/bin/ruff check .
.venv/bin/ruff format --check .
.venv/bin/python manage.py check
.venv/bin/python manage.py makemigrations --check --dry-run
.venv/bin/pytest --ds=config.settings.diagnostic_postgres -q
.venv/bin/python manage.py test --noinput --verbosity=1
.venv/bin/python manage.py test e2e.browser_checkout e2e.browser_htmx_global_ux --noinput
.venv/bin/python manage.py test e2e.browser_checkout_recovery --noinput
```

La configuración `diagnostic_postgres` ya existe en HEAD y exige nombre de base `tpv_diag_*`. TPV_CHROMIUM es opcional en tests: sin ella se usa el navegador gestionado de Playwright como antes. Chromium del entorno sustituye al bundle ausente; no se añade dependencia al producto.

| Comprobación | Resultado final |
|---|---|
| Ruff check / format | PASS; 464 archivos con formato correcto |
| Django check / makemigrations --check --dry-run | PASS; ningún problema, ninguna migración |
| Sintaxis de ambos módulos JS / git diff --check (también untracked) | PASS |
| Checkout + presentación, ejecución inicial | 42 tests PASS antes del último test cancelled; los cinco finales incluidos en suite completa |
| Matriz C PostgreSQL final | C01–C10 ×3, seis cierres, contratos y recuperación pendiente en sesión válida PASS; 38 snapshots BD |
| Django completo con PostgreSQL | **1625 tests PASS**,203,534s |
| pytest completo con PostgreSQL | **1577 PASS,6 FAIL**,521 subtests PASS,146,31s; no se presenta como suite verde |
| Contraste HEAD sin diff, seis tests fallidos de pytest | **Mismos6 FAIL**,7,54s; código de baseline exportado con git archive453e9c6 y SECRET_KEY sintética explícita |
| Chromium recuperación | Matriz27 ejecuciones + doble submit PASS; lote3 métodos106,128s (incluye repetición del caso500 anterior) |
| Chromium checkout/UX global anteriores, ejecución final | **21/21 PASS**,101,883s; impresión y nueva venta incluidas |
| Chromium journal adicional | **1/1 PASS**,3,950s; móvil, cerrar aviso tras recarga, journal corrupto, storage bloqueado; sin efectos económicos |

Los seis fallos previos de pytest: tres en `apps/catalog/tests/test_tax_resolution.py` (fixture de impuesto inactivo y slug duplicado), uno en `apps/catalog/tests/unit/test_forms.py` (expectativa is_active) y dos en `apps/catalog/tests/unit/test_services.py` (import inexistente `apps.core.tests.test_media`). Se reproducen los mismos IDs y causas en el HEAD limpio; no se corrige catálogo fuera del alcance C. Django y pytest tienen distinto descubrimiento, por lo que sus contadores/resultados no son intercambiables.

Se registran también las ejecuciones intermedias: faltaba el Chromium gestionado de Playwright y21 E2E no arrancaron inicialmente; se usó el binario instalado con selector opcional. Un test anterior de500 esperaba pulsar reintento aun cuando el GET ya mostraba éxito; se ajustó a comprobar recuperación por lectura y pasó en repetición individual y lote21 final. La matriz nueva detectó feedback residual tras reload y un aviso superpuesto en móvil, corregidos antes de su ejecución final. No se ocultan esos intentos fallidos ni se cuentan como pases.

Git final: cinco archivos tracked modificados, nueve C nuevos (incluye evidencia), once archivos B nuevos preservados; HEAD/branch sin cambios. Sin commit ni publicación. PostgreSQL desechable detenido/eliminado, sin otras conexiones cliente ni bases test restantes antes de detener. Los registros intermedios quedan en `/workspace/work/phase3-c`; los resultados numéricos de revisión están en la evidencia del repositorio. Simulaciones sintéticas, ningún cobro o documento fiscal real.

## Límites y autorización

Los fallos parciales son inyectados; abort real de XHR y timeout se ejecutan mientras el servidor conserva operaciones durables. No se ensaya kill real de worker, fallo físico de PostgreSQL, producción, terminal/adquirente ni emisor fiscal externo. No hay prueba de todas las planificaciones concurrentes. No se ejecuta toda la colección E2E ajena al checkout y UX global; la suite completa Django tiene descubrimiento distinto del patrón de archivos `browser_*.py`.

sessionStorage retiene solo campos allowlisted de intención dentro de pestaña, sin CSRF/cookies/credenciales. Si está bloqueado, memoria protege la página actual, pero no persiste al recargar. No sustituye autorización ni garantías del servidor. No se reconstruye cambio/efectivo entregado desde una lectura, pues no se persiste ese dato. Documentación maestra DOCX/checklist no disponible, declarada en integridad.

El motivo de pedir autorización posterior está en el encargo C.2 (“No modifiques todavía la validación que decide si se ejecuta un pago o una emisión si ello cambia el contrato de checkout”) y C.4 (“Modificar cierre de caja, Payments, CashMovement o transacciones requiere autorización posterior”). Las propuestas concretas, pseudocódigo, compatibilidad y pruebas están listas en `tpv-phase3-block-c-proposals.md`; no se han aplicado cambios de dominio.
