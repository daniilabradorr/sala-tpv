# P02 — recuperación explícita del pago pendiente con sesión cerrada

Autorización posterior al Bloque C,28/10/2026. Misma rama/base que P01. No se cambia la sesión de una Sale completed, no se reabre caja ni se modifican pagos o movimientos históricos. El flujo está implementado y validado dentro del alcance autorizado; cierre29/10/2026.

## Condiciones, permisos y alcance

El servidor ofrece recuperación solo si Sale está completed, su sesión histórica está closed con closed_at, y el saldo obtenido de Payments persistidos es positivo. No se confía en Sale.pending_amount almacenado si difiere del balance; no se altera el campo desde la vista. El servicio de Payments recalcula y persiste el estado económico al confirmar.

Se mantienen los permisos actuales de venta en Store: can_sell_in_store, usuario activo, Business/Store y validaciones del servicio de Payments. No se crea una elevación a manager ni un permiso nuevo: las reglas existentes permiten al vendedor autorizado registrar un pago en una sesión operativa de la misma tienda, aunque la haya abierto otro usuario. No se asume permiso de abrir/cerrar cajas.

Acceso visible: enlace «Recuperar checkout» en detalle de venta completed con saldo o documento pendiente; GET existente de checkout. También se ofrece al quedar la venta parcial tras cerrar caja entre etapas. El formulario muestra cobros confirmados y saldo, pide sesión destino válida, método, importe y confirmación explícita de no repetir cobros anteriores. No preselecciona otra caja. Puede confirmar una parte menor al saldo; después genera una intención nueva para la siguiente parte. Los campos y la confirmación también se validan sin JS.

## Identidad de las partes

- Cada Payment confirmado conserva UUID, método, importe, Sale, sesión, CashMovement y usuario originales. No se reenvía como intención a otra sesión. El servicio existente rechaza una clave confirmada con sesión/importe/método incompatibles.
- Una única parte no confirmada conocida conserva su UUID al pasar del POST antiguo a recuperación, incluido el split con una parte histórica confirmada. El journal de pestaña hace lo mismo tras una lectura autorizada. Un UUID no confirmado aún no tiene registro económico durable; la elección explícita de sesión es parte de su primera confirmación efectiva.
- Si no se conoce una única intención pendiente (GET fresco, varias partes no confirmadas), el formulario crea un UUID nuevo para **una confirmación explícita de saldo restante**. No se reutiliza el UUID de correlación principal de un split como si fuese una parte ya existente.
- El POST de recuperación conserva UUID/importe/destino al perder una respuesta. Tras GET, si esa clave ya figura en Payments, no se vuelve a cargar como pendiente: se muestra la confirmación y una nueva intención para el saldo que reste. No hay POST automático.
- La confirmación de una parte devuelve `X-Netxodo-Confirmed-Payment`; no equivale a declarar finalizado todo el checkout. El journal se limpia por esa identidad. La identidad de Billing se conserva separadamente, incluso al cerrar/reabrir tras un fallo conocido de emisión.

El importe se limita al saldo persistido bajo lock y se vuelve a validar por Payments. UUID nuevo no permite sobrepago. Ni amount, ni modo, ni checkbox pueden autorizar por sí solos a omitir estas comprobaciones.

## Transacciones y trazabilidad

`recover_pending_checkout_payment` en `apps/sales/checkout.py` es **una T2**, con lock Sale y guards de estado/versión/permisos/historia de caja. Invoca el servicio existente `register_sale_payment`; su atomic anidado pertenece a esa misma transacción de un solo pago. Mantiene orden Sale→CashSession destino y delega allí compatibilidad, saldo, método y sesión abierta. No engloba T1/Inventory ni T3/Billing. Un fallo revierte esta T2; las partes anteriores permanecen.

La nueva sesión recibe solo el Payment pendiente y, si es efectivo físico, su CashMovement. El método no efectivo conserva asociación a sesión sin generar movimiento físico. La nota del Payment identifica recuperación y sesiones histórica/destino, además de la auditoría existente de Payments. Sale.cash_register/cash_session y los datos históricos del documento se conservan; Billing sigue usando el contexto original de Sale y sus series válidas, sin sustituirlas por las de la caja destino.

Tras confirmar T2 se relee Sale. Si ya está pagada y falta el documento, se usa P01 y el Billing UUID original en una etapa posterior. Si Billing falla, no se revierte ni repite el nuevo Payment: queda «pagado/documento pendiente». Si el documento ya existía, no se reemite. No se introducen migraciones, nuevas dependencias, infraestructura de producto, reservas de checkout, reglas contables/fiscales ni cambios de numeración.

## Archivos

- `apps/sales/checkout.py`: elegibilidad, saldo de lectura y T2 controlada.
- `apps/sales/forms.py`: formulario de parte pendiente y confirmación explícita.
- `apps/sales/views.py`: selección autoritativa de ruta, conservación de una parte pendiente, lectura posterior y emisión separada.
- `templates/sales/partials/_checkout.html`, nuevo `_checkout_pending_payment.html`, `templates/sales/sale_detail.html`: estado, formulario y acceso visible.
- `static/js/core/checkout-recovery.js`: identidad de recuperación y tratamiento de partes confirmadas después de respuesta perdida.
- Nuevos tests `test_pending_checkout_authorized.py`, `tests_postgres_authorized.py`, `browser_checkout_authorized.py`. Se actualizan solo las expectativas C del nuevo contrato autorizado (H01, serie histórica y repetición sin confirmación de recuperación); se conserva su cobertura económica y su snapshot anterior.

## Pruebas y riesgos restantes

Antes de regresión final:20 tests de integración P01/P02 PASS (8,761s),7 métodos PostgreSQL concurrentes PASS (34,744s), incluyendo C01–C10×3, seis posiciones de cierre C, seis carreras de P01, seis carreras P02 con misma/distinta clave y cuatro cierres de sesión destino cash/card antes/durante T2. Las comprobaciones consultan BD, no solo HTTP. Se añade después un test de transición split que conserva el UUID de la única parte pendiente.

Desarrollo Chromium:15 ejecuciones autorizadas PASS (2 métodos,54,201s): P01 en1440/820/390 y P02 cash/card, respuesta perdida tras parte confirmada y cierre exacto tras T1 en cada tamaño, con touch en tablet/móvil. Validación final conjunta:751 pruebas de regresión financiera y26 E2E PASS; suplemento14 tests PASS que comprueba impresión y apertura real de la siguiente venta en los12 casos P02. Pytest1596 PASS y los mismos seis fallos preexistentes reproducidos sobre HEAD;38/38 snapshots económicos C idénticos. Comandos, tiempos y evidencia en `tpv-phase3-p01-p02-report.md` y su JSON.

El flujo requiere intervención consciente y una sesión válida; no fuerza reapertura ni selección silenciosa si no hay ninguna. Si la sesión destino cierra antes de confirmar, el pago nuevo se rechaza; si Payments la tenía bloqueada, el cierre espera esa T2. Si método/permiso cambia después de una respuesta perdida, un replay puede ser rechazado y se debe consultar de nuevo. La memoria de respaldo del journal no sobrevive una recarga con sessionStorage bloqueado. No hay prueba sobre producción, adquirentes, dispositivos físicos, todos los navegadores o todas las interrupciones de proceso. Estas limitaciones no se presentan como corregidas.

Identidad terminal y siguiente venta: una clave ya persistida en pending/cancelled se rechaza con409 sin emitir `X-Netxodo-Confirmed-Payment` ni mutar ese registro. Tras recuperar, «Nueva venta» utiliza el inicio global existente si la sesión histórica no es operativa; se comprueba la creación de una nueva Sale en la sesión válida y la conservación de la anterior. No se modifica SaleOpenView ni se reasigna la venta completada.
