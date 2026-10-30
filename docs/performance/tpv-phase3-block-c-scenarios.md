# Fase 3, Bloque C — escenarios y evidencia

Pruebas sobre PostgreSQL 16 desechable, HTTP real contra LiveServer (sesión autenticada y CSRF válidos). Datos sintéticos; ninguna emisión/cobro real. C01–C10 se repiten tres veces. Las carreras parten con barrera común; no se afirma cobertura de todas las planificaciones posibles. Los puntos T1/T2 se inyectan de forma determinista. Evidencia completa en `tpv-phase3-block-c-evidence.json`.

Cada venta estándar tiene total 12,10 €, una línea física y stock inicial 1000. C04 usa stock inicial 1. “P/D/S/C” son Payments completed/documentos issued/StockMovements/CashMovements físicos por venta. Importes y numeración se consultan directamente en BD después de cada carrera; no se infieren del HTTP.

| ID | Precondición / operación / fallo | HTTP observado (repeticiones) | Persistencia final | P/D/S/C | Recuperación / resultado |
|---|---|---|---|---|---|
| C01 | Misma venta abierta; mismo payload y UUID. Dos POST HTTP concurrentes. Fallo: Ninguno | [200, 200] | completed/paid, pendiente 0.00, confirmado 12.10, números [1]; stock ['999.000'] | 1/1/1/1 | GET confirma resultado; no otro cobro. PASS ×3 |
| C02 | Misma venta; dos usuarios autorizados, UUID distintos. Dos POST HTTP concurrentes. Fallo: Ninguno | [200, 200] | completed/paid, pendiente 0.00, confirmado 12.10, números [1]; stock ['999.000'] | 1/1/1/1 | GET confirma resultado; segundo UUID no fuerza saldo nuevo. PASS ×3 |
| C03 | Misma venta; una versión obsoleta y otra actual. Dos POST HTTP concurrentes. Fallo: Validación cart_version | [409, 200] | completed/paid, pendiente 0.00, confirmado 12.10, números [1]; stock ['999.000'] | 1/1/1/1 | Obsoleto recibe conflicto; consultar versión sin inventar intención. PASS ×3 |
| C04 | Dos ventas, sesiones distintas; una unidad disponible. Dos POST HTTP concurrentes. Fallo: Stock insuficiente para perdedora | [422, 200] | open/unpaid, pendiente 12.10, confirmado 0, números []; completed/paid, pendiente 0.00, confirmado 12.10, números [1]; stock ['0.000'] | 0/0/0/0; 1/1/1/1 | Perdedora sigue abierta; corregir stock/venta antes de confirmar. PASS ×3 |
| C05 | Dos ventas/sesiones; misma serie fiscal. Dos POST HTTP concurrentes. Fallo: Contención BillingSeries | [200, 200] | completed/paid, pendiente 0.00, confirmado 12.10, números [1]; completed/paid, pendiente 0.00, confirmado 12.10, números [2]; stock ['998.000'] | 1/1/1/1; 1/1/1/1 | Documentos números 1 y 2; consulta histórica. PASS ×3 |
| C06 | Split cash/card, UUID por parte. Primera parte confirma; segunda falla422; dos replays del mismo split. Fallo: Interrupción controlada antes de segunda parte | [200, 200] | completed/paid, pendiente 0.00, confirmado 12.10, números [1]; stock ['999.000'] | 2/1/1/1 | Primera parte no se repite; resto y documento se confirman. PASS ×3 |
| C07 | Venta abierta con sesión válida. Cerrar sesión exactamente después de T1; POST y replay. Fallo: Entre T1 y T2 | [409, 409] | completed/unpaid, pendiente 12.10, confirmado 0, números []; stock ['999.000'] | 0/0/1/0 | 409 repetido; recuperación visible de sesión válida propuesta P02. PASS ×3 |
| C08 | Venta ya completada, pagada y emitida. Dos POST tardíos, uno con UUID nuevo. Fallo: Después de commits | [200, 200] | completed/paid, pendiente 0.00, confirmado 12.10, números [1]; stock ['999.000'] | 1/1/1/1 | Consultar; no se añaden efectos; no equivale a validar todos los payloads históricos. PASS ×3 |
| C09 | Usuario cashier autorizado al GET; permiso revocado antes de POST. Carrera con usuario aún autorizado. Fallo: Autorización actual | [200, 403] | completed/paid, pendiente 0.00, confirmado 12.10, números [1]; stock ['999.000'] | 1/1/1/1 | Desautorizado403; otro usuario autorizado completa. PASS ×3 |
| C10 | Venta propia abierta; Store/Business/método ajenos. POST contra otra Store, otro Business y método ajeno. Fallo: Aislamiento/autorización/formulario | [404, 403, 422] | open/unpaid, pendiente 12.10, confirmado 0, números []; stock ['1000.000'] | 0/0/0/0 | 404/403/422 sin efectos; usar recursos autorizados. PASS ×3 |

El orden ganador/perdedor puede variar. C06 registra además el HTTP422 inicial y Payment1 previo al replay en sus aserciones. C08 no interpreta éxito idempotente como aceptación de un pago incompatible: el checkout completo tiene retorno temprano tras comprobar versión. El rechazo de UUID/payload incompatible se verifica separadamente en el servicio correspondiente.

## Cierre de caja: seis posiciones

| Posición | Inyección / comprobación | HTTP observado | Sale/pago/pendiente | P/D/S/C | Stock y caja | Recuperación |
|---|---|---|---|---|---|---|
| before_T1 | Cerrar antes de POST; preflight rechaza sin T1 | 409 | open/unpaid/12.10 | 0/0/0/0 | ['1000.000']; cerrada, esperado 0.00 | No cobro retroactivo. Venta abierta: corregir contexto válido; completed: P02 pendiente. PASS |
| during_T1 | Retener decrease_stock con lock de sesión adquirido; closer bloqueado ≥100 ms; liberar y esperar ambos | 409 | completed/unpaid/12.10 | 0/0/1/0 | ['999.000']; cerrada, esperado 0.00 | No cobro retroactivo. Venta abierta: corregir contexto válido; completed: P02 pendiente. PASS |
| after_T1 | Cerrar al entrar en register_sale_payment, tras commit T1 | 409 | completed/unpaid/12.10 | 0/0/1/0 | ['999.000']; cerrada, esperado 0.00 | No cobro retroactivo. Venta abierta: corregir contexto válido; completed: P02 pendiente. PASS |
| between_split | Cerrar después de confirmar primera parte cash, antes de card | 409 | completed/partial/6.05 | 1/0/1/1 | ['999.000']; cerrada, esperado 6.05 | No cobro retroactivo. Venta abierta: corregir contexto válido; completed: P02 pendiente. PASS |
| cash_race | Barrera común POST cash/cierre, planificación libre | 409 | open/unpaid/12.10 | 0/0/0/0 | ['1000.000']; cerrada, esperado 0.00 | No cobro retroactivo. Venta abierta: corregir contexto válido; completed: P02 pendiente. PASS |
| card_race | Barrera común POST card/cierre, planificación libre; no CashMovement físico | 409 | open/unpaid/12.10 | 0/0/0/0 | ['1000.000']; cerrada, esperado 0.00 | No cobro retroactivo. Venta abierta: corregir contexto válido; completed: P02 pendiente. PASS |

Durante T1 el lock sí impide cerrar mientras esa transacción está abierta; **no protege el intervalo entre commits**. Cash/card pueden acabar 200 o409 según quién obtenga locks primero; la evidencia registra la planificación observada, no una garantía de que cierre siempre gane. El total esperado de caja se compara con suma de movimientos y el Payment correspondiente. Ninguna prueba escribe efectivo en una sesión cerrada.

## UUID e identidad

`CheckoutIdentityContractTests` prueba CartOperation mismo UUID/mismo payload (mismo recibo), distinto payload (conflicto), Payment mismo UUID/mismo importe (mismo registro), importe incompatible (rechazo), UUID nuevo con saldo cero (rechazo), Billing mismo UUID (mismo documento), UUID distinto sobre documento inicial existente (rechazo), misma clave/serie distinta (rechazo), serie histórica desactivada (servicio permite replay, formulario HTTP422), método desactivado (servicio rechaza), usuario sin acceso (Payments y Billing rechazan). C02/C03/C06/C09/C10 añaden UUID distintos, versión, split, permisos y aislamiento por HTTP. No se cambia ningún contrato.

## Navegador: resultado desconocido

Chromium real; escritorio1440, tablet820 y móvil390, altura900; touch activado en820/390. Cada fila se ejecuta en las tres anchuras, con Sale independiente. Antes de consultar, el envío queda bloqueado incluso vía requestSubmit; GET no produce POST y conserva UUID principal/Billing/partes. Después se verifica BD: saldo0, documento1 y StockMovement1. Paid y partial se diferencian de unpaid; éxito permite imprimir/nueva venta.

| Caso ×3 | Fallo / persistencia antes de consultar | Lectura y recuperación | POST totales | Resultado |
|---|---|---|---|---|
| after_T1 | T1 durable; T2 interrumpida; respuesta abortada después del servidor | GET unpaid; replay explícito misma intención | 2 | P1/D1/S1, PASS |
| after_T2 | T2 durable; Billing interrumpido; respuesta perdida | GET paid/documento pendiente; replay de emisión conservando payload | 2 | P1/D1/S1, PASS |
| after_T3 | Respuesta abortada tras documento emitido | GET muestra éxito; ningún replay | 1 | P1/D1/S1, PASS |
| render_500 | Excepción de render POST después de T3, HTTP500 real | Aviso desconocido, GET muestra éxito | 1 | P1/D1/S1, PASS |
| timeout | XHR timeout250ms mientras servidor sigue ejecutando antes de T3 | GET autoritativo; replay explícito misma identidad; servidor original se libera | 2 | P1/D1/S1, PASS |
| abort | XHR.abort a250ms mientras servidor sigue ejecutando | Igual recuperación; no equiparar abort con rechazo | 2 | P1/D1/S1, PASS |
| split_partial | Primera parte cash durable; card interrumpida; respuesta perdida | GET partial; replay de partes originales | 2 | P2/D1/S1/C1, PASS |
| reload | Tras T1 se carga checkout standalone por URL | Journal de pestaña conserva UUID; bloquear hasta GET; replay explícito | 2 | P1/D1/S1, PASS |
| reopen | Se cierra y reabre modal tras T2 | GET existente recupera intención original; replay explícito | 2 | P1/D1/S1, PASS |

Adicional: doble submit durante processing, Billing retenido y requestSubmit duplicado: un solo POST, Payment1/documento1/stock1. Los E2E anteriores de checkout cubren impresión, nueva venta, cobro simple/dividido y errores de validación; se adaptan los reintentos inciertos para exigir consulta. El GET de una operación ya finalizada no reconstruye el efectivo entregado/cambio, que no se persiste: se comprueban total y movimiento real, sin fabricar esos valores.

## H01 y presentación sin JavaScript

Test permanente: Payment1 confirmado, Billing falla, se desactiva método, POST original devuelve422. Ahora el error del campo oculto aparece en resumen accesible, junto con “cobro registrado” y enlace GET. Sigue Payment1/documento0; un flujo existente de emisión a partir de GET completa documento sin añadir pago. Esto **no corrige el contrato H01**: el replay original con método desactivado sigue bloqueado. Tests extra comprueban atributos autoritativos, errores UUID ocultos, pago simple sin validar formset split ausente y venta cancelled sin formulario de cobro.

## Límites de la evidencia

No se ejecuta SIGKILL real de worker/BD, partición física de red, navegador distinto de Chromium, terminal de pagos físico, emisor fiscal externo ni carga real de producción. Los fallos parciales se inyectan en fronteras concretas; la pérdida de respuesta usa abort de transporte después de route.fetch. La garantía sin JS sigue en backend y en tests de servicios/HTTP, no en sessionStorage. No se afirma que estas pruebas agoten todas las carreras.

## Recuperación por servicio existente, sin cambiar el flujo de checkout

`test_existing_service_recovers_only_pending_part_in_valid_session`: venta completed12,10 €, primera parte cash6,05 confirmada; cierre histórico; segunda intención rechazada sobre sesión cerrada. Se crea una sesión sintética válida de la misma tienda. Usuario sin permiso rechazado y replay del UUID histórico con sesión distinta rechazado. La intención pendiente conserva UUID y confirma6,05 una vez en la nueva sesión; replay devuelve mismo Payment. Resultado: paid/pendiente0, Payment2, documento0, stock1; un CashMovement6,05 en cada sesión, Sale.cash_session y Payment histórico intactos. PASS sobre PostgreSQL. Prueba capacidad y límites actuales del servicio; **no implementa la interfaz ni la política operativa P02**.

El test adicional de journal verifica consulta tras cerrar aviso en recarga standalone móvil, rechazo seguro de journal corrupto y memoria de respaldo con sessionStorage bloqueado. No crea efectos económicos; la solicitud abortada se detiene antes de llegar al servidor. PASS: un test Chromium adicional en3,950s, snapshots en informe/evidencia.
