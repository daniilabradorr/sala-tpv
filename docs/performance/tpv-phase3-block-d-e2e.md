# NETXODO — Bloque D: matriz E2E y UX

Chromium151 real contra Django LiveServer y PostgreSQL16 desechable. Fixtures sintéticas; ningún cobro/documento real. Evidencia numérica y comandos en [JSON](tpv-phase3-block-d-evidence.json); resultados agregados, fallos previos y límites en [informe](tpv-phase3-block-d-report.md). Una fila puede corresponder a varias ejecuciones/tamaños; no se equiparan escenarios, métodos de test ni subtests.

Convención: venta estándar12,10€, una línea física, stock1000. P/D/S/C = Payments completed/documentos issued/StockMovements/CashMovements físicos por venta. Se comprueba estado persistido, no se deduce del200. Los UUID se comparan en memoria del test y no se exportan. Impresión usa stub de window.print que retorna sin papel; cierre/repetición de pestaña comprueban ausencia de mutaciones.

## D01–D26

| ID | Precondición | Acción / fallo | Estado visual y HTTP | Persistencia y mutación económica | Evidencia / resultado |
|---|---|---|---|---|---|
| D01 | Abierta, sesión válida, tarjeta | COBRAR, elegir tarjeta, Enter confirmar | Success; GET200/POST200 | completed/paid, saldo0,12,10€; P1/D1/S1/C0, stock999 | `D-full-card`; PASS |
| D02 | Igual, efectivo | Entregado20€, confirmar | Preview7,90€; success200 | P1/D1/S1/C1; caja+12,10€, no+20€ | `D-full-cash` y suite checkout cash; PASS |
| D03 | Split permitido | Cash6,05+card6,05, Enter | Success200; parcial/error preserva claves en otras pruebas | P2/D1/S1/C1, saldo0; primera parte no se repite | `D-full-split`, recovery split_partial×3; PASS |
| D04 | Cliente fiscal y serie F1 | Cobrar tarjeta, abrir documento | Success200 y factura F1 correcta | P1/D1/S1/C0; imprimir no cambia número/documento | `D-full-invoice`; PASS |
| D05 | Solicitud ticket y serie F2 | Cobrar e imprimir | Success200; FACTURA SIMPLIFICADA en impresión | Un F2 issued del tipo solicitado | `D-full-card/cash/split`, P02 browser; PASS |
| D06 | Checkout abierto sin confirmar | Escape/cierre; GET retenido | Modal cerrado, foco vuelve, sin falso aviso de red | P0/D0/S0/C0; no se ejecuta checkout POST | `D-cancel-read`, responsive y core checkout; PASS antes/después |
| D07 | Abierta con líneas | Doble clic COBRAR y cinco ciclos Escape/Enter | Una lectura por apertura, sin formularios duplicados; GET200 | P0/D0/S0/C0 | `D-double-open-cycles`:6 GET para6 aperturas; PASS |
| D08 | POST retenido antes de Billing | Doble submit/requestSubmit y API HTMX POST/GET adicional | Processing; solo POST original enviado | Una confirmación económica, sin sobrepago | `D-processing-requests`, recovery double_submit, PostgreSQL; PASS |
| D09 | Versión del formulario obsoleta | Cambiar versión/otra pestaña y confirmar | POST409, resumen visible; total/versión actuales antes de retry | Sin efectos con versión vieja; después confirmación explícita única | `D-version`, `D-two-browser-tabs`; PASS |
| D10 | Form cash con valor negativo | Forzar envío para probar validación servidor | POST422, resumen enfocado, aria-invalid/describedby | open/unpaid; P0/D0/S0/C0 | `D-errors-focus`; PASS |
| D11 | T1/T2/T3 confirmadas | Fallar render POST de forma controlada | HTTP500 real; mensaje desconocido; GET200 muestra éxito | Ya P1/D1/S1; GET no añade efectos | recovery `render_500`×3; PASS |
| D12 | POST retenido antes de T1 | XHR timeout real250ms; liberar servidor; consultar | Unknown/disabled, GET200 success; no replay automático | Antes open/P0/S0, después P1/D1/S1 con un solo POST | `D-timeout-before-t1`; además timeout antes de T3×3; PASS |
| D13 | Efectos durables T1/T2/T3 | route.fetch y abort de respuesta | Aviso desconocido, consulta antes de retry | TrasT3 solo GET; trasT1/T2 replay explícito compatible; nunca duplicación | recovery `after_T1/after_T2/after_T3`×3; PASS |
| D14 | Paid sin documento, método histórico desactivado | Reabrir, reintentar solo emisión, imprimir y nueva venta | «El cobro se ha registrado»; emisión200 y success | Payment original1; documento1; stock1, identidad Billing conservada | `D-full-p01`, P01-browser×3 y carreras P01; PASS |
| D15 | Completed, sesión histórica cerrada, saldo positivo | Seleccionar destino vacío inicialmente, confirmar parte cash/card | Form P02 explícito, saldo real; success final200; preview de parte menor | Sale/documento/historia intactos, nuevo Payment solo en destino válido; cash físico solo allí | P02-browser12 variantes, `D-piece-change`; PASS |
| D16 | Resultado desconocido en journal | Recargar standalone / cerrar y reabrir | Bloqueo hasta GET; conserva claves; damaged journal cierra acceso seguro | GET no muta; replay compatible solo cuando procede | recovery reload/reopen/journal y P01 inactive; PASS |
| D17 | F1/F2 issued | Abrir imprimir dos veces | GET documento existente, popup correcto, llamada print | Estado antes/después idéntico; mismo documento/número | `D-full-*` y P02-browser; PASS |
| D18 | Popup listo para imprimir | Stub retorna sin imprimir y cerrar pestaña | TPV sigue en success | Ninguna mutación de Sale/Payments/caja/stock/documento/serie | Dos aperturas en `D-full-*`; PASS como simulación, sin diálogo/impresora física |
| D19 | Success, sesión normal o histórica cerrada | POST NUEVA VENTA | Navega a otra Sale abierta | Empieza vacía/importe0/sin pagos; claves diferentes tras añadir producto; P02 usa sesión válida nueva | `D-full-*`, P02-browser12; PASS |
| D20 | Touch simulado y varios tamaños | Tap cash, introducir20€, rotación por viewport, zoom CSS2 | Panel sin overflow horizontal; confirmación≥44px | Sin cobro en prueba responsive | `D-responsive-keyboard`:390×844,844×390,820×1180,1180×820,1440×900,820×1180 CSS200%; PASS |
| D21 | Modal y standalone | Escape/Enter, retorno de foco, errores422, P02 sesión, Enter confirmar | Foco útil, cierre seguro, resumen anunciado; HTTP según acción | Cerrar no cobra; confirmar una vez | `D-responsive-keyboard`, `D-errors-focus`, `D-piece-change`, `D-full-*`; PASS |
| D22 | Dos páginas del mismo contexto/Sale | Otra pestaña añade producto mientras primera conserva checkout viejo |409; revisar24,20€; confirmar después200 | Antes P0; después P1/D1, stock998, confirmado24,20€ | `D-two-browser-tabs` + carrito two_tabs; PASS |
| D23 | Cookie caducada e intención local pendiente | Leer cart-sync / acción HTMX / volver a login | Lectura devuelve login HTML por redirect, mensaje sesión/permisos; HTMX hace navegación completa al login | Intención y clave preservadas, sin pago nuevo; revalidación del mismo usuario probada | `D-expired-cart-read`, hardened expired_login, global UX expired_session; PASS |
| D24 | Usuario autorizado al GET | Revocar can_sell antes de POST |403 y aviso permiso, no error-page swap | P0/D0/S0/C0; carrera con otro autorizado conserva integridad | `D-permission`, C09×3; PASS |
| D25 | Caja cierra antes/entre transacciones | Cierre antesT1, trasT1, entre partes; recuperación explícita P02 |409/recuperación; elección nueva y confirmación necesarias | AntesT1 P0/S0; trasT1 P0/S1; entre partes P1/S1/C1. Historia intacta al recuperar | `closure-*`, P02-browser after_T1×3 y carreras destino; PASS |
| D26 | Mutaciones de carrito pendientes | Cantidad mientras POST retenido, varias operaciones, COBRAR | Loading sin formulario hasta drenar; luego versión/total confirmados; GET/POST200 | Caso nuevo cobra36,30€ para3 unidades, P1/D1/S1, stock997. No total provisional cobrable | `D-pending-quantities`, suites optimistic/hardening; PASS |

## Carrito: ampliación de variantes obligatorias

Se ejecutan `e2e.browser_optimistic_cart` y `e2e.browser_cart_hardening`:42 pruebas de desarrollo PASS; el test adicional de assets compilados falló inicialmente al buscar un bundle Chromium ausente y pasó por separado tras admitir el ejecutable instalado y compilar assets en un directorio temporal. Total43 pruebas de carrito validadas, sin presentar el primer lote como verde. Sus métodos heredados están explícitamente desactivados en la clase hardening para no duplicar descubrimiento; se informa el contador real del runner.

| Grupo | Pruebas / acción | Comprobación |
|---|---|---|
| Inicialización/flush | `checkout_waits_for_initial_protocol_read_before_draining`, `checkout_opens_shell_and_flushes_pending_before_enabling_payment`, `D-pending-quantities` | No formulario cobrable antes de confirmar pendientes; snapshot/versión autoritativos. |
| Cantidad y varias operaciones | quantity_during_sync_then_delete, twenty_quantity_steps, batch_provisional_quantity_delete, fifty_clicks | Orden/dependencias/UUID/recibos; persistencia coincide con intención; no pérdida de unidades. |
| Doble apertura/cierre | close_reopen_cancels_only_local_flush_wait, stale_checkout_read, `D-double-open-cycles`, `D-responsive-keyboard` | Cancelar espera local no revierte mutación; respuestas viejas y close tardío no rompen nueva apertura. |
| Timeout y red | header_timeout, header_network_abort, stuck_busy, actual_timeout_replays_original_operation_identity, lost_batch_response_reload | Espera acotada y revisión explícita; replay con identidad original, sin descartar flight. |
|409/422 | two_tabs_conflict, replayed_receipt_does_not_rebase, invalid_quantity, rejected_inactive_product, header_http_error | Conflicto requiere decisión; no rebase silencioso ni cobrar valores inválidos. |
| Navegación | abandon_warning, reload_unsent_intent, lost_batch_response_reload y `D-navigation-pending` | Aviso solo con cambios no verificados; navegación cancelada conserva cola, aceptada y vuelta reejecuta UUID original una vez. |
| Sesión y contexto | expired_login, namespace, incompatible_worker_or_identity | Pendientes de otro usuario/Business/Store/Sale no se importan ni se mandan a otro contexto. |
| Almacenamiento | quota_failure, corrupt_storage, partial_cleanup, invalid_flight_revision | Fallo seguro y explícito; no borrar datos que puedan representar resultados desconocidos. |
| Teclado/assets | keyboard_wedge, decimal_quantity_focus_scroll_tablet, collected_assets_initialize | Enter conserva unidades, foco/scroll; assets reales del producto arrancan. |

## Accesibilidad y revisión visual

Se inspeccionan capturas locales móvil y tablet de `/workspace/work/phase3-d`, no adjuntas como evidencia fiscal. En móvil el contenido tiene scroll vertical; el importe, método y efectivo se mantienen dentro del panel. Tablet presenta total, estado, cash y acción de confirmación sin desbordar. La captura móvil puede estar desplazada al campo efectivo por el foco, no representa un recorte de contenido inaccesible.

El test de contraste calcula ratios15,74:1 y18,26:1 sobre colores computados de total/confirmación y comprueba etiquetas de controles visibles; los valores están en `D-contrast-labels`. Es una muestra, no una certificación WCAG completa ni una prueba con lector de pantalla. El zoom probado es CSS al200%, no toda combinación de zoom nativo, pinch y dispositivo. Los contadores finales y cualquier fallo están en el informe; los intentos fallidos previos no se cuentan como pases.
