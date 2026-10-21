# Fase 2B: propuesta pendiente de autorización

Documento histórico del diseño previo a la autorización. El estado actual se
documenta en `tpv-optimistic-cart-report.md`.

Estado en el momento de esta propuesta: interfaz sin implementar. Rama
`feat/tpv-optimistic-cart`, basada en `perf/tpv-inventory` (`61fa856`).
No se han modificado reglas de negocio, servicios, modelos ni migraciones.

## Motivo de la pausa

La solicitud exige detenerse si es necesario modificar contratos del backend
y prohíbe migraciones sin autorización explícita. Los contratos actuales de
Sales no permiten garantizar reintentos sin duplicados y detección de cambios
desde otra pestaña. La idempotencia existente de pago/documento no cubre las
mutaciones del carrito.

Evidencia en `apps/sales/services.py` y `apps/sales/views.py`:

- `add_sale_line` crea una línea por petición aceptada; no registra una identidad
  de operación para reconocer una repetición tras perderse la respuesta.
- `update_sale_line` guarda cantidades absolutas bajo bloqueo, sin exigir una
  revisión esperada. El bloqueo serializa escrituras, pero no detecta una
  intención basada en un estado antiguo.
- La validación del checkout no entrega un contrato de revisión del carrito
  que el POST de confirmación deba comprobar bajo el mismo bloqueo de venta.
- `cartRevision` en JavaScript protege la presentación frente a respuestas
  antiguas; no constituye una precondición validada por el servidor.

## Comprobación reproducida

Prueba local con Django Client, Dataset sintético y SQLite en memoria. No se
ejecutaron pagos ni emisiones. Evidencia local sin versionar:
`work/tpv-optimistic-cart/contract-probe.json`.

| Caso | Resultado actual |
| --- | --- |
| Dos POST de añadir, mismo `operation_id` propuesto | HTTP 200 ambos; dos líneas, cantidad total 2 |
| Cantidades absolutas 2, 3 y repetición antigua de 2 | HTTP 200 todos; cantidad final 2 |

Los campos propuestos `operation_id` y `expected_revision` son ignorados por
los endpoints actuales. El segundo caso simula una repetición antigua; no es
una prueba de concurrencia PostgreSQL. Estos resultados prueban la ausencia
de las precondiciones, no un fallo introducido por esta fase. La separación
entre validación y confirmación del checkout se ha inspeccionado estáticamente;
no se ha reproducido un cobro con un importe cambiado.

## Contrato mínimo propuesto, limitado a Sales

1. Revisión persistente del carrito y recibos persistentes de mutación. Una
   migración añadiría la revisión a Sale y un registro de operación con identidad
   única por venta, huella del contenido aceptado y revisión resultante.
2. Cada mutación enviaría UUID estable y revisión esperada. Dentro de la
   transacción y el bloqueo existente de Sale, comprobar primero si ya fue
   aceptada, rechazar reutilización del UUID con contenido distinto, comprobar
   revisión, aplicar los servicios de negocio y persistir el recibo/revisión
   atómicamente. Nunca registrar datos de pago en esos recibos.
3. Una repetición aceptada devolvería su recibo y una instantánea autoritativa
   actual. Un conflicto de revisión devolvería HTTP 409 y estado suficiente
   para reconciliar. Mantener el ámbito Business/Store/Sale en cada acceso.
4. Todas las vías que alteren el carrito o sus importes deben participar en el
   protocolo de revisión. Conservar las rutas HTML existentes y sus validaciones,
   evitando que escrituras antiguas eludan la revisión para clientes optimistas.
5. La validación del checkout devolvería revisión e importes definitivos. La
   confirmación comprobaría la misma revisión bajo el bloqueo de Sale, antes
   de invocar los servicios existentes de cobro y emisión. Si cambia, exigiría
   revisar y confirmar de nuevo. No cambiar contratos internos de Payments,
   Billing, Inventory ni reglas fiscales.

La retención y limpieza de recibos necesita una política definida: no eliminar
un recibo mientras el cliente todavía pueda reintentar su operación. Una cola
exclusivamente en memoria, un GET de reconciliación o un bloqueo entre pestañas
no permiten determinar por sí solos si una petición sin respuesta se confirmó.

## Interfaz prevista después de autorizar el contrato

- Estado confirmado más cola persistente de intenciones por Business/Store/Sale;
  estado visual derivado al aplicar las pendientes. Una petición en vuelo por
  venta y UUID conservado ante timeout o recarga.
- Añadir, quitar y cambiar cantidades modificarían el DOM inmediatamente.
  Agrupar únicamente intenciones todavía no enviadas cuando conserve su
  significado; nunca alterar una operación enviada ni asumir que abortarla
  revierte su efecto.
- Diferenciar pendientes, errores recuperables y conflictos. Reconciliar con
  el estado autoritativo y no repetir a ciegas cantidades absolutas antiguas.
- Reutilizar nodos y actualizar líneas/totales de forma granular, conservando
  foco y scroll. Importes locales siempre provisionales, sin motor fiscal JS.
- No fusionar silenciosamente líneas del mismo producto con precios,
  descuentos o snapshots fiscales distintos. La agrupación visual debe
  preservar sus identidades y el backend debe validar cualquier consolidación.
- Abrir inmediatamente la carcasa del checkout, congelar nuevas ediciones,
  vaciar la cola y validar la revisión. Habilitar confirmar solo con estado
  sincronizado y total definitivo revisado.

## Validación necesaria tras la autorización

Cubrir las ráfagas de 20 clics, cantidades durante sincronización, añadir/quitar,
respuestas antiguas, latencia, desconexión, respuesta perdida, reintento y recarga.
Comprobar productos desactivados, rechazos de stock según reglas existentes,
cambio de Business/Store, dos pestañas y checkout con pendientes. Verificar
persistencia final y pruebas transaccionales con PostgreSQL para recibos,
revisiones, rollback y carrera entre edición y confirmación.

Medir por separado interacción→primer cambio visual (objetivo <50 ms),
confirmación remota y checkout; mismos datos y condiciones antes/después.
Todavía no hay resultados de rendimiento visual ni tests de una implementación
2B. No se declara completada la fase ni se sube una implementación parcial.

La autorización de push ya está concedida por el mensaje más reciente del
usuario. Se usará para subir la rama implementada y validada, sin merge ni
despliegue, después de resolver esta ampliación de alcance.
