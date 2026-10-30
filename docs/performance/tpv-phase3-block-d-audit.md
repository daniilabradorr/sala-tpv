# NETXODO — Fase 3, Bloque D: auditoría de frontend

Base comprobada: `a38898acce06a4360c4a2427895488178225072e`, rama `fix/tpv-checkout-audit-phase3`, inicialmente limpia. `origin/main` verificado mediante fetch: `cdbf88c7df6b5c9d75ccdeda84c8ac8b67b03983`; no se incorpora. Fecha de ejecución: 29/10/2026. Se conservan B, C, P01 y P02. Los informes históricos C describen propuestas entonces pendientes: **P01/P02 ya están implementadas y este bloque no las reimplementa**.

Se han leído los informes A, B diagnostic/findings, C integrity/scenarios/report, P01 implementation, P02 implementation y P01/P02 report. La especificación maestra del frontend no está disponible en el árbol consultado; no se presume su contenido. El informe final y la matriz enlazan los resultados de esta ejecución, separados de la evidencia histórica.

## Recorrido y fuentes revisadas

| Capa | Archivos revisados | Responsabilidad y límite |
|---|---|---|
| Carrito | `static/js/sales_cart.js`, `_cart.html`, `_cart_footer.html`, `_product_grid.html`, `sale_workspace.html` | Intenciones/UUID/recibos/versiones, persistencia local, freeze, flush y lectura autoritativa antes del GET. No decide el importe cobrado. |
| UI de cobro | `static/js/sales_tpv.js`, `_checkout.html`, `_checkout_pending_payment.html`, `checkout.html`, `sale_detail.html` | Modos, vista previa del cambio, formulario, errores, foco y acciones finales. |
| Infraestructura frontend | `static/js/app.js`, `core/htmx-events.js`, `core/checkout-recovery.js`, `core/modal.js`, `core/drawer.js`, `core/sale-start.js`, `templates/base.html` | Eventos, modal, journal, resultado desconocido, bloqueo de envío y navegación. |
| Presentación | `static/css/sales_tpv.css`, estilos de feedback/componentes y tokens existentes | Reflow, scroll, touch, mensajes y foco visible. Sin rediseño global. |
| Servidor (solo lectura) | `apps/sales/{checkout,forms,views}.py`, servicios/selecciones de Sales, Payments, Inventory, CashRegister y Billing | Permisos/Business/Store, estado y saldo persistidos, T1/T2/T3, idempotencia y fiscalidad. Se conserva por hash el backend. |
| Impresión | `_document_preview.html`, `templates/billing/document_print.html`, `static/js/pages/billing-print.js`, vistas/selectores Billing | GET de documento issued existente; `window.print()` no emite otro documento. Nueva venta usa el POST de inicio existente. |

El flujo real es shell de carga → flush (inicialización, cabeceras y mutaciones pendientes) → GET checkout → selección/confirmación explícita → POST → T1/Sale+Inventory → T2 por Payment → T3/Billing → estado persistido → swap/settle → impresión GET → inicio de Sale por POST. Los commits económicos permanecen separados; un error de respuesta no los revierte.

## Hallazgos demostrados antes de corregir

| ID | Causa y reproducción | Efecto observado | Corrección |
|---|---|---|---|
| D-F01 | GET checkout retenido, iniciado con la API pública `htmx.ajax` y source body; después un POST P02 confirma y llega el GET antiguo | El formulario parcial obsoleto sustituye el éxito ya confirmado | Propiedad/revisión por panel y XHR; excluir swaps y limpieza visual de solicitudes obsoletas. |
| D-F02 | Billing retenido mientras procesa el POST; llamadas adicionales `htmx.ajax` con source body | Se enviaban POST, GET, POST; no se observó duplicación económica gracias al servidor | Bloquear solicitudes nuevas del panel durante la mutación y otro POST mientras el formulario declara resultado desconocido. |
| D-F03 | 422 real por efectivo negativo; recuperación P02 standalone | Resumen sin foco; P02 no empezaba en la elección explícita de sesión | Resúmenes enfocables, asociaciones de error por nombre y foco tras settle/inicialización. |
| D-F04 | P02 ofrece importe de una parte y efectivo entregado, sin salida de cambio en su DOM | Faltaba la ayuda visual existente en pago simple/dividido | Vista previa con céntimos enteros basada en el importe de esa parte. No altera payload ni validación. |
| D-F06 | Escape seguido inmediatamente de Enter en móvil; `close` nativo llega tras reabrir | El handler tardío abortaba la nueva apertura: modal abierto, cola descongelada y «Preparando cobro…» permanente | Ignorar ese evento de cierre anterior si el mismo dialog ya está abierto de nuevo. |
| D-F05 | Caducar cookie con intención de carrito pendiente y pedir snapshot | La redirección de login HTML terminaba en `Unexpected token '<' ... not valid JSON` | Detectar redirección/content-type en la lectura y explicar sesión/permisos conservando pendientes. |

F01/F02 son fallos de coordinación del panel demostrados usando un llamador HTMX distinto del formulario. El envío nativo y el enlace P02 habitual ya estaban protegidos por `hx-sync` y controles de formulario; no se atribuye un doble cobro al cajero ni se afirma que un doble clic normal lo provocase. La defensa añadida cubre la API HTMX sin sustituir los locks, UUID y saldo del servidor.

El POST tenía `xhr.timeout=0` sin límite propio (confirmado en A/B y código vendorizado). Se añade una espera de navegador de 60 s cuando no hay otra explícita, usando la recuperación desconocida ya existente en C. Es una decisión de UX, no un plazo transaccional ni una solución de la incidencia original. El test reduce ese plazo a 250 ms para provocar el evento real; no espera 60 s por reloj.

## Estados y mensajes

| Estado | Comportamiento revisado y probado |
|---|---|
| Loading | Shell antes de HTTP; ningún formulario cobrable hasta completar flush y GET. |
| Processing | Botón Procesando…, disabled, aria-busy; Escape/cierre normal bloqueados. Ahora el panel también excluye otra llamada HTMX mientras procesa. |
| Success | Solo respuesta/GET autoritativos con Sale completed, paid, saldo cero y documento issued esperado. |
| 409 | Parcial de conflicto cuando servidor lo autoriza; revisar versión/total/estado. No éxito deducido del HTTP. |
| 422 | Datos ligados y UUID conservados; resumen visible y enfocado, errores asociados a campos incluso de partes split. |
| 403/404 | Aviso de permisos/recurso; no sustituir el panel por una página de error ni relajar autorización. |
| 500/timeout/sendError/abort mutante | «No podemos confirmar el resultado de la operación»; conservar intención, bloquear reenvío ciego, ofrecer GET. Nunca «Pago rechazado». |
| Billing pendiente/P01 | El pago consta registrado; reintentar emisión aunque el método histórico esté inactivo. Sin Payment nuevo. |
| Parcial/P02 | Cobros históricos y saldo persistido; elegir caja válida y confirmar explícitamente la parte. Sin selección silenciosa ni traslado de historia. |
| Completa | Documento, impresión y nueva venta. Imprimir lee; siguiente venta empieza vacía y con otras claves. |

Un GET puede llegar mientras el servidor original continúa tras timeout. La lectura no prueba que ese proceso haya terminado: se conserva la identidad y cualquier replay explícito sigue sujeto a idempotencia/estado/permisos del servidor. No se cancela un POST económico al cerrar ni se inventa rollback.

## Ciclo de vida y rendimiento

Los módulos core tienen guard de inicialización, los mapas de elementos/XHR utilizan referencias débiles y los partials de checkout no reincluyen scripts. No se encuentra hx-boost global que reejecute `sales_tpv.js` en cada swap. Los múltiples handlers HTMX cumplen funciones distintas; su mera cantidad no demuestra duplicación. Las reaperturas y dobles aperturas se contrastan con conteo de solicitudes en la matriz. No se implementa un guard global especulativo de reinyección de scripts ni se elimina el protocolo del carrito.

Las filas optimistas se retiran de su Map al desaparecer y sus callbacks se reemplazan al renderizar. No se ha medido heap sostenido de horas ni se certifica ausencia universal de fugas. No se demuestra un listener duplicado en el recorrido normal. La prueba de cerrar voluntariamente el GET ya pasaba antes: se conserva como regresión, sin suprimir aborts mutantes.

Se instrumentan únicamente pruebas: clic en window capture (el listener capture del carrito detiene el evento en document), flush, beforeRequest/afterRequest, swap/settle, dos rAF después de settle y apertura impresa. Las oportunidades de pintura no equivalen a píxeles físicos. Véanse muestras/rangos en el informe final. No hay telemetría externa ni optimización de Inventory/Billing; no se atribuyen los 20 s originales a ninguna causa sin evidencia.

## Riesgos y límites

No se ejecuta producción, adquirente, emisor fiscal externo, impresora física, Safari/Firefox, SIGKILL real ni caída física de PostgreSQL. Touch/viewport/zoom se simulan en Chromium. El journal en memoria no sobrevive recarga con sessionStorage bloqueado; cambiar permisos/método/sesión puede impedir un replay. Fiscalidad y numeración son controles autoritativos existentes, que corresponde revisar en E. Estas limitaciones no se presentan como resueltas por una corrección visual.
