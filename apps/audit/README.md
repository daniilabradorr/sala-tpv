# Audit

## Propósito y límites

`audit` conserva hechos de negocio append-only para investigación y trazabilidad.
No es logging HTTP ni una fuente de verdad basada en event sourcing. Los servicios
de dominio llaman explícitamente a `apps.audit.services.log_event()` después de la
mutación real, antes de retornar y dentro de su misma transacción; no se usan
signals, estado global de requests ni `transaction.on_commit()`.

Un fallo al registrar Audit debe revertir la mutación de dominio. Los replays
idempotentes retornan el resultado existente antes de Audit y no crean otro evento.

## Seguridad e investigación

- Los eventos no se pueden actualizar ni borrar mediante instancia, queryset,
  manager o admin. `bulk_create()` tampoco permite ignorar conflictos ni hacer
  upsert. `Business`, `Store` y `User` usan referencias protegidas; `user=None`
  identifica un evento de sistema.
- Toda lectura de aplicación usa `get_audit_events(business=...)` o
  `AuditEvent.objects.for_business(...)`. El admin es read-only, exige el permiso
  Django `audit.view_auditevent`, limita queryset y filtros al tenant, y solo el
  superusuario tiene visibilidad global.
- Cada payload se construye con una allowlist pequeña. El sanitizer recursivo
  redacta contraseñas, PIN, tokens, cookies, credenciales, claves y otros secretos.
  Conserva identificadores legítimos como `cash_session_id`, configuración no
  secreta como `require_pin_for_sensitive_actions` y hashes fiscales no secretos
  como `current_hash` y `previous_hash`.

## Política de duplicidad

Un hecho principal produce un evento principal. La única excepción deliberada es
el cierre de caja, que produce `CASH_COUNTED` y `CASH_SESSION_CLOSED` porque son dos
hechos distintos.

- Los movimientos de caja automáticos de pagos (`SALE_CASH` y `REFUND_CASH`) se
  representan solo con `PAYMENT_COMPLETED` o `PAYMENT_REFUNDED`; `CASH_IN`,
  `CASH_OUT` y `CASH_ADJUSTED` se reservan para movimientos manuales.
- Un `StockMovement` provocado por venta, devolución o recepción de compra no
  genera un segundo evento Inventory. Los eventos `STOCK_*` corresponden solo a
  operaciones explícitas del módulo Inventory.
- Billing registra un único evento high-level por operación: emisión, sustitución
  o rectificación. Un F3 companion de una rectificación no añade eventos de
  emisión ni sustitución.
- `BUSINESS_CONFIG_CHANGED` incluye solo nombres de campos modificados y valores
  operativos expresamente permitidos; nunca identidad fiscal privada completa.

## Contrato de eventos pre-VeriFactu

| Módulo | Eventos | Cantidad |
| --- | --- | ---: |
| `sales` | `SALE_COMPLETED`, `SALE_CANCELLED`, `SALE_RETURN_COMPLETED`, `SALE_RETURN_CANCELLED` | 4 |
| `payments` | `PAYMENT_COMPLETED`, `PAYMENT_REFUNDED`, `PAYMENT_CANCELLED`, `SALE_ON_ACCOUNT_REGISTERED` | 4 |
| `cash_register` | `CASH_SESSION_OPENED`, `CASH_IN`, `CASH_OUT`, `CASH_ADJUSTED`, `CASH_COUNTED`, `CASH_SESSION_CLOSED` | 6 |
| `inventory` | `STOCK_INITIALIZED`, `STOCK_ADJUSTED`, `STOCK_ADJUSTMENT_CANCELLED` | 3 |
| `purchases` | `PURCHASE_CREATED`, `PURCHASE_ORDERED`, `PURCHASE_RECEIVED`, `PURCHASE_CANCELLED` | 4 |
| `billing` | `BILLING_DOCUMENT_ISSUED`, `BILLING_DOCUMENT_SUBSTITUTED`, `BILLING_DOCUMENT_RECTIFIED` | 3 |
| `business_config` | `BUSINESS_CONFIG_CHANGED` | 1 |
| **Total** |  | **25** |

## Estado

**CERRADO PARA BACKEND PRE-VERIFACTU**

Dependencia diferida: cuando `integrations/verifacti` sea implementado, Audit
deberá reabrirse para incorporar los hechos fiscales externos de emisión/envío,
aceptación, rechazo, anulación, rectificación/subsanación y retry. Este contrato no
incluye todavía eventos `VERIFACTI_*`.
