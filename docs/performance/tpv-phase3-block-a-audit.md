# Netxodo — Fase 3, Bloque A: auditoría del checkout

Fecha: 28 de octubre de 2026. Alcance: código local, análisis estático, pruebas sintéticas aisladas y evidencia histórica. No se implementa ninguna corrección.

## 1. Procedencia, Git y alcance verificable

- Repositorio configurado: `https://github.com/daniilabradorr/sala-tpv.git`.
- HEAD local inicial (antes de verificar remoto): `f46dca88ddc2bdf4ebe08a562534d15fcf367211` (`fix(e2e): await TPV initialization and settled header saves`).
- Estado inicial: rama `work`, árbol limpio, sin archivos AGENTS.md encontrados en `/workspace`.
- Rama nueva: `fix/tpv-checkout-audit-phase3`. Base definitiva verificada contra `main` remoto: **`cdbf88c7df6b5c9d75ccdeda84c8ac8b67b03983`**, merge de PR #232. No existía local ni remotamente en la consulta de referencias. La rama provisional se recolocó en ese HEAD antes de crear commits; sin trabajo previo sobrescrito.
- Verificación remota: los primeros intentos sin permiso de red no alcanzaron el proxy. Al ejecutar con el permiso de red de la sesión, `git ls-remote --heads origin main fix/tpv-checkout-audit-phase3` y `git fetch origin main` finalizaron correctamente. El SHA real de main se obtuvo del remoto, no se presupuso. `git diff f46dca88ddc2bdf4ebe08a562534d15fcf367211 cdbf88c7df6b5c9d75ccdeda84c8ac8b67b03983 --exit-code` devolvió 0: ambos árboles son idénticos; toda evidencia y pruebas de este informe aplican también a la base definitiva.
- La instrucción directa del chat solicita rama nueva y subirla: autoriza commit y push de la documentación, sustituyendo la prohibición de push del adjunto. No autoriza merge, PR, despliegue ni cambios de negocio.
- Antes de integrar cambios posteriores de main, verificar diferencias con esta base auditada. No se realizó merge ni force-push.

## 2. Fuentes consultadas y diferencias históricas

Se consultó el encargo adjunto y el código indicado en las referencias de este informe, incluidos módulos indirectos de permisos, auditoría, cuenta de cliente, context processors y arnés de diagnóstico.

Documentación histórica local consultada:

- `tests/performance/DIAGNOSTIC.md`: mediciones fase 1.5 y semántica de instrumentación.
- `docs/performance/tpv-inventory-report.md`: fase 2A; precarga de identidades y validaciones de inventario ya optimizadas.
- `docs/performance/tpv-phase2c-report.md`: lotes, recibos, límites de espera y recuperación.
- `docs/performance/tpv-phase7-9-report.md`: orquestación durable, UX y pagos físicos.
- `docs/performance/pr230-ci-correction.md`: espera de inicialización del carrito.
- `docs/testing/pr232-browser-e2e-lifecycle.md`: deadlock histórico de limpieza de fixtures/servidor E2E; no prueba un deadlock del checkout productivo.

No aparecen los dos DOCX maestros ni el TXT de deudas con esos nombres en el árbol del repositorio. No se han obtenido de servicios externos ni se presume su contenido. Los enlaces históricos no equivalen a documentos consultados en esta sesión. Se contrastaron los documentos locales de PR #230/#232 y el código presente; el commit main remoto confirma el merge de #232. No se consultaron los hilos ni ejecuciones vivas de esas PR.

Diferencias relevantes: la fase 2A ya eliminó la búsqueda inicial de InventoryItem por cada línea; los problemas de inicialización y lifecycle E2E descritos históricamente tienen correcciones presentes. Las cifras anteriores no describen automáticamente este HEAD. El código actual ya contempla `paid` sin documento y reintento de emisión; no es correcto afirmar que todo checkout revierte globalmente ante Billing.

## 3. Arquitectura y secuencia implementada

El navegador mantiene una cola de intenciones de carrito con UUID y recibos; la identidad de esas operaciones **no es** la identidad de Payment o Billing. Django coordina servicios que conservan sus transacciones y validaciones propias. Sale determina editabilidad y stock; Payment determina saldo; Billing conserva snapshots e identidad documental. La impresión lee el documento persistido.

El orden real es: sincronizar carrito → GET checkout → validar formulario y preflight → completar Sale **con Inventory** → registrar cada Payment con su CashMovement cuando procede → emitir Billing → releer estado → renderizar confirmación → GET de impresión → POST de nueva venta.

```mermaid
sequenceDiagram
    actor Cajero
    participant UI as Carrito / HTMX
    participant V as SaleCheckoutView
    participant C as run_checkout
    participant S as Sales / Inventory
    participant P as Payments / Cash
    participant B as Billing
    participant DB as Base de datos
    Cajero->>UI: COBRAR
    UI->>UI: Abrir shell, congelar carrito, flush (presupuesto 20 s)
    UI->>DB: Vía cart-sync: confirmar pendientes y releer (Sale lock en GET)
    UI->>V: GET checkout (después de flush correcto)
    V-->>UI: 200 formulario + versión + UUID pagos/Billing
    Cajero->>UI: Confirmar
    UI->>V: POST checkout (formulario crítico)
    V->>V: Versión y formularios
    V->>C: run_checkout
    C->>DB: BEGIN T1, lock Sale, estado, versión, preflight
    alt Estado ya completo
        C->>DB: Fin T1 sin efectos nuevos
    else Sale abierta
        C->>S: complete_sale (atomic anidado)
        S->>DB: Locks Sale, sesión, líneas, inventario
        S->>DB: Totales, stock, movimientos, completed, auditoría
        C->>DB: COMMIT T1
    else Sale completada parcialmente
        C->>DB: Fin T1 tras preflight
    end
    loop Intenciones mientras haya pendiente
        C->>P: register_sale_payment (T2 por parte)
        P->>DB: Lock Sale y sesión; comprobar UUID y balance
        P->>DB: Payment, CashMovement físico, saldo, cuenta cliente, auditoría
        P->>DB: COMMIT T2
    end
    opt Pendiente cero y falta documento esperado
        C->>B: issue_sale_document (T3)
        B->>DB: Lock Sale, UUID/fingerprint, snapshots e hijos
        B->>DB: Lock serie, número, issued, auditoría, COMMIT T3
    end
    C-->>V: Estado persistido (o excepción con pasos previos conservados)
    V->>DB: Relecturas y opciones; render fuera de T1/T2/T3
    V-->>UI: 200 éxito/recuperación, 422 inválido, 409 conflicto o 500 no capturado
    UI->>UI: Swap checkout-panel, foco, quitar processing
    Cajero->>V: IMPRIMIR: otro GET a BillingDocumentPrintView
    V->>DB: Documento emitido + hijos prefetched, sin emisión nueva
    V-->>UI: HTML F2/F1, window.print al load si autoprint=1
    Cajero->>V: NUEVA VENTA: POST SaleOpenView
    V-->>UI: Redirección al detalle de nueva Sale abierta
```

El diagrama representa las transacciones de la configuración del repositorio: no se encuentra `ATOMIC_REQUESTS` habilitado (`config/settings/base.py:89`). Un `TestCase` añade una transacción exterior de prueba, por lo que no mide estos commits físicos ni valida concurrencia PostgreSQL.

## 4. Recorrido frontend → backend y permisos

| Paso | Implementación y evidencia | Comportamiento observable |
|---|---|---|
| COBRAR | `templates/sales/partials/_cart_footer.html:3`; `static/js/sales_cart.js:888` | Enlace con hx-get, target checkout-panel y sync drop; sin líneas es botón deshabilitado. El listener capture de carrito intercepta el enlace. |
| Abrir shell | `static/js/sales_cart.js:895` | Impide apertura duplicada y cantidades inválidas, congela cola, clona loading y abre dialog antes de acceder al servidor. Todavía no hay formulario de pago. |
| Flush | `static/js/sales_cart.js:381` | Espera la misma inicialización del protocolo, espera cabeceras/operación activa, rechaza headerError, drena cola, rechaza errores/pendientes y relee snapshot. Plazo global 20 s; lecturas/red tienen 15 s (`:15`, `:408`, `:749`). |
| Error o cierre de apertura | `static/js/sales_cart.js:940` y `:961` | Muestra error con vuelta al ticket; cerrar cancela espera y GET asociados, descongela y refresca. No deshace una mutación ya recibida por Django. |
| GET de checkout | `static/js/sales_cart.js:923`; `apps/sales/urls.py:83`; `config/urls.py:24` | `/sales/stores/{store_id}/sales/{sale_pk}/checkout/`, lectura GET limitada a 15 s en esta ruta JS. Solo después de flush correcto. |
| Acceso | `apps/sales/views.py:286`, `:1380`; `apps/users/mixins.py:255`, `:294`, `:332` | Autenticación, negocio y permiso de vender en Store; verifica tienda del negocio; selector filtra Sale por Business y Store. Sin permiso 403; fuera del selector 404; sesión caducada redirige a login. |
| Lectura/render | `apps/sales/selectors.py:261`; `apps/sales/views.py:1391`, `:1459` | Selector de cabecera sin prefetch del carrito/devoluciones; obtiene estado documental, opciones, settings y permisos. GET no ejecuta preflight ni descuentos de stock. |
| Formulario | `apps/sales/forms.py:39`; `templates/sales/partials/_checkout.html:41` | Dos UUID para pago simple/Billing, UUID por parte dividida, cart_version oculto; hx-post, innerHTML, submit deshabilitado y hx-sync this:drop. |
| POST | `apps/sales/views.py:1509` | Rechaza versión ausente/no entera con 409; valida forms antes del orquestador; pago simple usa pendiente del servidor, no un total del navegador. |
| Confirmación | `static/js/core/htmx-events.js:15`, `:61`; `static/js/core/modal.js:3` | Marca formulario y modal processing, cambia texto y bloquea reenvío/cierre/Escape mientras procesa. No constituye exclusión entre pestañas o dispositivos. |

Carrito: GET `SaleCartSyncView` (`apps/sales/views.py:2539`) es lectura con `atomic` y lock de Sale, devuelve snapshot, recibos, protocolo 2, user_id y no-store. POST (`:2582`) verifica usuario declarado y CSRF/permisos, elige `mutate`/`mutate_batch`, responde JSON 200/409/422. En `apps/sales/cart.py:111`, `:125`, `:199` se bloquea Sale, se verifican UUID/fingerprint y versiones, y se confirman conjuntamente efectos y recibos del lote. La operación del carrito no confirma un pago.

## 5. Validaciones, Sale e Inventory

`apps/sales/checkout.py:109` comprueba estado OPEN/COMPLETED, líneas si está abierta, Ticket/Factura y cliente para factura, settings, serie activa compatible con año/tienda/caja, política de pago dividido, métodos activos del negocio, métodos únicos, importes positivos, suma exacta y efectivo entregado suficiente. La suma admite los importes ya persistidos con los mismos UUID para recuperar un split parcial. La sesión se comprueba si la exige completar Sale o mover efectivo; una Sale abierta con sesión asociada también la valida. Este preflight hace lectura de sesión; el lock autoritativo se toma en el servicio.

`run_checkout` (`apps/sales/checkout.py:218`) bloquea Sale y compara versión **antes** de devolver el estado ya completo. Una petición con versión obsoleta puede recibir 409 aunque otro checkout ya haya terminado; GET permite recuperar el estado.

`complete_sale` (`apps/sales/services.py:1004`) relee y bloquea Sale (`_lock_sale`, `:382`), devuelve la ya completada sin repetir stock, rechaza cancelada/devuelta/no abierta y valida vendedor, cliente fiscal y caja. Bloquea CashSession antes de inventario (`:1047`), bloquea SaleLine ordenadas por producto y PK (`:1066`), recalcula totales (`:697`) y valida integridad por línea (`:1078`). Actualiza completed, closed_by y completed_at solo después de todo el stock; auditoría participa en la misma transacción (`:1146`).

Inventory (`apps/sales/services.py:1084`): solo productos físicos con track_stock y control habilitado. Precarga una vez **identidades**, no stock, por Business/Store/productos activos. Cada línea llama `decrease_stock` con referencia Sale/SaleLine y operation_id determinista (`:537`, `:1130`). No fusiona líneas del mismo producto.

`apps/inventory/services.py:514`: valida cantidad y tipo, atomic anidado, lock de InventoryItem con relaciones, comprueba activo y available_stock (incluye reservas mediante el modelo), aplica allow_negative, actualiza stock y crea StockMovement con before/after y relación a la línea. Un fallo de cualquier línea revierte **toda T1**, incluidas salidas anteriores y completed. El UUID de stock no es por sí solo una garantía universal de deduplicación: en este flujo la protección fundamental es el lock de Sale + retorno temprano cuando ya está completed.

## 6. Payments, Cash y cuenta de cliente

Tras salir de T1, `run_checkout` recorre intenciones (`apps/sales/checkout.py:278`). Cada `register_sale_payment` tiene su propio atomic (`apps/payments/services.py:285`):

1. Lock Sale por Business; solo admite completed; valida usuario y método activo.
2. Normaliza importe y busca UUID existente por negocio (`:151`). Compara Sale, método, tipo, importe, devolución y sesión. Si coincide, devuelve el Payment; si difiere, ValidationError. El replay todavía exige autorización y método válido.
3. Lock de sesión si se ha enviado una, incluso para un método no físico (`:118`); efectivo siempre requiere sesión abierta. El checkout transmite la sesión asociada a Sale.
4. Obtiene balance con agregados de pagos/devoluciones; rechaza amount mayor que pendiente y comprueba política split (`:335`). Un UUID distinto no autoriza sobrecobrar.
5. Crea Payment COMPLETED y llama a `register_payment_cash_movement` en savepoint (`:354`). Solo métodos `affects_cash_register` generan CashMovement; el saldo esperado se incrementa por el importe asignado, no por el efectivo entregado (`apps/cash_register/services.py:743`).
6. Recalcula payment_status/pending_amount (`apps/payments/services.py:180`, `:210`), aplica pago de deuda de cliente si existía cargo (`:250`) y registra auditoría. Todo queda en T2, incluido el efecto físico y la cuenta del cliente.

Estados: cero pagado → unpaid; pago parcial → partial; pendiente cero con pago → paid, con reglas adicionales de devolución. No se registra una autorización bancaria remota en esta ruta: se registra el pago interno y su referencia. No aparecen llamadas a pasarela HTTP en el recorrido inspeccionado; esto no demuestra qué hace un terminal externo fuera de la aplicación.

Identidad reforzada por `uniq_payment_business_idempotency` (`apps/payments/models.py:392`) y `uniq_cashmovement_payment` (`apps/cash_register/models.py:616`). Si una parte de split falla, anteriores T2 permanecen. El orquestador refresca Sale entre partes y tras errores de validación.

## 7. Billing: emisión, estados y fallos

- Ticket → F2, Factura → F1 (`apps/sales/checkout.py:45`). El checkout rechaza NONE; el servicio Billing independiente también puede mapear NONE a F2 (`apps/billing/services.py:339`). Son contratos de entrada distintos, no un cambio fiscal realizado aquí.
- `checkout_options` (`apps/sales/checkout.py:89`) y `active_billing_series` (`apps/billing/selectors.py:140`) filtran Business, tipo, año local y ámbitos global/tienda/caja compatibles. Una candidata es automática; varias requieren elección. No se reserva número al abrir checkout.
- Con pendiente cero y documento esperado ausente se llama `issue_sale_document` (`apps/sales/checkout.py:307`), una T3 independiente (`apps/billing/services.py:722`).
- Lock Sale primero; autorización del emisor; UUID y fingerprint canónico de negocio/venta/tipo/serie. Replay compatible devuelve documento histórico; incompatible falla (`apps/billing/services.py:541`, `:553`, `:738`).
- Para nueva emisión comprueba Sale completed, cliente fiscal si F1, y ausencia de documento inicial emitido F1/F2/F3 (`:742`). La exclusión inicial se apoya en lock Sale y comprobación del servicio; no hay un constraint único general por Sale inicial en `apps/billing/models.py:304`.
- Lee todas las SaleLine, valida importes históricos y tratamiento fiscal soportado, toma snapshots de emisor (BusinessProfile), receptor y líneas; crea documento borrador e hijos fiscales (`apps/billing/services.py:365`, `:440`, `:498`, `:776`).
- `_issue_draft` (`:699`) bloquea BillingSeries después de Sale, revalida, incrementa current_number y guarda number/series_text/fecha/status issued. Auditoría es parte de T3 (`:808`). Un fallo revierte documento, hijos y numeración de esa T3; no los pagos ni stock de T1/T2.
- Constraints de UUID por Business y número por serie (`apps/billing/models.py:305`, `:310`); snapshots emitidos protegidos en save/delete y en hijos (`:551`, `:563`). Las escrituras bulk/SQL ajenas al contrato quedan fuera de esa protección de modelo.
- `BillingServiceError` hereda ValidationError (`apps/billing/services.py:75`): la vista lo captura. Perfil fiscal ausente/incompleto, cliente, serie desactivada/cambio de año, fiscalidad no soportada o datos históricos incoherentes pueden impedir emitir aunque Payment ya esté confirmado.

El SHA256 visto aquí es el fingerprint de idempotencia (`apps/billing/services.py:269`), no evidencia de encadenamiento VeriFactu ni de envío a AEAT. No se ha alterado ningún cálculo, serie, número o hash ni se ha emitido un documento real.

## 8. Transacciones y locks

| Unidad | Inicio / fin y persistencia | Locks y trabajo incluido |
|---|---|---|
| Carrito GET | `views.py:2544`, fin antes de respuesta | Sale FOR UPDATE incluso para snapshot; puede esperar al checkout concurrente. |
| Carrito POST | `cart.py:111` / `:199` | Sale; servicios de línea y recibos del lote. Independiente del checkout posterior. |
| T1 | `checkout.py:230` hasta antes del for de pagos | Sale; dentro de complete_sale: Sale otra vez, CashSession, SaleLine por producto/PK e InventoryItem por línea. Settings, permisos, preflight, validaciones, stock y auditoría incluidos. |
| T2 por parte | `payments/services.py:285`, retorno `:407` | Sale; CashSession si asociada; la consulta select_related sin `of` de sesión puede ampliar locks a CashRegister en PostgreSQL. Payment, efecto físico, saldo, deuda y auditoría. |
| T3 | `billing/services.py:722`, retorno `:832` | Sale → BillingSeries. Snapshots, full_clean, hijos y auditoría dentro de la transacción. |
| Cierre de caja | `cash_register/services.py:636`, retorno `:740` | Sesión obtenida con lock (`repositories.py:106`), closing count, estado CLOSED y auditoría; se serializa con servicios que bloquean esa sesión. |
| Render final / impresión | Después de servicios económicos | SELECT adicionales y render fuera de T1/T2/T3. Excepciones aquí no revierten los commits previos. |

Los atomic anidados y savepoints no adelantan el commit exterior. No hay una transacción que englobe stock + todos los pagos + documento en HTTP normal. No se observaron NOWAIT/SKIP LOCKED/plazo explícito de lock en estos servicios; el tiempo real depende de configuración PostgreSQL y contención, no comprobadas aquí. El cierre puede ganar **entre T1 y T2**, dejando Sale completed/stock descontado sin pago, con respuesta recuperable 409; no implica efectivo registrado en una caja ya cerrada.

## 9. Inventario de consultas y mutaciones

Inventario estático de familias SQL; **no** es una captura SQL ni un conteo exacto actual. QuerySets son perezosos; forms, full_clean, permisos y context processors pueden emitir consultas adicionales.

| Etapa | SELECT / locks | Escrituras y coste variable |
|---|---|---|
| Flush | Sale lock, líneas snapshot y recibos por UUID; POST de pendientes | Solo pendientes modifican líneas/totales/versiones/recibos. Siempre hay lectura final antes de GET checkout. |
| GET checkout | Store/permisos, Sale con joins; documento esperado con COUNT de hijos; métodos y series materializados; settings | Sin mutaciones económicas. Payments se evalúa al usarlo en éxito, con method precargado (`payments/selectors.py:57`). |
| POST forms | Repite opciones; ModelChoiceField valida método/serie en BD; settings | Sin efecto económico hasta run_checkout. Cada parte split añade validación de método. |
| Preflight/T1 | Sale y refresh; documento; settings/series/métodos; EXISTS líneas/UUID previos/sesión según rama | Totales, completed y auditoría. SaleLine se lee bloqueada y vuelve a leerse en recálculo. |
| Inventory | Una precarga de identidades, lock y validación de ficha por línea física | Un UPDATE ficha + INSERT movimiento por línea, con validaciones de modelo/constraints. No se elimina esta relectura autoritativa. |
| Payment | Sale lock, método, UUID, sesión lock, agregados balance/devoluciones, métodos usados | INSERT Payment, posible CashMovement/UPDATE sesión; balance se vuelve a agregar al recalcular estado; posible cuenta cliente y auditoría. |
| Billing | Sale lock, UUID, EXISTS documento, serie candidata, líneas, perfil fiscal, serie lock | Borrador, INSERT por línea y grupo fiscal, UPDATE serie/documento, auditoría; save/full_clean por objeto. |
| Respuesta | confirmed_cash_presentation, estado en render, opciones/settings y un estado adicional al decidir header/status | Sin efectos económicos. Consultas repetidas confirmadas por llamadas visibles; conteo pendiente de Bloque B. |
| Impresión | Documento y joins; prefetch líneas, impuestos, relaciones entrantes/salientes; perfil | Sin mutaciones económicas/fiscales. Algunas relaciones prefetch podrían no necesitarse para imprimir. |

Repeticiones concretas: `complete_sale` lee SaleLine con lock (`services.py:1066`) y `_recalculate_locked_sale` la vuelve a leer (`:697`); Billing la lee otra vez (`billing/services.py:440`) para congelar snapshots. `SaleCheckoutView` descarta el estado devuelto por run_checkout y vuelve a consultar en `_render` y en decisión del header/status (`views.py:1621`, `:1644`, `:1651`). No todas estas lecturas son eliminables sin revisar garantías de concurrencia y contratos de modelo.

Billing tiene crecimiento por N líneas: `_create_lines_and_breakdowns` guarda cada hijo y cada grupo, con full_clean (`billing/services.py:498`; `billing/models.py:596`). Es trabajo SQL por elemento confirmado; llamarlo defecto N+1 eliminable o causa de 20 s requiere medir y preservar validaciones. Payments de la confirmación y las líneas de impresión tienen eager loading; no se demuestra N+1 de métodos o líneas renderizadas en esas rutas.

## 10. HTTP, HTMX, resultado y recuperación

| Resultado | HTTP / headers | DOM y recuperación |
|---|---|---|
| GET válido | 200; Vary HX-Request y HX-History-Restore-Request | Parcial si request.htmx; página checkout completa si navegación normal. |
| Versión ausente/inválida o CheckoutConflict | 409 + X-Netxodo-Allow-Error-Swap: true | Handler permite swap del parcial; revisar estado/versión antes de confirmar. |
| Formulario inválido | 422 HTMX, 200 sin HTMX | Conserva formulario ligado y UUID. El global permite swap de 422. |
| ValidationError/ValueError de servicio | 422 HTMX si no está paid; puede ser 200 si paid | Relee estado persistido. Banner genérico y error de servicio; si paid sin documento presenta REINTENTAR EMISIÓN. |
| Éxito completo | 200 + X-Netxodo-Confirmed-Operation con UUID del formulario principal | Swap innerHTML checkout-panel; VENTA COMPLETADA, pagos, documento, preview y acciones. |
| 403/404 | Error de permisos/objeto | Handler evita sustituir panel con página de error y muestra feedback. |
| Excepción no capturada, p. ej. DB/template | Normalmente 500, salvo infraestructura | Resultado mutante desconocido; no swap de error, feedback indica comprobar estado, conserva formulario para recuperar. No significa rollback. |
| Error de transporte sendError | Sin HTTP fiable | Feedback desconocido para mutación; finaliza processing; comprobar GET antes de repetir con las mismas identidades. |
| Autenticación caducada | Redirección login convertida en 204 + HX-Redirect para HTMX | Navegación completa, `expired=1` cuando procede (`apps/core/middleware.py:10`). |
| Impresión | 200 issued; 404 borrador/inaccesible; 405 métodos mutantes | HTML en nueva pestaña; no inicia emisión ni pago. |

Evidencias: `apps/sales/views.py:1459`, `:1509`, `:1633`; `static/js/core/htmx-events.js:77`; `templates/sales/partials/_checkout.html:8`, `:16`, `:37`. Los errores de plantilla ocurren fuera del try del servicio al construir respuesta; pueden ocultar éxito económico sin revertirlo.

`static/js/sales_tpv.js:408` inicializa checkout y `:412` atiende afterSwap para foco. No se recibe un nuevo carrito desde el éxito de checkout; el panel representa la venta persistida. Cerrar el modal refresca la cola, y nueva venta navega a otra Sale.

El POST no tiene el plazo específico de 15 s del GET de apertura: solo este GET recibe `xhr.timeout=15000` (`sales_cart.js:1011`). HTMX vendorizado 1.9.12 declara `timeout:0` (`static/vendor/htmx/1.9.12/htmx.min.js:1`); no se encontró override global de plazo en templates/scripts de aplicación. Una petición que nunca finalice puede mantener processing y bloqueo de cierre hasta que falle red/servidor. No se prueba que esto haya ocurrido en el caso observado.

## 11. Venta completada, impresión y nueva venta

El éxito exige conjuntamente Sale completed, paid, pendiente cero y documento issued **del tipo esperado** (`checkout.py:68`). Tener Payment o Sale completed por separado no muestra VENTA COMPLETADA.

`templates/sales/partials/_document_preview.html:1` muestra emisor, número, COUNT líneas y total del documento; no genera ticket nuevo. IMPRIMIR apunta a `/billing/stores/{store}/documents/{document}/print/?autoprint=1`, target blank, rel noopener y hx-boost false (`_checkout.html:29`).

`BillingDocumentPrintView` (`apps/billing/views.py:215`) solo acepta GET, aplica negocio/acceso a tienda y comprueba issued. `billing_document_detail` precarga hijos y relaciones (`apps/billing/selectors.py:25`, `:95`). Marca skip_app_shell para evitar contexto de navegación y lee branding actual; la identidad fiscal, importes y líneas proceden de snapshots. `templates/billing/document_print.html:18` elige F2 recibo o F1 factura; los partials recorren hijos precargados. `static/js/pages/billing-print.js:10` imprime al load si autoprint=1; puede esperar CSS/imágenes/logo en el navegador. Eso es posterior a confirmar el pago y no explica por sí solo la espera previa al ticket. No se verificó impresora física.

NUEVA VENTA es POST al start con sesión si la había (`_checkout.html:28`). `SaleOpenView` (`apps/sales/views.py:617`) resuelve caja/sesión, valida formulario, llama open_sale y redirige a detalle. GET no crea venta. `static/js/core/sale-start.js:3` bloquea envíos locales dobles y restablece estado en pageshow; no es una deduplicación global de creación de ventas.

## 12. Matriz de integridad: doce escenarios

“Confirmado” significa comportamiento visible en código o prueba indicada; “riesgo” no implica incidente real. Los tests PostgreSQL y E2E se inspeccionaron, no se ejecutaron en esta sesión.

| Escenario | Protección y evidencia | Comportamiento / riesgo | Cobertura existente | Prueba adicional necesaria |
|---|---|---|---|---|
| 1. Doble clic | critical-form, hx-sync drop y botones (`_checkout.html:41`; `htmx-events.js:61`); lock/UUID en servicios | Mitigado local y servidor; red perdida aún puede dejar resultado desconocido | `e2e/browser_htmx_global_ux.py:105`; concurrencia checkout `tests_postgres_checkout.py:88` | Doble submit por ratón/Enter con respuesta retenida y comprobar una sola mutación y desbloqueo. |
| 2. Dos pestañas | cart_version bajo lock (`checkout.py:230`); Payment balance e idempotencia | Puede perder una con conflicto o recuperar éxito; no se demuestra sobrepago usando servicios | `tests_postgres_checkout.py:88`, `:97`; servicio, sin dos pestañas reales | Dos contextos sobre la misma Sale, distintas versiones/UUID y documentos; verificar DOM de ambas. |
| 3. Dos dispositivos | Locks en BD, filtro Business/Store, saldo, documento inicial bajo Sale lock | Mismas garantías servidor; posible contención no medida; barrera de UI no es compartida | Mismos tests concurrentes; Billing `tests_concurrency.py:108` | HTTP de dos procesos/dispositivos, dos billing_key diferentes y misma serie, last-unit-stock. |
| 4. Timeout navegador | Conserva UUID; lectura de estado; replay; POST sin deadline específico (`sales_cart.js:1011`) | Desconocido no equivale a rechazado; posible bloqueo prolongado del modal | `e2e/browser_checkout.py:582`, `:654`; test servicio replay `tests_postgres_checkout.py:88` | Timeout real de XHR y servidor que continúa, en cada frontera T1/T2/T3; comprobar recuperación y processing. |
| 5. Conexión perdida tras commit | GET checkout_state reconstruye estado y servicios deduplican | Pago/documento pueden existir sin respuesta; reabrir verifica éxito | E2E uncertain POST `:582`; servicio concurrente replay `:88` | Cortar respuesta tras commit real T3 en HTTP, antes de primer byte; GET y reintento de ambos UUID. |
| 6. Sale completed y Billing falla | T1/T2 durables, T3 revierte; recuperación según paid (`views.py:1633`) | Estado parcial confirmado por diseño, no rollback global; riesgo alto de atención si no se recupera | `test_checkout.py:454`, `:769` | Fallos de perfil/serie/plantilla reales en fixture; cambio de configuración entre pago y emisión. |
| 7. Payment sin documento | paid + sin documento → CTA solo emisión; pending cero impide nuevo pago | Estado confirmado; recuperación normalmente segura; método desactivado bloquea bound form (H01) | `test_checkout_cash.py:193`; sonda H01 de esta sesión | Añadir regresión permanente del método desactivado y modos split/series cambiantes. |
| 8. Mismo UUID | Compatibilidad Payment (`payments/services.py:151`), fingerprint Billing (`billing/services.py:553`), constraint | Devuelve efecto existente si se llega al servicio y sigue autorizado; no garantiza que cualquier formulario obsoleto valide | `test_checkout.py:420`; `billing/tests_service.py:208`; `tests_postgres_checkout.py:88` | Replay HTTP con referencias/caja/método cambiados; recuperar sin repetir efecto ni ocultar error. |
| 9. UUID diferente | Balance bajo lock Sale, corte pending<=0; Billing lock y EXISTS inicial | No permite sobrepago con saldo agotado; documento existente evita nueva emisión; writer externo fuera de contratos no probado | `tests_postgres_checkout.py:97`; `billing/tests_concurrency.py:108` | Dos billing_key y dos payment_key distintos en HTTP, split parcial incluido. |
| 10. Cierre concurrente caja | Lock sesión en complete_sale/Payment/cierre (`sales/services.py:1047`; `payments/services.py:129`; `cash_register/services.py:660`) | Sin pago físico nuevo sobre sesión cerrada; cierre entre T1/T2 deja completed/unpaid y stock ya aplicado | `tests_postgres_checkout.py:104`; `cash_register/tests/integration/test_concurrency.py:196` | Barrera determinista entre T1/T2 y entre partes split; procedimiento explícito para reasignar/recuperar caja. |
| 11. Stock insuficiente | InventoryItem lock, available_stock, atomic de toda T1 | ValidationError y rollback stock/Sale de T1; no se ejecuta Payment. Si allow_negative, salida permitida | `sales/tests/unit/test_services.py:443`; tests inventario y locking existentes | Última unidad dos ventas HTTP + productos repetidos, reservas y flag negativo. |
| 12. Plantilla falla después de efectos | Render fuera de transacciones económicas y UI distingue 500 desconocido | Puede haber venta, pago y documento emitidos aunque se vea error. Riesgo de ambigüedad, no prueba de duplicidad | E2E 500 `browser_checkout.py:654` es error HTTP; no demuestra TemplateError después de T3 | Inyectar TemplateError solo en render final después de commits y demostrar GET/replay sin duplicar. |

## 13. Hallazgos confirmados y clasificación

No se confirma un incidente CRÍTICO de pago duplicado, pérdida económica o inconsistencia fiscal. La clasificación indica impacto del caso demostrado/potencial, no frecuencia ni causa del síntoma original.

### H01 — Recuperación de Billing bloqueada por método ya cobrado desactivado

**Defecto reproducido en fixture aislada.** Tras pago exitoso y fallo sintético de Billing, desactivar el método y repetir el mismo POST da 422. `_forms` limita el ModelChoiceField a métodos activos y `form.is_valid()` se ejecuta antes de decidir que solo falta emisión. El template paid conserva `method` oculto pero no muestra sus errores, porque el bloque de errores de método está dentro de pending_amount > 0. El usuario recibe REINTENTAR EMISIÓN sin explicación de por qué no avanza. Un GET nuevo elimina el método histórico del formulario y permite emitir sin segundo pago.

| ID | Gravedad | Componente | Evidencia | Impacto | Propuesta |
|---|---|---|---|---|---|
| H01 | ALTO | Formulario / recuperación Billing | `sales/views.py:1397`, `:1533`; `sales/forms.py:43`, `:60`; `_checkout.html:50`, `:57`, `:69`; sonda de §16 | Venta paid sin ticket; reintento ligado bloqueado con error oculto | En bloque de corrección separar validación de intención ya confirmada de emisión pendiente; preservar UUID/autorización. Exponer todos los errores y cubrir regresión. |

Reproducción: fixture `CheckoutIntegrationTests.setUp`; crear Sale Ticket y serie; POST tarjeta con UUID fijos y cart_version; simular `issue_sale_document` → ValidationError; comprobar un Payment y cero documentos; desactivar tarjeta; repetir cuerpo → 422, error `method` en contexto, cero nodos field-error y cero documentos; GET nuevo + POST single con método vacío y UUID nuevos → un documento, sigue un Payment. No prueba el caso de 20 s.

### H02 — Relecturas de cabecera/estado y líneas

**Confirmado estáticamente; impacto temporal sin medir en este HEAD.** Algunas revalidaciones son necesarias en las fronteras de transacción; no se propone eliminarlas a ciegas.

| ID | Gravedad | Componente | Evidencia | Impacto | Propuesta |
|---|---|---|---|---|---|
| H02 | MEDIO | Sales / respuesta | `sales/services.py:1066`, `:697`; `billing/services.py:440`; `sales/views.py:1621`, `:1651`; `checkout.py:68` | Consultas/carga repetidas y trabajo después de confirmar economía | Medir llamadas/SQL de state/options/render y coste de cada relectura; evaluar reutilización solo dentro de garantías de consistencia. |

### H03 — Coste fiscal por línea dentro de T3

**Patrón confirmado, no defecto fiscal.** Escrituras, validaciones y auditoría son síncronas; inventario también mantiene lock hasta terminar T1.

| ID | Gravedad | Componente | Evidencia | Impacto | Propuesta |
|---|---|---|---|---|---|
| H03 | MEDIO | Billing / Inventory | `billing/services.py:498`, `:699`; `billing/models.py:596`; `inventory/services.py:540` | Trabajo crece con líneas y mantiene locks; posible espera entre ventas de la misma serie/productos | Descomponer tiempo/SQL con arnés existente. No introducir bulk ni omitir full_clean, snapshots, señales o numeración en este bloque. |

### H04 — Validaciones fiscales tardías producen estado parcial previsto

**Comportamiento confirmado y cubierto, no defecto de atomicidad.** Preflight selecciona serie y cliente básico; perfil emisor completo y compatibilidad fiscal detallada se verifican en Billing después del pago.

| ID | Gravedad | Componente | Evidencia | Impacto | Propuesta |
|---|---|---|---|---|---|
| H04 | ALTO | Orquestación / Billing | `checkout.py:109`, `:307`; `billing/services.py:365`, `:427`; `test_checkout.py:454` | Sale completed/paid sin documento hasta resolver causa; no hay rollback de Payment | Documentar y medir causas de emisión pendiente; evaluar validaciones informativas previas manteniendo revalidación autoritativa; garantizar recuperación y visibilidad. |

## 14. Hipótesis y riesgos todavía no demostrados

| ID | Gravedad | Componente | Evidencia | Impacto | Propuesta |
|---|---|---|---|---|---|
| R01 | ALTO | POST / modal | Plazo HTMX 0 en vendorizado; POST crítico y bloqueo cierre; `htmx-events.js:15`, `modal.js:3` | Si servidor/red no finaliza, processing puede prolongarse; no hay medición de caso real | En B retener POST y observar todos los eventos/finalización; diseñar recuperación desconocida antes de cambiar plazos. |
| R02 | ALTO | Render posterior a commits | `views.py:1650`; render fuera de T1/T2/T3 | TemplateError puede esconder éxito económico/fiscal; no reproducido | Inyección controlada después de T3 y verificación de GET/replay. |
| R03 | ALTO | Caja entre pasos | T1 libera sesión antes de T2; `checkout.py:278`; cierre `cash_register/services.py:619` | Caja puede cerrarse después de stock y antes de pago; recuperación operativa puede requerir intervención | Carrera determinista en BD desechable; evaluar contexto de caja alternativo para venta completed, sin modificarlo ahora. |
| R04 | MEDIO | Contención BD / workers / red | Locks en §8; arnés de lock disponible; sin trazas productivas | Locks, cola de worker, WAN o conexiones podrían contribuir a demora | Correlacionar traza HTTP, PID, wait_event y blocker; medir cola con timestamp proxy fiable. |
| R05 | MEDIO | Flush inicial | `sales_cart.js:17`, `:381`, `:923` | Puede consumir hasta 20 s antes de GET checkout | Separar interacción COBRAR de POST confirmar en navegador. Coincidencia numérica no demuestra causalidad. |
| R06 | BAJO | Lectura de impresión | `billing/selectors.py:25`; `billing/views.py:220` | Prefetch de relaciones no siempre usado; load espera imágenes/CSS | Medir impresión aparte; confirmar utilidad de cada prefetch sin alterar identidad fiscal. |

No se atribuye lentitud a Render, PostgreSQL, Gunicorn, Payments, Billing o HTMX. No hay evidencia actual de llamada bancaria/fiscal de 20 s en el proceso inspeccionado. La disponibilidad, autenticación y configuración del despliegue real no fueron verificadas.

## 15. Rendimiento: evidencia disponible y límites

`tests/performance/DIAGNOSTIC.md:15` documenta HTTP local fase 1.5: POST con emisión p50 298,3 / 629,9 / 1.303,4 ms para 1/20/50 líneas; no reprodujo 20 s. Son resultados históricos de otra base, no una medición de esta sesión. El reporte fase 2A ya compara inventario optimizado y reporta POST p50 posterior 267,20 / 636,90 / 1.175,00 ms y SQL 325 / 879 / 1.749 (véase tabla de comparación en `tpv-inventory-report.md`). No se usa la fase 1.5 como estado actual ni se propone rehacer 2A.

La instrumentación existente (`tests/performance/diagnostic.py:106`) envuelve alias reales de run_checkout, checkout_state/options, complete_sale, register_sale_payment, issue_sale_document, decrease_stock, creación de hijos y render. `Trace.execute` (`:40`) registra tiempo y contador SQL/PID, sin retener SQL/parámetros. Conexión/commit/rollback se miden separadamente. Está opt-in por settings diagnóstico; el middleware base no lo habilita por defecto.

Los spans son inclusivos: no sumar inventory + complete_sale + checkout, ni percentiles entre etapas. sql_execute mezcla ejecución, red y espera lock; no equivale a tiempo puro del servidor. El arnés cuenta savepoints. El hook Gunicorn posterior a asignación no mide cola previa al worker. La pintura usa dos frames, no impresión física. Esta sesión no ejecutó benchmark ni carga ni habilitó instrumentación de producción.

## 16. Cobertura inspeccionada y verificaciones ejecutadas

Se inspeccionaron los tests referenciados en §12 y:

- `apps/sales/tests/integration/test_checkout.py:312`, `:393`, `:420`, `:454`, `:488`, `:508`, `:769`, `:795`: métodos, split, replay parcial, fallos durables, tipo de documento, impresión y 422.
- `apps/sales/tests/integration/test_checkout_cash.py:38`, `:132`, `:193`, `:224`: cambio/efectivo, conflicto caja, recuperación Billing y nueva venta.
- `apps/sales/tests/unit/test_services.py:338`, `:365`, `:425`, `:443`: stock, idempotencia y rollback ante auditoría/stock.
- `apps/sales/tests_postgres_checkout.py:88`, `:97`, `:104`: dos llamadas concurrentes/replay, UUID distintos y cierre de caja. El helper no pasa expected_version y comparte billing_key: no cubre por sí solo dos formularios HTTP con versiones/billing_key distintos. El nombre timeout_replay representa replay de servicio, no pérdida real del transporte.
- `apps/payments/tests_postgres_locking.py:84`: lock Sale con relación nullable.
- `apps/billing/tests_concurrency.py:108`, `:127`, `:149`, `:169`: misma venta/distintas claves, ventas distintas/serie compartida, replay y colisión de clave.
- `apps/billing/tests_service.py:208`, `:259`, `:517`, `:698`, `:717`: idempotencia/autorización/snapshots/rollback número/auditoría.
- `apps/billing/tests_print.py:181`, `:184`, `:189`, `:340`, `:526`: GET repetidos sin mutaciones, métodos mutantes rechazados, prefetch y render sin consultas de hijos.
- `e2e/browser_checkout.py:582`, `:654`, `:698`; `e2e/browser_htmx_global_ux.py:105`, `:341`: respuesta desconocida, 500, recuperación y estado UI. Inspeccionados, no ejecutados aquí.

**Pruebas ejecutadas:**

```bash
.venv/bin/python manage.py test \
  apps.sales.tests.integration.test_checkout \
  apps.sales.tests.integration.test_checkout_cash \
  apps.billing.tests_service apps.billing.tests_print \
  --settings=config.settings.diagnostic --noinput --verbosity=1
```

Resultado: **98 tests, OK**, 12,199 s; system check sin incidencias. La configuración `config/settings/diagnostic.py:6` impone SQLite `:memory:` y no hereda la base de DATABASE_URL. Solo fixtures sintéticas; la base de test se destruyó al terminar. No se ejecutaron migraciones ni comandos sobre una base real; el runner creó su esquema desechable de pruebas.

Sonda adicional H01: un caso construido sobre la fixture existente y ejecutado con DiscoverRunner y esos mismos settings. Resultado: **1 test, OK**, 0,594 s. Verifica explícitamente paid sin documento, POST con método desactivado → 422 y error oculto, GET nuevo y emisión sin otro Payment. La sonda es scratch de esta sesión, no cambio de suite ni lógica productiva. La primera tentativa del arnés manual no llamó setup_test_environment y fue rechazada por ALLOWED_HOSTS; se corrigió únicamente el arnés temporal y se ejecutó con testserver autorizado por Django.

Estos 99 casos no establecen comportamiento de locks PostgreSQL ni commit HTTP: SQLite y TestCase no son válidos para esa conclusión. No se dio por disponible una PostgreSQL de pruebas claramente aislada y no se ejecutaron tests de concurrencia/benchmark de BD real.

## 17. Bloque B: mediciones y pruebas concretas

1. **Fijar procedencia:** SHA realmente desplegado, main remoto, assets servidos, configuración de workers/timeouts/DB/pooler y versión del protocolo. Repetir auditoría de diferencias si no coincide con este HEAD.
2. **Capturar un caso lento correlacionado:** evento COBRAR, duración flush y cabeceras pendientes, GET checkout, submit confirmar, beforeRequest, inicio Django, etapas, commit/rollback, fin servidor, Resource Timing, swap/settle y dos frames. Separar impresión/nueva venta. Mantener un trace_id técnico, nunca UUID económicos o datos personales en logs.
3. **Usar arnés actual en entorno desechable:** 1/20/50 líneas; productos distintos/repetidos; stock ON/OFF; F1/F2; cash/card y split. Muestras fresh, warm/cold, número de repeticiones y configuración declarados. No emitir documentos ni ejecutar cobros reales.
4. **Descomponer servidor:** llamadas y SQL de state/options/forms/complete_sale/inventory/payment/billing/billing_lines/html_render; medir conexión, commit, rollback y error por fase; comparar con validaciones y contexto app_shell (`apps/core/context_processors.py:26`). No sumar spans inclusivos ni p95.
5. **Contención:** correlacionar PID de traza con pg_stat_activity, wait_event_type/event y pg_blocking_pids en intervalo lento; duración de T1/T2/T3 y tiempo del lock Sale/sesión/inventario/serie. Medir colas externas con timestamp edge/proxy sincronizado y fiable; no deducirlas del hook pre_request.
6. **Fronteras durables:** interrumpir antes/después de cada commit con servidor HTTP real en PostgreSQL aislada: fallo Payment, fallo parte 2, fallo Billing, pérdida de respuesta post-T3 y TemplateError final. Después, solo GET para observar y replay con mismas claves para verificar counts/saldos.
7. **Carreras no cubiertas:** dos pestañas/dispositivos con expected_version y billing_key diferentes; cierre situado exactamente entre T1/T2 y entre partes; última unidad; cambio de serie/método/perfil durante recuperación. Comprobar un Payment por intención, stock una vez, cash solo físico y documento inicial uno con numeración coherente.
8. **H01 como regresión futura:** reproducir POST ligado de emisión pendiente con método desactivado, split y settings cambiados; validar que el usuario entiende el error y puede recuperar sin recobrar. No corregir hasta acordar siguiente bloque.
9. **POST retenido y errores UI:** observar timeout/sendError/responseError/afterRequest, restablecimiento de processing, bloqueo de cierre y preservación UUID; resultado siempre desconocido hasta lectura autoritativa. Probar navegación sin JS y caducidad CSRF/login.
10. **Medir impresión separada:** TTFB del GET, consultas de detalle/prefetch, CSS/logo hasta load y apertura de print. Diferenciar documento emitido de impresión física exitosa.

Criterio para atribuir causa: traza del intervalo lento que localice el tiempo, correlación con espera/recurso y reproducción controlada manteniendo integridad. Los síntomas y los históricos por sí solos no bastan.

## 18. Limitaciones y estado de entrega

Se inspeccionó el recorrido local desde COBRAR hasta impresión y nueva venta, incluidos Sales/Inventory/Payments/Cash/Billing, permisos, HTTP/HTMX y recuperación. **No se declara validación integral del entorno real:** hilos y ejecuciones vivas de PR no inspeccionados, documentos maestros no disponibles localmente, despliegue/configuración/logs productivos no inspeccionados, caso original de 20 s no reproducido, PostgreSQL concurrente y navegador/impresora no ejecutados en esta sesión. Los doce escenarios tienen análisis de código; varios requieren las pruebas adicionales de §12/§17.

La única modificación versionable de esta entrega es `docs/performance/tpv-phase3-block-a-audit.md`. No cambia código de negocio, modelos, migraciones, fiscalidad, infraestructura o contratos de idempotencia. No se desplegó ni se creó PR/merge. El commit documental y push de esta rama están autorizados por la petición del chat. Se verificó con diff que la base remota tiene el mismo código auditado. El SHA final documental y la confirmación de publicación se comunican fuera del propio commit para evitar referencias circulares.
