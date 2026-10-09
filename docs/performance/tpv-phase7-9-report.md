# TPV fases 7, 8 y 9 — informe de entrega

PR [#227](https://github.com/daniilabradorr/sala-tpv/pull/227), una sola PR contra develop, sin merge.

Referencia de reglas de caja: [master backend](https://drive.google.com/file/d/1m6JcYr1zbqNberV4C8H51pQ-HKQVrfQp/view). El checklist se excluye expresamente por indicación del usuario.

## 1. SHA base real

`6c29ca27d8a38bbc7a0e998ea5ab16a060202207`, merge de PR #226. Verificado con el commit remoto y `git ls-remote develop` antes de trabajar. Fases 1–6 presentes.

## 2. SHA final de implementación

`95eb203d3c5c399107ebd1ee000837d759a1a3f0`. Los siguientes commits de documentación publican evidencias sin cambiar la implementación medida. El SHA de entrega se consulta en la cabeza de PR #227.

## 3. Archivos modificados



- `.github/workflows/ci.yml`
- `apps/payments/forms.py`
- `apps/payments/models.py`
- `apps/payments/services.py`
- `apps/payments/tests.py`
- `apps/sales/checkout.py`
- `apps/sales/forms.py`
- `apps/sales/selectors.py`
- `apps/sales/services.py`
- `apps/sales/tests/integration/test_cart_layout.py`
- `apps/sales/tests/integration/test_views.py`
- `apps/sales/views.py`
- `e2e/browser_checkout.py`
- `e2e/browser_full_flow.py`
- `e2e/browser_htmx_global_ux.py`
- `e2e/browser_tpv.py`
- `static/css/sales_tpv.css`
- `static/js/core/htmx-events.js`
- `static/js/sales_tpv.js`
- `templates/sales/partials/_cart_content.html`
- `templates/sales/partials/_checkout.html`
- `templates/sales/partials/_line_editor.html`
- `templates/sales/partials/_line_update_success.html`
- `templates/sales/partials/_product_grid.html`
- `templates/sales/sale_workspace.html`
- `tests/performance/baseline.py`
- `tests/performance/browser.py`
- `tests/performance/test_queries.py`

## 4. Archivos creados



- `apps/payments/migrations/0004_require_session_only_for_physical_cash.py`
- `apps/sales/tests/integration/test_checkout_cash.py`
- `apps/sales/tests_postgres_checkout.py`
- `templates/sales/partials/_cart_footer.html`
- `templates/sales/partials/_cart_line.html`
- `templates/sales/partials/_checkout_loading.html`
- `templates/sales/partials/_line_mutation.html`
- `docs/performance/tpv-phase7-9-actions.json`
- `docs/performance/tpv-phase7-9-before-browser.json`
- `docs/performance/tpv-phase7-9-before-harness.patch`
- `docs/performance/tpv-phase7-9-before-server.json`
- `docs/performance/tpv-phase7-9-browser.json`
- `docs/performance/tpv-phase7-9-comparison.md`
- `docs/performance/tpv-phase7-9-pr227-final.md`
- `docs/performance/tpv-phase7-9-report.md`
- `docs/performance/tpv-phase7-9-server.json`

## 5. Fase 7

Selector exclusivo de grid; render mínimo para cantidad/precio/descuento; línea y footer OOB; opciones de checkout materializadas una vez; debounce 175 ms y Enter inmediato. No se quita full_clean, auditoría ni validación económica.

## 6. Fase 8

COBRAR abre la shell local inmediatamente. GET queda editable/cerrable; el POST crítico bloquea reenvíos y cierre. Formularios conservados, recovery según estado persistido, errores 422/409 y resultados inciertos sin mostrar éxito inventado.

## 7. Fase 9

Vacío = exacto, insuficiente = error antes de mutation, cambio calculado con céntimos; Payment/CashMovement guardan importe asignado. Sesión conditional al método físico; Sale tiene su propia regla de apertura.

## 8. Grid antes/después

Antes: selector de detalle con relaciones/cart/returns y construcción de formularios de cabecera. Después: venta escalar tenant/store-scoped, catálogo paginado, categorías y settings; sin lectura de SaleLine ni SaleReturn. La navegación normal y history restore conservan el detalle completo.

## 9. Carrito antes/después

Antes: cantidades y editor devolvían el ticket entero. Después: `_cart_line`, `_cart_footer`, `_line_mutation` y OOB. Los hints de líneas pendientes se filtran por business/sale/store; la última respuesta reconcilia las dos líneas y total. Add/delete mantienen el shell completo. Si una respuesta estructural es antigua y se descarta, needsStructure espera a la cola estable y solicita un GET autoritativo region=cart al endpoint existente; revisiones protegen también ese refresh. La ruta común no añade GET. Anclaje automático desactivado en el scroll interior; errores locales se revelan dentro de esa región. Los full swaps conservan el foco del control activo dentro del drawer modal, con preventScroll y fallback al cierre si el control se elimina; no roban foco a otra superficie.

## 10. Debounce anterior

275 ms, medido y registrado en el baseline.

## 11. Debounce nuevo

175 ms para escritura humana; se evita repetir valores de input sin cambio.

## 12. Barcode

`barcode_enter`: p50/p95 105.85 / 119.40 → 81.60 / 93.80 ms. Enter cancela el timer y envía en el mismo evento. E2E usa barcode real `8410000000010`, comprueba el orden request → submit-returned, una petición y respuestas antiguas reemplazadas, sin sleeps como prueba de rapidez.

## 13. Queries grid

`grid_250_all`: queries 13 → 11; bytes 19610 → 19765; p50/p95 servidor 32.08 / 40.21 → 15.24 / 17.92 ms. `grid_250_search_exact`: queries 12 → 10; bytes 1491 → 1496; p50/p95 servidor 26.17 / 31.66 → 10.53 / 12.77 ms. Constantes en catálogos 50/250/1000.

## 14. Queries add

`add_product_1_lines`: queries 68 → 65; bytes 5161 → 5309; p50/p95 servidor 53.34 / 60.35 → 43.80 / 48.46 ms. `add_product_20_lines`: queries 68 → 65; bytes 44097–44307 → 45271–45544; p50/p95 servidor 62.36 / 69.78 → 49.89 / 55.25 ms.

## 15. Queries quantity

`quantity_1_to_1.5`: queries 66 → 64; bytes 11361 → 2743; p50/p95 servidor 40.87 / 44.65 → 43.55 / 52.15 ms.

## 16. Queries header

`header_customer_none_to_customer`: queries 40 → 40; bytes 1723 → 1723; p50/p95 servidor 29.84 / 34.45 → 33.78 / 214.61 ms. Se conservan las cuatro variantes de cabecera.

## 17. Queries checkout GET

`checkout_get_1_lines`: queries 18 → 10; bytes 7287 → 7720; p50/p95 servidor 35.57 / 41.41 → 25.79 / 33.74 ms. `checkout_get_20_lines`: queries 18 → 10; bytes 7292 → 7725; p50/p95 servidor 37.03 / 44.84 → 23.68 / 31.77 ms.

## 18. Payload quantity

`quantity_1_to_2`: queries 66 → 64; bytes 11359 → 2741; p50/p95 servidor 42.13 / 51.62 → 42.85 / 44.58 ms. `quantity_50_lines`: queries 66 → 64; bytes 104020 → 2746; p50/p95 servidor 58.11 / 60.45 → 40.60 / 43.09 ms.

## 19. Payload discount

`editor_discount_post`: queries 67 → 65; bytes 11476 → 2857; p50/p95 servidor 40.83 / 44.41 → 41.28 / 44.63 ms. `discount_50_lines`: queries 67 → 65; bytes 104136 → 2861; p50/p95 servidor 58.12 / 60.55 → 41.79 / 48.56 ms. `editor_price_post`: queries 67 → 65; bytes 11383 → 2764; p50/p95 servidor 45.74 / 48.53 → 39.54 / 45.46 ms. `price_50_lines`: queries 67 → 65; bytes 104043 → 2768; p50/p95 servidor 56.43 / 62.33 → 43.72 / 48.49 ms.

## 20. Payload add/delete

`add_product_20_lines`: queries 68 → 65; bytes 44097–44307 → 45271–45544; p50/p95 servidor 62.36 / 69.78 → 49.89 / 55.25 ms. `delete_line_20_lines`: queries 48 → 46; bytes 40189 → 41312; p50/p95 servidor 56.29 / 67.52 → 43.36 / 47.93 ms. Se publican aumentos de bytes de add/delete derivados de IDs/atributos, sin prometer reducción en esas respuestas completas.

## 21. Search browser

`search`: p50/p95 348.75 / 362.80 → 243.25 / 256.80 ms.

## 22. Add browser

`add`: p50/p95 170.90 / 220.80 → 134.70 / 159.80 ms.

## 23. Quantity browser

`quantity_plus`: p50/p95 128.15 / 144.00 → 119.20 / 157.00 ms. `quantity_enter`: p50/p95 137.15 / 179.60 → 119.75 / 143.30 ms.

## 24. Checkout GET browser

`checkout_1`: p50/p95 124.95 / 168.10 → 91.20 / 110.10 ms. `checkout_20`: p50/p95 109.15 / 137.50 → 92.15 / 120.10 ms. La métrica de disponibilidad de formulario se distingue de la shell visible.

## 25. Checkout POST servidor

card: 191.72 / 197.99 ms; cash_exact: 220.70 / 249.94 ms; cash_change: 206.81 / 218.25 ms; split: 257.26 / 287.20 ms; Cada muestra: Sale fresca, servicios reales, fixture fuera de intervalo y assertions de estado persistido.

## 26. Checkout POST UI

card: 365.05 / 401.10 ms; cash_exact: 397.65 / 437.10 ms; cash_change: 354.55 / 392.40 ms; split: 393.65 / 428.80 ms; Mismo observador de evento → estado visible tras settle; cada muestra usa Sale nueva.

## 27. Click COBRAR → diálogo

1 línea: p50/p95 13.90 / 19.30 ms; 20 líneas: 16.55 / 25.20 ms. Capturado con MutationObserver sobre atributo open.

## 28. Loading shell

Se clona `_checkout_loading.html` al beforeRequest y usa el modal global. Tiene título COBRAR, cierre, aria-busy y status Preparando cobro. El GET sustituye contenido y afterSettle enfoca método/cash sin esperar para mostrar diálogo.

## 29. Double submit

`data-nx-critical-form`, hx-sync drop, disabled y estado global Processing. Listener de submit en capture rechaza programmatic requestSubmit repetido mientras nxProcessing=true. POST bloquea Escape; GET conserva cierre.

## 30. Idempotency keys

UUIDs server-side en GET; POST bound forms se reutilizan en 422/409/error. Resultado incierto conserva DOM y claves. Sale/Payment/Billing utilizan sus servicios/constraints existentes; no se genera una clave nueva al reintentar la misma intención.

## 31. Partial failure

No hay atomic global. Sale completada/stock, pagos y documento son pasos duraderos. Una excepción no borra efectos previos; cada render consulta estado persistido y muestra qué queda. Cobro registrado + billing fallido se comunica como tal.

## 32. Retry billing

Con pending cero, el retry omite pagos y solicita el documento inicial si falta. Test inyecta fallo de emisión tras pago real y comprueba un Payment, un movimiento y un documento al reintentar, sin duplicar cobro.

## 33. Cash vacío

En form/view y preflight, None se considera exacto para la parte física. El POST normal sin HTMX también lo acepta. No se añade campo cash_received a Payment.

## 34. Cash insuficiente

Se valida antes de complete_sale; 422 HTMX con datos/keys preservados y error visible. Sin JavaScript, respuesta HTML del formulario; no hay stock/pago/documento nuevo.

## 35. Cash con cambio

Se muestra la diferencia entre entregado e importe asignado. Ejemplo backend 10,90 € con 20 €: cambio 9,10 €, Payment 10,90 €, movimiento 10,90 €.

## 36. Cents JS

Parser de strings a BigInt céntimos, suma/resta entera y formatter; no parseFloat ni coma flotante para dinero. Backend Decimal sigue siendo autoridad. Inputs inválidos muestran feedback y no simulan éxito.

## 37. Split cash

Test backend de venta 30 €, cash 10 € + card 20 €, tender vacío y 20 €. E2E con cash 10,10 € y tender 20 € verifica cambio 9,90 €, asignado total y pendiente cero exactos, y campos cash ocultos para tarjeta.

## 38. Payment.amount / cash_received

amount = deuda saldada por método; cash_received = dato operativo del formulario para cambio/preflight. No altera amount ni deuda y no se persiste un saldo artificial.

## 39. CashMovement

Solo afecta físico si method.affects_cash_register. amount = Payment.amount; refund resta. No se crean movimientos para tarjeta/transferencia/vale.

## 40. Expected cash

Saldo inicial + pagos cash asignados − refunds cash. Test con apertura 100 € comprueba el delta exacto y retry sin segundo incremento; races comparan closing CashCount con saldo snapshot.

## 41. _cash_context

La ausencia de sesión se rechaza solo para un método físico. Si se suministra sesión, sigue validando business/store/open/registro activo y bloquea la fila como antes. require_open_cash_register no se usa como obligación universal de Payment.

## 42. Matriz require_open_cash_register

Sale abierta: cash sin sesión falla siempre; noncash sin sesión solo puede completar si require_open=False. Sale completada/deuda/refund: noncash sin sesión permitido con ambos valores; físico exige sesión abierta. E2E/HTTP y tests de servicios ejercitan esta separación.

## 43. Noncash sin sesión

Tarjeta, transferencia y vale completed con CashSession null en tests reales. La migración elimina el antiguo check universal; el master backend define cash_session nullable y autoridad affects_cash_register.

## 44. Cash sin sesión

Sigue siendo inválido en modelo, formularios y servicios; no hay Payment/CashMovement. Una sesión ajena, cerrada o con caja inactiva tampoco permite operar.

## 45. Race cierre/checkout

TransactionTestCase PostgreSQL con barrera, conexiones independientes y servicios reales. Se bloquea CashSession antes de stock en complete_sale para evitar el deadlock de commit descubierto; cierre y saldo económico se serializan. Si cierre gana, no entra efectivo después del snapshot; checkout presenta 409 contextual.

## 46. Refund cash/noncash

Refund tarjeta/transferencia/vale sin sesión permitido; cash requiere sesión abierta y produce movimiento negativo por amount. Reglas allows_refund, PIN, tienda, sale_return, amount e idempotencia permanecen vigentes.

## 47. Tenant/store isolation

Selectors y servicios siguen scoped por business/store/sale. Test intenta inyectar IDs de otra Sale y otro tenant en X-TPV-Changed-Lines y verifica que no aparecen en HTML. Métodos, series y sesiones se validan backend, no por atributos JS.

## 48. Locking

Se conservan select_for_update, transacciones por módulo, claves únicas y full_clean. Se añade sesión lock en Sale completion antes de stock; no se crea una transacción que englobe Sales/Payments/Billing. Ninguna prueba captura OperationalError para esconder deadlocks.

## 49. Tests unitarios

Suite existente y reglas de modelo/form y métricas incluidas en la suite Django. La aritmética visual de céntimos se comprueba en E2E. No se añaden dependencias ni sustituciones de servicios para declarar success.

## 50. Tests integración

Payment/no-session/deuda/refund; Checkout cash matrix, insuficiente, split, métodos, emisión fallida/retry; query/payload/isolation y regresiones previas.

## 51. Tests HTTP

POST normal y HTMX, 422 y 409, form errors y UUIDs conservados, cash exact/insuficiente/cambio, una o varias opciones de método y retry de pago/emisión.

## 52. Tests PostgreSQL

Cinco gates locales y GitHub: Billing, Sales (incluye checkout+queries+metrics), Payments, Purchases y Cash. Threads/barreras reales con stock/pagos/saldo/documento verificados. El test de race no se omite en PostgreSQL.

## 53. E2E nuevos/modificados

Barcode Enter y debounce cancelado; última intención visual de dos líneas; shell antes del GET retenido; Processing/double-submit/Escape con POST retenido; efectivo exact/insuficiente/cambio en cuatro viewports; red perdida y 500 tras commit real + replay seguro; fallo parcial de emisión con pago/stock reales y retry de Billing sin segundo cobro; split en céntimos; scroll/footer de 20 líneas y errores locales; setup global espera scripts, usa Enter y expect_response GET/POST sin nxPreparedRegions. Add/delete → quantity y orden inverso comprueban DOM/DB, total y un único refresh cuando corresponde. Nueva venta sin CashSession usa el POST existente. Los reintentos de efectivo conservan 10 € de cambio tras Billing/red; un GET correcto o 422 no ocultan incertidumbre, solo el header de confirmación del mismo intento/surface. Los interceptores retrasan/pierden respuestas, no sustituyen resultados económicos por mocks.

## 54. Django completa

1546 tests sobre PostgreSQL 16: OK. Ruff check/format, check, makemigrations --check --dry-run y collectstatic: OK. CI ejecuta también la suite SQLite según el workflow existente.

## 55. Browser completa

91 tests, los mismos 23 módulos de CI: OK. Chromium real, sin exclusiones del gate ni timeout relajado. Pruebas a 1440×900, 900×900, 375×812 y 375×568 en los escenarios TPV correspondientes.

## 56. Benchmark AFTER

51 escenarios servidor y 12 escenarios navegador. Todos 1 first + 5 warmups + 20 samples; JSONs con muestras individuales, profiler SQL, p50/p95 y bytes. POST usa Sale fresca.

## 57. Comparación BEFORE/AFTER

Ver `tpv-phase7-9-comparison.md` y los cuatro JSON nuevos. Aplicación base exacta vuelta a medir en el entorno actual; mismo PostgreSQL/software/Chromium secuencial. Baseline antiguo preservado byte por byte.

## 58. GitHub Actions

El snapshot de los diez jobs de la implementación se registra en `tpv-phase7-9-actions.json`; los jobs del SHA final de entrega se verifican y enlazan en la descripción de la PR. La PR permanece Draft hasta verificar todos success; no se hace merge.

## 59. Deuda técnica / migración

Migración única necesaria: RemoveConstraint chk_payment_completed_session, pues cero migraciones era incompatible con completed noncash sin sesión. Confirmado en master backend antes del cambio. Para downgrade deben resolverse esas filas null. El cambio se conserva dentro del intento/retry mediante Payment confirmado, UUID y POST original; no se inventa tender tras una recarga sin esos datos. No se agregan campos por presentación. No se persiste cash_received ni se incorpora estado global/motor monetario alternativo. El checklist queda excluido por indicación del usuario.

## 60. Cierre de fases

Fase 7 cerrada: SÍ. Fase 8 cerrada: SÍ. Fase 9 cerrada: SÍ. Benchmark completo y todas las verificaciones de implementación publicadas; los diez jobs del SHA de entrega documental se verifican igualmente antes de marcar ready y se enlazan en el body de #227. No implica merge, ni ampliación a Fase 13.

