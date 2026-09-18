# HTMX Global UX Layer

HTMX se usa dentro de regiones semánticas estables para interacciones parciales; la navegación entre módulos continúa siendo navegación completa. Una respuesta parcial contiene únicamente el target (nunca `html`, `head`, shell ni scripts). No se usa `hx-boost` global.

## Superficies

Un `<dialog data-nx-modal id="example">` se abre con `data-nx-modal-trigger="example"` y se cierra con `data-nx-modal-close`. El modal nativo aporta modalización, trap de foco y Escape; la capa restaura foco y bloquea el cierre durante `data-nx-processing="true"`.

El drawer usa el mismo árbol en todos los tamaños: `data-nx-drawer`, `data-nx-drawer-trigger="id"` y `data-nx-drawer-close`. Es lateral desde 768 px y bottom sheet hasta 767 px. El selector de tienda conserva sus selectores históricos pero usa este contrato.

## Feedback y eventos

`nx:toast` acepta `{message, tone, timeout}`. El mensaje siempre se escribe con `textContent`, los tonos válidos son `success`, `info`, `warning` y `error`, y la región es `aria-live="polite"`. Los errores que requieren atención usan feedback persistente, no un toast efímero.

El helper `add_hx_trigger(response, events)` combina eventos JSON en `HX-Trigger`. Eventos globales:

- `nx:toast`: muestra feedback transitorio.
- `nx:close-modal` / `nx:close-drawer`: cierran la superficie abierta; opcionalmente aceptan un `id` seguro.
- `nx:refresh-region`: acepta únicamente un selector de ID y dispara `nx:refresh` local. La URL permanece declarada en el DOM mediante `hx-trigger="nx:refresh"`.

## Requests y errores

`htmx:beforeRequest` marca solamente el target con `aria-busy` e `is-loading`; todos los finales de request y errores lo limpian. Los formularios críticos usan `data-nx-critical-form` y `data-loading-text`: se conserva el texto, se evita doble envío y la superficie no se puede cerrar durante el request.

En error de red no se afirma fracaso: se indica que el resultado no puede confirmarse y se recomienda verificar antes de repetir. La clave de idempotencia no se crea, borra ni cambia en JavaScript; bloqueo de UI e idempotencia/transacción del backend son defensas distintas.

- **422:** se permite el swap del mismo formulario, preservando valores y errores inline.
- **403:** no se swapea; mensaje persistente de permiso.
- **404:** no se swapea; se informa que el recurso ya no está disponible.
- **409:** no se swapea; se recomienda actualizar el estado real.
- **500:** no se swapea ni se filtran detalles internos; mensaje genérico persistente.

## CSRF, sesión y foco

La plantilla base publica el token CSRF en un `meta`; `htmx:configRequest` añade `X-CSRFToken` solo a POST/PUT/PATCH/DELETE. Los `{% csrf_token %}` tradicionales y `CsrfViewMiddleware` siguen siendo obligatorios.

Si una petición HTMX anónima recibe exactamente un redirect al login, middleware dedicado devuelve 204 con `HX-Redirect`, conservando `next`. Otros redirects mantienen su semántica. Así nunca se inserta la página de login en un target.

Los swaps normales no mueven el foco. Modal y drawer sí lo gestionan deliberadamente y lo devuelven al trigger al cerrar. Skeletons, cuando existan, son decorativos (`aria-hidden="true"`) y no se activan globalmente para requests breves.
