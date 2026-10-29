# NETXODO — Bloque D: correcciones y decisiones

Base: `a38898acce06a4360c4a2427895488178225072e`. Cambios locales revisables; sin commit/publicación. [Auditoría](tpv-phase3-block-d-audit.md), [matriz](tpv-phase3-block-d-e2e.md) e [informe final](tpv-phase3-block-d-report.md) distinguen resultados finales de reproducciones iniciales.

## Aplicación

| Archivo | Cambio y razón | Contrato conservado |
|---|---|---|
| `static/js/core/htmx-events.js` | WeakMaps de revisión del panel y propiedad del XHR; bloqueo de nuevas solicitudes mientras procesa, bloqueo de POST desconocido, exclusión de respuestas/errores visuales antiguos. Espera de navegador acotada a60s salvo override explícito. | No cancela el POST original, no repite pagos, no genera UUID ni deduce éxito/rollback. Los demás targets HTMX mantienen su comportamiento. |
| `static/js/sales_cart.js` | Mensaje comprensible cuando snapshot redirige a login o devuelve contenido distinto de JSON; ignorar `close` nativo tardío si el dialog ya está reabierto. | Mismos UUID, flight, recibos, versión, orden, lotes, flush, persistencia local y endpoints. No se descartan pendientes ni se reinicia su identidad. |
| `static/js/sales_tpv.js` | Inicialización idempotente por checkout existente; asociar errores renderizados por nombre de campo y enfocar resumen/selección de sesión P02, también standalone. No quitar foco a alguien que ya escribe dentro. Preview P02 con BigInt en céntimos sobre el importe explícito de la parte. | Cambia presentación; los importes finales y el saldo vienen de servidor. No cambia UUID, importe enviado, método, checkbox ni sesión. |
| `templates/sales/partials/_checkout.html` | Resúmenes con id/tabindex y referencias de error por campo normal/split, incluyendo errores ocultos. | Condiciones de pago/estado, formularios, actions, claves y headers intactos. |
| `templates/sales/partials/_checkout_pending_payment.html` | Metadato cash en opciones del select existente; resumen accesible y salida de cambio de la parte. | Mismo name/id/choices activas/valor ligado y required del método; elección de sesión vacía y confirmación explícita existentes. No oculta ni deshabilita campos necesarios. |
| `static/css/sales_tpv.css` | Contorno del resumen enfocado usando `--focus-ring`. | Sin cambios globales de colores, tipografía, breakpoints ni componentes. |

El guard de panel no es un mecanismo de exclusión económica entre dispositivos. Antes del cambio, las protecciones nativas y `hx-sync` ya evitaban el doble envío habitual; otra fuente `htmx.ajax` podía eludirlas. La reproducción retuvo la respuesta GET/etapa Billing de forma controlada. El servidor protegió la integridad incluso antes del cambio; ahora la UI no envía esas solicitudes incompatibles ni reemplaza un resultado más reciente.

El cierre tardío se reprodujo dos veces con la nueva prueba de teclado: después de Escape→Enter aparecía dialog.open=true, queue.frozen=false y panel de carga sin formulario. El evento nativo encolado pertenecía a la apertura anterior. Comprobar dialog.open evita que ese evento aborte el nuevo AbortController local. No se añade una pausa artificial al teclado ni se suprime la gestión de abort de un POST.

## Pruebas y observación nuevas

`e2e/browser_checkout_frontend_d.py` utiliza Chromium real, Django LiveServer y PostgreSQL de pruebas, fixtures sintéticas, aserciones de persistencia y rutas de fallo controladas. Reutiliza la fixture de navegador autorizada, termina y une workers antes de flush y cierra conexiones del hilo de Playwright. No cambia el guard async de producción: el override se limita a la clase de test. Los errores JS de interacción y popups del módulo se recogen; la ausencia de error no sustituye las aserciones de estado económico.

`e2e/browser_optimistic_cart.py` amplía únicamente el arranque de `CollectedCartAssetsBrowserTests` para admitir `TPV_CHROMIUM`, como las otras pruebas. No cambia sus aserciones. El primer lote de carrito terminó con42 PASS y un error antes de arrancar ese navegador; el test restante se ejecutó después con Chromium instalado, `collectstatic` temporal y almacenamiento Manifest/WhiteNoise:1 PASS. No se instala el bundle de Playwright ni se cambia configuración de producto.

`e2e/checkout_frontend_d_observer.js` solo se inyecta en pruebas. Recoge tiempos/categorías/status, sin POST, URL, cookie, CSRF, UUID o HTML. Wrapper flush conserva el resultado y las excepciones. Dos rAF después de afterSettle separan finalización HTMX de oportunidad de pintura; el observador MutationObserver también mide visibilidad. Las muestras antes/después usan el mismo arnés y cinco ventas nuevas. No se incluye el coste de preparar fixtures.

Se conservan las suites existentes de carrito, checkout, recuperación C y P01/P02. Las nuevas pruebas de contraste usan muestras de colores calculados, no afirman certificar WCAG para toda la aplicación. Impresión se comprueba con HTML y stub de `window.print()`; no se certifica diálogo nativo, cancelación física ni papel.

## Reproducciones y correcciones del arnés

Los intentos iniciales quedan en `/workspace/work/phase3-d`, separados de las ejecuciones finales. Se afinó la prueba de GET obsoleto para usar source body: el enlace del formulario heredaba `hx-sync`/disabled y ya bloqueaba el caso habitual. La prueba P02 espera ahora la respuesta y una intención nueva antes de consultar BD, evitando leer la forma anterior todavía visible. Se reparó una edición intermedia demasiado amplia de `sales_tpv.js` antes de cualquier validación final; el diff definitivo solo incluye los cambios descritos.

El primer observador de rendimiento no veía el click COBRAR porque el carrito detiene su propagación en document; se movió la captura a window y se volvió a medir la base. También se distingue dos rAF de visibilidad de dos rAF **posteriores a settle**. Solo la versión final comparable se utiliza para el informe.

## Decisiones conservadas y trabajo posterior

- P01 recupera Billing desde estado autoritativo paid/pending0; el método histórico inactivo no crea ni bloquea un Payment nuevo porque no se intenta registrar ninguno.
- P02 conserva Sale/documento/sesión/Payments/CashMovements históricos; el nuevo pago va únicamente al destino explícito válido bajo reglas existentes. El preview no implementa una segunda contabilidad.
- Se mantienen permisos actuales, validaciones fiscales, locks y T1/T2/T3 separados. Ningún cambio en `apps/`, `config/`, migraciones o lockfile; comprobación por manifiesto SHA256.
- No se hace optimización Inventory/Billing ni se acepta suprimir validaciones para reducir latencia. B conserva las propuestas de rendimiento para otro encargo.
- Quedan los seis fallos de catálogo de pytest, validación fiscal/documental del Bloque E, staging/configuración real y dispositivos físicos. No se implementan fuera del alcance.
