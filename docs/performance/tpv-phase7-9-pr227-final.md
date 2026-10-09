# PR #227 — respuestas finales (46 puntos)

Medidas reales same-host, PostgreSQL 16; 1 first + 5 warmups + 20 samples. La comparación completa contiene todas las variantes.

## 1. SHA final

Implementación medida: `95eb203d3c5c399107ebd1ee000837d759a1a3f0`. El SHA final de entrega, posterior a la publicación de estos documentos, se muestra en la descripción de PR #227 y en la entrega final. Base: `6c29ca27d8a38bbc7a0e998ea5ab16a060202207`.

## 2. Causa de los cuatro E2E

El helper empezaba a escribir antes de que los scripts diferidos del TPV estuvieran disponibles y usaba flags de afterSettle como sincronización de una búsqueda ahora gobernada por debounce manual. La shell del diálogo también se puede ver antes del foco del contenido definitivo.

## 3. Helper corregido

Espera carga real de scripts; fill + Enter con expect_response del GET de búsqueda; botón del producto visible; click con expect_response del POST lines/add; línea visible en el carrito. No depende de nxPreparedRegions.

## 4. Sin sleeps/timeouts

No se añaden sleeps, no se aumentan timeouts, no se omiten pruebas ni se eliminan asserts. Las respuestas retenidas se liberan mediante eventos y requests reales. El benchmark tiene 5 warmups y 20 samples, sin umbrales artificiales en CI.

## 5. Add → Quantity

ADD B ya se aplica en servidor. Una intención posterior A+ aumenta cartRevision. La respuesta completa de ADD se suprime por antigua; la respuesta pequeña de quantity solo reemplaza A y footer, por lo que B podía faltar visualmente aunque estuviera persistido.

## 6. Delete → Quantity

DELETE B ya se aplica en servidor. A+ vuelve antigua la respuesta completa de DELETE. El fragmento posterior actualiza A/footer y dejaba la antigua B en DOM aunque estuviera eliminada de DB.

## 7. Reconciliación

needsStructure se activa al suprimir una respuesta estructural 200. Tras afterRequest, una microtask comprueba la cola HTMX, las requests activas y answeredRevision === cartRevision. Se hace un GET region=cart al detalle existente, scoped por business/store/sale. El GET también lleva revisión; nunca pisa una intención más nueva. No hay reload, sleeps ni cálculos económicos cliente. El camino común de quantity sigue siendo pequeño.

## 8. Tests de carrera

Se añaden test_structural_add_then_quantity_reconciles_cart, test_structural_delete_then_quantity_reconciles_cart y los dos órdenes inversos. Se conservan los tests de ++++ y A+/B+/A+. Las pruebas PostgreSQL concurrentes de checkout same/different keys y cierre/cobro usan barreras y servicios reales.

## 9. DOM/DB Add → Quantity

A=2 y B visible/persistida; total DOM igual a Sale.total_amount, comprobado sin reload (total 6,05 €). Un único GET de reconciliación. La traza muestra ADD revision 2 suprimida, quantity revision 3 aplicada y reconciliación posterior.

## 10. DOM/DB Delete → Quantity

A=2 y B ausente tanto en DOM como DB; total DOM igual a Sale.total_amount, comprobado sin reload (total 4,84 €). Un único GET de reconciliación. La traza muestra DELETE revision 3 suprimida y quantity revision 4 aplicada.

## 11. NUEVA VENTA con sesión

CTA principal en success, formulario POST al endpoint sale_start_for_session existente. La nueva Sale OPEN conserva la sesión/caja/tienda y vuelve al workspace.

## 12. NUEVA VENTA sin sesión

CTA principal cuando can_sell, formulario POST al endpoint general sale_start existente. E2E require_open=False, tarjeta, sin CashSession: éxito, CTA, POST 302, otra Sale OPEN sin sesión y workspace visible.

## 13. Cambio en Billing retry

La recuperación conserva method, cash_received, mode y partes/UUIDs en inputs hidden. Con pendiente cero el importe se obtiene del Payment completed de esa Sale/business y misma key/method. Se muestra tender/change solo cuando el Payment persistido coincide con la intención. Caso 40/50 conserva Cambio 10 tras la emisión real del retry; un Payment y un movimiento.

## 14. Cambio en network retry

El test permite commit real y pierde solo la respuesta. Reenvía el formulario con las mismas claves y tender. Payment persistido determina amount=40, tender=50 y change=10. Un Payment, CashMovement de 40 y documento, sin segundo cobro.

## 15. Feedback incierto

El feedback almacena payment_idempotency_key y surface. Solo success autoritativo de POST devuelve X-Netxodo-Confirmed-Operation. afterSwap lo oculta si coincide key y diálogo. GET correcto no lo limpia; E2E verifica #nx-feedback oculto tras éxito.

## 16. 422

Conserva diálogo, errores, tender y UUIDs. Una insuficiencia tras desconexión no oculta el aviso de incertidumbre. La confirmación final del mismo intento sí lo oculta. Ningún Payment/CashMovement se crea por la insuficiencia.

## 17. 409

El cierre de sesión/estado cambiado se comunica con mensaje contextual y X-Netxodo-Allow-Error-Swap. Se reconsulta estado persistido y se conservan datos. No se simula success ni se aflojan locks.

## 18. Idempotencia

Mismas keys durante 422, pérdida de respuesta y emisión fallida. Servicios duraderos y constraints existentes evitan pagos/documentos/movimientos duplicados. No hay atomic global que revierta Sale/Payments al fallar Billing.

## 19. Cash exact

Entregado vacío equivale a amount asignado en backend, incluido POST normal sin JavaScript. Payment.amount y CashMovement.amount son iguales; cambio cero.

## 20. Cash insuficiente

Se rechaza antes de Sale completion o pago. HTTP HTMX 422 y estado original conservado: cero Payment, cero CashMovement, sin stock/documento nuevos.

## 21. Cash con cambio

40 de deuda y 50 entregado: Payment=40, CashMovement=40, efectivo entregado=50 y cambio=10 en success. El dinero entregado no incrementa deuda ni balance de caja.

## 22. Split cash

Total 30: efectivo asignado 10, entregado 20, tarjeta 20. Dos Payments, un CashMovement de 10, pendiente cero y cambio 10. E2E adicional con 10,10 verifica cambio 9,90 mediante BigInt céntimos.

## 23. Expected cash

Solo cambia por el importe asignado del Payment físico. Entregado/cambio son presentación y preflight; no crean saldo adicional. Las assertions de balance real y movimientos permanecen.

## 24. Noncash sin sesión

affects_cash_register=False permite Payment/refund sin CashSession. require_open_cash_register sigue siendo política de Sale, independiente. La matriz seis combinaciones continúa cubierta.

## 25. Cierre / checkout

Se serializa CashSession antes de inventario en complete_sale, conservando locks de Sale/Payment/caja. Los threads PostgreSQL verifican que si cierre gana no entra efectivo después del snapshot y no hay deadlock silenciado.

## 26. Refunds

Pagos de devolución no físicos pueden completarse sin sesión tanto con require_open=True como False; físicos exigen sesión abierta y movimiento correcto. Full flow de ERP prueba devolución Ticket/Factura y rectificación real.

## 27. Query counts

`grid_250_all`: queries 13 → 11; bytes 19610 → 19765; p50/p95 servidor 32.08 / 40.21 → 15.24 / 17.92 ms. `add_product_20_lines`: queries 68 → 65; bytes 44097–44307 → 45271–45544; p50/p95 servidor 62.36 / 69.78 → 49.89 / 55.25 ms. `quantity_1_to_2`: queries 66 → 64; bytes 11359 → 2741; p50/p95 servidor 42.13 / 51.62 → 42.85 / 44.58 ms. `header_customer_none_to_customer`: queries 40 → 40; bytes 1723 → 1723; p50/p95 servidor 29.84 / 34.45 → 33.78 / 214.61 ms. `checkout_get_20_lines`: queries 18 → 10; bytes 7292 → 7725; p50/p95 servidor 37.03 / 44.84 → 23.68 / 31.77 ms.

## 28. Payload

`quantity_50_lines`: queries 66 → 64; bytes 104020 → 2746; p50/p95 servidor 58.11 / 60.45 → 40.60 / 43.09 ms. `discount_50_lines`: queries 67 → 65; bytes 104136 → 2861; p50/p95 servidor 58.12 / 60.55 → 41.79 / 48.56 ms. `price_50_lines`: queries 67 → 65; bytes 104043 → 2768; p50/p95 servidor 56.43 / 62.33 → 43.72 / 48.49 ms.

## 29. Search p50/p95

`search`: p50/p95 348.75 / 362.80 → 243.25 / 256.80 ms. Debounce 275 → 175 ms. `barcode_enter`: p50/p95 105.85 / 119.40 → 81.60 / 93.80 ms. Enter no espera el timer.

## 30. Add p50/p95

`add_product_20_lines`: queries 68 → 65; bytes 44097–44307 → 45271–45544; p50/p95 servidor 62.36 / 69.78 → 49.89 / 55.25 ms. `add`: p50/p95 170.90 / 220.80 → 134.70 / 159.80 ms.

## 31. Quantity p50/p95

`quantity_1_to_2`: queries 66 → 64; bytes 11359 → 2741; p50/p95 servidor 42.13 / 51.62 → 42.85 / 44.58 ms. `quantity_plus`: p50/p95 128.15 / 144.00 → 119.20 / 157.00 ms. `quantity_enter`: p50/p95 137.15 / 179.60 → 119.75 / 143.30 ms.

## 32. Checkout GET

`checkout_get_1_lines`: queries 18 → 10; bytes 7287 → 7720; p50/p95 servidor 35.57 / 41.41 → 25.79 / 33.74 ms. `checkout_get_20_lines`: queries 18 → 10; bytes 7292 → 7725; p50/p95 servidor 37.03 / 44.84 → 23.68 / 31.77 ms. `checkout_1`: p50/p95 124.95 / 168.10 → 91.20 / 110.10 ms. `checkout_20`: p50/p95 109.15 / 137.50 → 92.15 / 120.10 ms.

## 33. Checkout POST card

AFTER: queries 293; bytes 2330–2332; servidor p50/p95 191.72 / 197.99 ms; navegador 365.05 / 401.10 ms. Sale fresca en cada muestra; sin baseline histórico de este POST.

## 34. Checkout POST cash exact

AFTER: queries 339; bytes 2432; servidor p50/p95 220.70 / 249.94 ms; navegador 397.65 / 437.10 ms. Sale fresca en cada muestra; sin baseline histórico de este POST.

## 35. Checkout POST cash change

AFTER: queries 339; bytes 2432; servidor p50/p95 206.81 / 218.25 ms; navegador 354.55 / 392.40 ms. Sale fresca en cada muestra; sin baseline histórico de este POST.

## 36. Checkout POST split

AFTER: queries 411; bytes 2455–2457; servidor p50/p95 257.26 / 287.20 ms; navegador 393.65 / 428.80 ms. Sale fresca en cada muestra; sin baseline histórico de este POST.

## 37. Archivos benchmark

tpv-phase7-9-before-server.json, tpv-phase7-9-before-browser.json, tpv-phase7-9-server.json, tpv-phase7-9-browser.json y tpv-phase7-9-comparison.md; patch BEFORE reproducible, informe original de 60 puntos, este de 46 y snapshot Actions. Baseline histórico intacto.

## 38. Nuevos tests

Checkout cash/recovery y CTA sin sesión; matriz Payment/deudas/refunds; PostgreSQL checkout concurrente; queries/payload/isolation; cuatro carreras estructurales, apertura del ticket móvil con ADD retenido y foco preservado, feedback incierto +422, cash40/tender50 perdido y Billing retry; responsive/processing/barcode. Ningún test económico sustituye servicios reales por success mockeado.

## 39. Total Django

1546: suite completa PostgreSQL OK. CI SQLite ejecuta la misma suite: 1546 OK (skipped=30), tests exclusivos PostgreSQL cubiertos en los gates. Ruff/check/migrations/collectstatic verdes.

## 40. Total Browser

91: todos los 23 módulos del workflow; cero failures, cero errors. No se reduce el gate.

## 41. Cada gate PostgreSQL

sales: OK (18); payments: OK (3); purchases: OK (2); billing: OK (10); cash: OK (6)

## 42. Actions finales

Los diez jobs de la implementación tienen success en tpv-phase7-9-actions.json, con Vercel success. El SHA posterior de entrega documental se verifica igualmente y se enlaza en el body final de PR #227: ci, browser-e2e, cinco PostgreSQL, Lint, Format Check y Docker Check.

## 43. Fase 7 cerrada

SÍ: benchmark completo publicado, comparación same-host y regresiones de queries/payload/UX verificadas.

## 44. Fase 8 cerrada

SÍ: checkout instantáneo, processing, retry, cambio conservado, feedback ligado al intento y suite completa verde.

## 45. Fase 9 cerrada

SÍ: exact/insuficiente/cambio/split, Payment.amount, balance físico, sesión condicional, nueva venta y locks/refunds verificados.

## 46. Deuda restante

Sin campos nuevos por tender: una recarga sin POST original no inventa efectivo entregado/cambio. Para revertir payments.0004 deben resolverse Payments noncash con sesión nula. Latencias limitadas al entorno documentado. No se hace merge ni se amplía el scope a otras fases.

