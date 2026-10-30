# Fase 3, Bloque C — propuestas y autorización

Base de aplicación: `453e9c61de9c2a61b0c628c8e966b1c4983b03fc`; rama `fix/tpv-checkout-audit-phase3`. No se han cambiado servicios económicos, decisiones de checkout, límites transaccionales, locks, constraints, migraciones, fiscalidad o numeración.

## Decisión P01 — H01 funcional: emisión pendiente sin validar de nuevo un pago histórico

**Prioridad alta. Estado: PENDIENTE DE AUTORIZACIÓN.** La corrección de presentación y su test permanente sí están implementados; el rechazo HTTP 422 del método desactivado continúa intencionadamente.

Causa: `SaleCheckoutView.post` construye CheckoutForm con métodos activos y llama `is_valid()` antes de run_checkout (`apps/sales/views.py:1397`, `:1533`; `apps/sales/forms.py:39`). También puede rechazar una serie histórica desactivada antes de reconocer un resultado ya emitido. La UI no debe interpretar esto como falta del pago confirmado.

Archivos de una corrección futura: `apps/sales/views.py`, `apps/sales/forms.py`, tests de integración/HTTP/Chromium; revisar `apps/sales/checkout.py` solo si se necesita un conflicto explícito adicional, no para unir T1/T2/T3. Payments y Billing conservarían servicios y comprobaciones autoritativas.

Propuesta concreta, **no implementada**:

```text
POST checkout, con autenticación, CSRF, Business, Store y permiso actual:
    leer estado persistido (nunca confiar en mode/pending enviados por navegador)
    si completed + paid + pending == 0:
        si existe documento esperado emitido:
            presentar resultado persistido conforme a política de replay aprobada
        si falta documento:
            validar formulario específico de emisión:
                cart_version, serie compatible, billing UUID original
                payment UUID original solo para correlación de UI, si procede
            llamar orquestación existente con intents=[]
            en su lock Sale/T1 revalidar que no se ha abierto saldo nuevo
            si cambió estado: conflicto, sin registrar Payment
            Billing mantiene autorización, fingerprint, serie, numeración y atomic propio
    en otro estado:
        conservar validación completa de nuevas intenciones/partes y su contrato actual
```

Compatibilidad: aceptar el POST antiguo de pago simple/dividido cuando el servidor determine que solo falta documento, conservando claves originales; ningún flag del cliente decide qué operación económica se omite. Un GET no autoriza el POST posterior: hay que revalidar bajo el lock. Un cambio concurrente de saldo, devolución o estado debe fallar de forma segura. No se revalidaría como método nuevo una intención ya confirmada para emitir; **ese cambio de decisión es precisamente lo que necesita aprobación**.

La intención de Billing conserva su fingerprint (Business/Sale/tipo/serie). No se debe sustituir automáticamente una serie desactivada ni generar otra clave para esquivar incompatibilidades. Un documento ya emitido se consulta como histórico; definir expresamente la política de respuesta a un POST tardío incompatible.

Riesgos: saltarse validación de un pago aún pendiente por estado obsoleto; mezclar identidades de partes; alterar compatibilidad del POST; ocultar errores legítimos de Billing; confundir UUID principal con UUID de cada parte. Mitigaciones: estado autoritativo bajo lock, intents vacíos solo en ruta de emisión, autorización actual y pruebas negativas.

Migraciones: no previstas. No cambia impuestos, número, hash ni datos históricos.

Tests necesarios para autorizar implementación: H01 simple y split totalmente pagado, método desactivado, saldo concurrentemente reabierto, paid sin documento, documento emitido con serie desactivada, mismo UUID/payload distinto, dos billing UUID concurrentes, usuario desautorizado, otra Store/Business, cart_version obsoleta, pérdida de respuesta y emisión que confirma después del timeout. Deben verificar pagos/documentos/stock/saldos y no solo HTTP.

## Decisión P02 — R03: recuperar pagos pendientes con sesión cerrada

**Prioridad alta. Estado: PENDIENTE DE AUTORIZACIÓN.** No se ha modificado cierre, CashMovement, Payments ni coordinación transaccional.

Causa: T1 confirma stock/completed y libera el lock de sesión antes de cada T2. Una sesión asociada a Sale puede cerrarse; Payments valida la sesión y rechaza el pago. Entre partes de split puede persistir la primera parte y quedar el resto pendiente. Un método no físico sigue validando la sesión si se envía una asociada.

Archivos implicados: `apps/sales/checkout.py:230`, `:274`; `apps/payments/services.py:118`, `:285`; `apps/cash_register/services.py:619`; `apps/sales/services.py:612`; formularios/vistas de pagos y checkout. La vista de cambio de sesión de Sale exige editabilidad: no se debe eliminar esa garantía para editar una venta completed.

Propuesta preferida, **no implementada**:

1. Mostrar Sale completed/unpaid o partial, stock ya aplicado, pagos confirmados y sesión histórica cerrada.
2. Usuario con permiso actual de venta/recuperación en Store elige y confirma una sesión abierta válida. Definir si se requiere permiso adicional de manager; no inventarlo silenciosamente.
3. Utilizar el contrato existente de Payments para **la intención aún no confirmada** y el saldo actual, con UUID conservado y sesión válida. Ese servicio ya valida Business/Store/estado de sesión, saldo y autorización bajo locks.
4. Nunca volver a presentar una parte ya confirmada como nuevo pago en otra sesión: `_existing` compara también cash_session_id. Su efecto, UUID e identidad de caja son históricos y permanecen intactos.
5. No escribir CashMovement sobre sesión cerrada. La sesión nueva recibe exclusivamente el pago que realmente se confirma allí; la antigua conserva su cierre y arqueo.
6. Tras paid, emitir/recuperar documento por la ruta autorizada, sin completar Sale ni descontar stock de nuevo. Documentar la relación entre sesión histórica de Sale/documento y sesión del pago recuperado.

Pseudocódigo del flujo futuro:

```text
estado = lectura autorizada de Sale, pagos y documento
si completed y pending > 0:
    presentar pagos históricos y saldo, sin preselección silenciosa de otra caja
    usuario confirma sesión válida y partes aún no confirmadas
    Payments vuelve a bloquear Sale y sesión, valida saldo e identidad
    registrar solo los efectos pendientes (nunca recargar las partes confirmadas)
    releer; si paid y sin documento, ofrecer emisión
```

Compatibilidad: conserva frontera durable y servicios actuales; no modifica Sale.cash_session ni factura histórica por comodidad. B verificó recuperación con sesión nueva mediante API existente; C reproduce bloqueo, pagos parciales y recuperación de la parte pendiente mediante el servicio existente: rechaza mover el UUID histórico a la sesión nueva, conserva Sale/Payment históricos y deja un CashMovement en cada sesión. Falta diseñar y ensayar el flujo visible de cajero con sus permisos exactos. Mostrar un enlace genérico no basta para declarar esta recuperación resuelta.

Alternativas evaluadas:

| Alternativa | Ventaja | Límite / riesgo | Decisión |
|---|---|---|---|
| Revalidar antes de completar Sale | Error temprano cuando ya estaba cerrada | Ya se valida; no elimina la ventana entre commits | Mantener, no presentarlo como solución completa |
| Recuperación explícita en sesión válida | Conserva commits e historia; permite intervención consciente | Exige permisos, saldo actual e identidad por parte; contexto documental debe explicarse | Preferida para diseñar |
| Bloquear cierre mientras haya checkout en vuelo | Evitaría algunos estados parciales | No existe una reserva durable de intento; timeout no acredita fin; podría bloquear cajas indefinidamente | No implementar sin otro diseño autorizado |
| Unir T1/T2/T3 o mantener sesión bloqueada entre commits | Aparente atomicidad global | Cambia arquitectura, locks y fallos durables; aumenta contención | No autorizado; no propuesto como atajo |
| Registrar efectivo retroactivamente en sesión cerrada | Ninguna garantía segura | Rompe arqueo/historia | Rechazado |

Migraciones: no necesarias para una primera propuesta basada en servicios existentes; una reserva durable de intento sí podría exigir esquema y autorización nueva. No se ha creado ninguna.

Tests requeridos: seis cierres de C (antes/durante/después de T1, entre partes y cash/card), selección de sesión ajena/cerrada/inactiva, permiso perdido, replay de parte histórica con sesión distinta rechazado, parte pendiente en sesión nueva confirmada una vez, cash físico separado de card, cierre concurrente de la sesión destino y recuperación de Billing posterior.

## Decisiones P03/P04 — optimización y validación fiscal previa

**Estado: fuera de las correcciones autorizadas de C.** H02/H03 continúan como trabajo de rendimiento medido, no corregido. H04 es un estado parcial previsto, no un fallo de rollback global.

P03: diseñar por separado reuso de lecturas y coste por línea manteniendo save/full_clean, snapshots, señales, auditoría y locks. Requiere evidencia de equivalencia y pruebas antes de tocar Inventory/Billing. No se autoriza bulk por reducir contador de SQL.

P04: evaluar comprobaciones informativas de perfil/serie/cliente antes del pago; revalidaciones de estado mutable y fiscalidad deben permanecer dentro de emisión. Ningún preflight elimina fallos de BD/red después de T2. Cambiar orquestación requiere aprobación y pruebas de carreras; no se propone una transacción global.

## Contratos observados que no deben confundirse

- CartOperation: UUID por Sale y fingerprint de intención; el replay antiguo puede devolver recibo aunque avance cart_version. UUID de carrito no es UUID de pago.
- Payment: UUID único por Business; compatibilidad de Sale, método, tipo, importe, devolución y sesión. External_reference no es toda la identidad comparada. Método y autorización actuales se validan antes del replay.
- Billing: UUID/fingerprint de intención; replay autorizado de documento histórico puede funcionar con serie desactivada. La vista checkout puede rechazar el mismo POST por su formulario antes de llegar al servicio.
- Checkout ya completo: run_checkout devuelve estado después de comprobar versión, sin volver a consumir todas las intenciones. Un POST tardío de formulario válido no necesariamente valida cada payload histórico incompatible; no se ha demostrado duplicación por ello. Endurecer esa política también sería cambio de contrato, no una corrección visual.

## Qué aprobación se necesita

1. **P01:** autorizar la ruta funcional de emisión determinada por estado económico autoritativo, sin validar método histórico como pago nuevo y sin generar otro Payment.
2. **P02:** autorizar el diseño e implementación de recuperación explícita de partes pendientes en una sesión válida, con política de permisos y contexto histórico de caja definidos.
3. **P03/P04:** autorizaciones separadas si se decide abordar optimizaciones de dominio o anticipar validaciones; no son condición para cerrar las correcciones visuales de C.

La fuente de esta separación es el propio encargo C.2: “No modifiques todavía la validación que decide si se ejecuta un pago o una emisión si ello cambia el contrato de checkout”, y C.4: “Modificar cierre de caja, Payments, CashMovement o transacciones requiere autorización posterior”. Ninguna de estas propuestas ha sido aplicada.
