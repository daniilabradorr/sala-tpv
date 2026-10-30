# NETXODO — Fase 3, Bloque D: informe final

29/10/2026. Rama `fix/tpv-checkout-audit-phase3`. SHA inicial y final: **`a38898acce06a4360c4a2427895488178225072e`**, más este diff local. Árbol inicial limpio. `origin/main` verificado por fetch: `cdbf88c7df6b5c9d75ccdeda84c8ac8b67b03983`; rama remota comprobada por ls-remote en `a38898acce06a4360c4a2427895488178225072e`. No se incorpora main ni se crea otra rama. **Sin commit, push, PR, merge ni despliegue.**

El flujo de cobro, recuperación, impresión y nueva venta supera la matriz ensayada. Se corrigen seis defectos de coordinación/presentación y se acota la espera del navegador. P01/P02 permanecen implementadas y validadas; no se modifica dominio para resolver UX. Pytest completo conserva seis fallos preexistentes de catálogo, reproducidos sobre la base limpia: **no se declara la suite global verde**.

Entregables: [auditoría](tpv-phase3-block-d-audit.md), [matriz D01–D26](tpv-phase3-block-d-e2e.md), [correcciones](tpv-phase3-block-d-fixes.md), este informe y [evidencia numérica](tpv-phase3-block-d-evidence.json). Scratch/logs/capturas locales: `/workspace/work/phase3-d`.

## Las doce respuestas

1. **COBRAR → CONFIRMAR → IMPRIMIR → NUEVA VENTA:** funciona en los casos probados de tarjeta, efectivo, split, F1/F2 y P01/P02. La impresión abre el documento emitido; iniciar otra venta ejecuta realmente el POST existente. Se comprueban vacío/importe0/sin pagos y claves nuevas, no solo la presencia del botón.
2. **Dobles envíos/listeners:** no se demuestra duplicación de listeners en el recorrido normal ni duplicación económica. Sí se reproducen solicitudes adicionales por otra fuente `htmx.ajax` y un GET antiguo que reemplazaba éxito; ahora se excluyen. Los controles nativos/hx-sync ya protegían el doble envío habitual. Cinco reaperturas y doble apertura conservan un GET por apertura; doble confirmación no produce otro cobro.
3. **Mensajes:** 409 informa cambio de estado;422 expone errores y ahora enfoca/asocia el resumen;403 indica permiso.500/timeout/abort/red mutantes mantienen resultado desconocido. La sesión caducada del snapshot ya no muestra un SyntaxError de JSON. No se afirma «pago rechazado» sin confirmación del servidor.
4. **Timeout:** espera de POST acotada a60s si no hay otro plazo finito explícito; el test inyecta250ms antes deT1. Desbloquea processing, conserva intención y exige GET antes de repetir. El servidor puede seguir ejecutando. Al liberar la operación original, GET confirma éxito con **un POST, un Payment y un documento**. No hay cancelación económica ni rollback inferido.
5. **P01:** funciona desde UI con método histórico desactivado, misma identidad Billing y Payment original único. Se verifica reapertura en1440/820/390 y recorrido adicional hasta impresión/nueva venta; carreras de dos usuarios incluidas en regresión PostgreSQL.
6. **P02:** funciona con sesión histórica cerrada, elección explícita de sesión válida, partes cash/card, parcial y respuesta perdida. No preselecciona caja ni repite lo confirmado. La nueva vista previa usa el importe de la parte; historia, UUID confirmados y sesión de Sale/documento permanecen intactos.
7. **Tablet/móvil:** usable en los tamaños simulados y revisados visualmente. Tap, Escape/Enter, foco, cambio y scroll vertical funcionan; overflow horizontal del panel0px y confirmación54px (108px con zoom CSS2). Se corrige un cierre nativo tardío que cancelaba una reapertura rápida. No equivale a validar hardware real o todos los zooms.
8. **Defectos corregidos:** respuesta GET obsoleta; solicitudes incompatibles del mismo panel; foco/asociación de errores y foco P02 standalone; ausencia de cambio visual para la parte P02; error técnico tras login HTML en snapshot; cierre tardío que dejaba «Preparando cobro…». Además, el POST deja de esperar indefinidamente en el navegador cuando usa el default.
9. **Pendientes:** seis fallos de catálogo; revisión fiscal/documental E; dispositivos/impresora/diálogo nativo; staging y causa productiva de los20s. Las propuestas de rendimiento de Inventory/Billing siguen fuera de este bloque. No se declara ausencia universal de fugas o carreras por estas muestras.
10. **Pruebas:**752 financieras PASS;85 métodos E2E únicos validados entre checkout y carrito; pytest1596 PASS/6 FAIL/525 subtests PASS. Ruff, formato, check, migraciones y sintaxis PASS. Detalle y error intermedio de arranque de Chromium abajo. No se ejecuta toda la colección browser ajena a checkout/carrito ni Django sin etiquetas.
11. **Integridad:**38/38 snapshots económicos anteriores coinciden;54 casos HTTP/servicios con aserciones persistidas. No se altera ninguno de422 archivos protegidos de backend/configuración/lockfiles. En lo ensayado: sin sobrepago, stock repetido, pago confirmado movido, efectivo en sesión cerrada, documento inicial duplicado ni avance fiscal por imprimir.
12. **Bloque E:** se puede continuar con su validación fiscal y documental en un siguiente encargo. D entrega evidencia y correcciones frontend; no certifica cumplimiento fiscal, beta productiva ni autoriza despliegue.

## Cambios locales entregados

Siete archivos existentes modificados:

- `static/js/core/htmx-events.js`: revisión/propiedad del panel, exclusión durante processing/desconocido y límite de espera.
- `static/js/sales_cart.js`: mensaje de snapshot/login y guard de cierre nativo tardío.
- `static/js/sales_tpv.js`: foco, asociaciones ARIA y cambio de la parte P02.
- `static/css/sales_tpv.css`: contorno de foco del resumen con token existente.
- `templates/sales/partials/_checkout.html`: resúmenes/errores enfocables y asociados.
- `templates/sales/partials/_checkout_pending_payment.html`: metadato del método, preview y resumen accesible.
- `e2e/browser_optimistic_cart.py`: selector opcional de Chromium instalado para la prueba Manifest, sin cambiar aserciones.

Siete archivos nuevos: `e2e/browser_checkout_frontend_d.py`, `e2e/checkout_frontend_d_observer.js` y los cinco documentos/JSON `docs/performance/tpv-phase3-block-d-{audit,e2e,fixes,report}.md` y `tpv-phase3-block-d-evidence.json`.

No hay cambios en `apps/`, `config/`, modelos, servicios, views/forms, endpoints, migraciones, dependencias o lockfile. Se revisan diff completo y archivos nuevos, nombres y patrones de credenciales; no aparecen secretos ni archivos ajenos. Los informes B/C/P01/P02 anteriores permanecen intactos.

## Entorno y validación

Python3.12 existente, Django5.2, Chromium151 del sistema, PostgreSQL16-alpine en contenedor propio `tpv-phase3-d-postgres`, etiqueta `codex.task=tpv-phase3-d`, --rm y sin volumen persistente. Publicado solo en127.0.0.1:55440. Base sintética `tpv_diag_phase3d`; Django crea/destruye `test_tpv_diag_phase3d`. Settings `diagnostic_postgres` exige prefijo diagnóstico y no usa DATABASE_URL. Sin instalar dependencias ni acceder a producción. Los runners con esa base se ejecutan secuencialmente.

| Ejecución | Resultado observado |
|---|---|
| Sales/Payments/Inventory/CashRegister/Billing completos | **752 PASS,167,420s**, PostgreSQL; incluye concurrencia/locks, T1/T2/T3, cierres, C y P01/P02 |
| Comparación económica con evidencia anterior a D | **38/38 coinciden**; se normaliza orden de listas de carreras y se excluyen HTTP/duraciones, sin sustituir importes/estados |
| Checkout conjunto (D inicial+autorizado+recovery+checkout+global UX) | **39 PASS,355,484s**; incluye15 ejecuciones P01/P02,27 pérdidas/fronteras C y variantes nuevas |
| Suplemento navegación/contraste/cantidades pendientes | **3 PASS,11,187s**; navegación real con beforeunload cancelar/aceptar y replay del UUID; contraste15,74:1/18,26:1 y etiquetas; cobrar36,30€ tras flush |
| Carrito optimistic/hardening, lote inicial | **42 PASS y1 ERROR de arranque**,43 métodos,95,473s. No se presenta este lote como verde |
| Test restante de assets compilados | **1 PASS,3,503s**, tras selector Chromium; collectstatic temporal:234 ficheros y700 procesados; Manifest/WhiteNoise real |
| Total E2E único validado | **85 métodos** =39+3+42+1. No suma repeticiones de desarrollo ni confunde subcasos con métodos |
| Muestras frontend base comparables | **1 método PASS,17,413s**,5 ventas nuevas; medición posterior incluida en lote39 |
| Pytest completo PostgreSQL | **1596 PASS,6 FAIL,525 subtests PASS**,152,88s;1 warning Django60 también presente en base |
| Seis fallos sobre exportación limpia HEAD a38898a | **Los mismos6 FAIL,7,44s**; mismos IDs y mensajes normalizando direcciones de objetos |
| Ruff check / format |PASS;469 archivos formateados |
| Django check / makemigrations --check --dry-run |PASS; sin problemas ni cambios de esquema |
| node --check de tres scripts modificados y observador / git diff --check |PASS |

Los logs contienen409/422/500 y aborts intencionados. Algunos handlers de rutas retenidas de Playwright registran `asyncio.CancelledError` al cerrar contextos; no son pageerror de JavaScript ni fallos del runner. Se separan las reproducciones anteriores a la corrección, el error del bundle ausente y las ejecuciones finales. Las suites no pasan por alterar sus aserciones económicas.

### Seis fallos preexistentes de pytest

| Archivo / clase / método | Causa coincidente en base limpia y D |
|---|---|
| `apps/catalog/tests/test_tax_resolution.py` · `ProductTaxResolutionTests.test_inactive_specific_tax_is_an_error` | Fixture intenta crear producto con impuesto inactivo; ValidationError antes del punto esperado |
| Mismo archivo · `test_one_default_per_business_and_defaults_for_two_businesses` | Fixture Business con slug ya existente |
| Mismo archivo · `test_other_business_default_is_never_used` | Mismo slug duplicado |
| `apps/catalog/tests/unit/test_forms.py` · `TaxFormTests.test_tax_update_form_exposes_is_active_but_not_business_or_is_default` | Expectativa de `is_active` que el formulario actual no expone |
| `apps/catalog/tests/unit/test_services.py` · `CatalogMediaDeleteTests.test_protected_delete_keeps_media` | Import inexistente `apps.core.tests.test_media` |
| Mismo archivo · `test_successful_product_delete_cleans_media_after_commit` | Mismo import inexistente |

La exportación se obtiene con git archive del HEAD real, sin el diff D, usa SECRET_KEY sintética y la misma PostgreSQL aislada. Se comparan automáticamente los conjuntos de IDs y los mensajes de error; no se atribuye su preexistencia solo a un informe anterior. No se corrige catálogo fuera del alcance. Django y pytest tienen descubrimiento distinto; no se suman sus contadores.

## Rendimiento frontend antes/después

Cinco muestras warm por versión, una línea/card/F2, ventas nuevas y sin tracing detallado. Misma máquina/LiveServer/PG, sin otros runners simultáneos. Base: JS extraído de a38898a servido mediante ruta del navegador; misma plantilla normal sin errores y arnés que en D. No se compara Gunicorn B con LiveServer D como si fuesen el mismo experimento. No se midió cold start ni p95.

Valores: **mediana [mín–máx] ms**. Las etapas se solapan: no sumar columnas. Los intervalos beforeRequest→afterRequest contienen servidor, transporte y finalización HTMX, no red pura. Dos rAF tras settle son oportunidad de pintura, no píxel físico.

| Intervalo | Base | D |
|---|---:|---:|
| COBRAR→inicio flush |4,0 [4,0–5,8] |4,4 [4,1–5,1] |
| Flush |64,0 [28,1–73,2] |65,8 [60,7–69,8] |
| GET beforeRequest→afterRequest |80,3 [77,6–83,0] |78,3 [77,6–78,9] |
| COBRAR→formulario visible |149,7 [118,2–157,4] |150,2 [144,8–153,6] |
| COBRAR→dos frames tras settle GET |191,1 [155,2–193,2] |192,1 [188,5–193,6] |
| Confirmar→beforeRequest POST |3,8 [3,4–5,6] |4,1 [4,0–4,5] |
| POST beforeRequest→afterRequest |287,5 [268,2–332,0] |286,7 [261,6–314,5] |
| POST beforeRequest→afterSwap |287,3 [268,0–331,2] |286,6 [261,4–314,0] |
| afterSwap→afterSettle POST |21,9 [21,6–22,3] |23,1 [22,0–23,5] |
| afterSettle→dos frames POST |17,9 [15,0–20,2] |13,9 [12,9–21,8] |
| Confirmar→dos frames tras settle |328,5 [310,5–377,5] |327,6 [309,3–355,8] |
| Click imprimir→dos frames tras load del popup |159,1 [141,1–168,2] |160,5 [155,3–170,7] |

No se demuestra mejora significativa: COBRAR→pintura cambia+1,0ms y confirmar→pintura−0,9ms de mediana en muestras pequeñas con ruido. El objetivo de D es coordinación/claridad/recuperación; no se promete acelerar Inventory/Billing. No se reproduce espontáneamente ni se atribuye la incidencia original de20s. Las muestras individuales y eventos están en el JSON.

## Reproducción y límites

Usar un PostgreSQL **nuevo y desechable**, nunca la base del comercio. En esta ejecución:

```bash
export SECRET_KEY=phase3-d-synthetic
export TPV_TEST_DATABASE_URL=postgresql://postgres@127.0.0.1:55440/tpv_diag_phase3d
export DJANGO_SETTINGS_MODULE=config.settings.diagnostic_postgres
export TPV_DIAGNOSTICS=0
export TPV_CHROMIUM=/usr/bin/chromium
.venv/bin/ruff check .
.venv/bin/ruff format --check .
.venv/bin/python manage.py check
.venv/bin/python manage.py makemigrations --check --dry-run
.venv/bin/python manage.py test apps.sales apps.payments apps.inventory apps.cash_register apps.billing --noinput
.venv/bin/python manage.py test e2e.browser_checkout_frontend_d e2e.browser_checkout_authorized e2e.browser_checkout_recovery e2e.browser_checkout e2e.browser_htmx_global_ux --noinput
.venv/bin/python manage.py test e2e.browser_optimistic_cart.OptimisticCartBrowserTests e2e.browser_cart_hardening --noinput
.venv/bin/python -m pytest --ds=config.settings.diagnostic_postgres -q
```

El comando conjunto final listado incluye las tres pruebas D añadidas después del lote39; aquí se ejecutaron por separado como suplemento3. Para guardar snapshots definir `TPV_INTEGRITY_OUTPUT` con destino distinto por runner. El test `CollectedCartAssetsBrowserTests` requiere collectstatic y almacenamiento Manifest/WhiteNoise: se ejecutó con override temporal de STATIC_ROOT/STORAGES mediante `/workspace/work/phase3-d/run_collected_assets.py`, sin añadir settings de producto. El script crea TemporaryDirectory, aplica `CompressedManifestStaticFilesStorage`, llama collectstatic y DiscoverRunner para esa clase; no instala browsers ni dependencias. La comparación base de rendimiento usa `TPV_D_BASELINE_STATIC_DIR` apuntando a `static/js` extraído del SHA.

No se prueba impresora física, cancelación del diálogo nativo, terminal bancario, fiscalidad externa, Safari/Firefox, hardware móvil real, todas las combinaciones de zoom, cargas sostenidas, heap durante horas, SIGKILL real ni caída física de PostgreSQL. La falta de especificación maestra frontend se declara en auditoría. El journal de memoria no sobrevive recarga si el storage está bloqueado; permisos/método/sesión pueden cambiar y exigir nueva lectura. No se introduce un atajo para evitarlos.

## Cierre y Git

Antes de detener PostgreSQL se verificaron **cero conexiones cliente ajenas al lector y cero bases test pendientes**. Se comprobó etiqueta/identidad/--rm y se detuvo únicamente el contenedor de D; después de su retirada asíncrona, una nueva consulta Docker confirma que no existe. Los directorios temporales de collectstatic se retiraron. Los logs y exportaciones de prueba permanecen en scratch para revisión; no se versionan.

Estado final comprobado: siete archivos existentes modificados y siete nuevos, exclusivamente aplicación frontend, pruebas y documentación D. Ningún cambio staged ni nuevo commit. Los422 hashes protegidos siguen idénticos; diff sin servicios/migraciones ni cambios fiscales. La publicación continúa pendiente de autorización posterior del usuario.

## Autorización posterior de publicación

El29/10/2026 el usuario solicita publicar estos cambios en `fix/tpv-checkout-audit-phase3`, autorizando el commit y el push del Bloque D. Los estados «sin commit/push» y el SHA final anteriores describen el cierre de la auditoría, previo a esta autorización. Se mantienen las validaciones documentadas y los seis fallos preexistentes de pytest. El SHA publicado y la comprobación del remoto se comunican después del push.
