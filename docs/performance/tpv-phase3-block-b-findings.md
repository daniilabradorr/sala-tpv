# Fase 3, Bloque B — matriz de causas y propuestas

Base `453e9c61de9c2a61b0c628c8e966b1c4983b03fc`, rama `fix/tpv-checkout-audit-phase3`. Cifras finales PostgreSQL/HTTP warm del JSON adjunto; n=7 salvo controles indicados. “Confirmado” no atribuye la demora original al mecanismo. No se implementó ninguna solución de negocio.

| ID | Severidad | Etapa | Evidencia | Latencia | Causa | Estado |
|---|---|---|---|---|---|---|
| B01 | MEDIO | Inventory/T1 | E02/E04/E06, span inventory y stock verificado | 17.86 / 269.16 / 645.33 ms, 1/20/50 líneas | Trabajo y validaciones por línea bajo lock | CONFIRMADO local |
| B02 / H03 | MEDIO | Billing/T3 | E02/E04/E06 + fiscal_model_costs | 54.27 / 139.41 / 288.58 ms | Snapshots, full_clean/guardado de hijos, serie y auditoría | CONFIRMADO local |
| B03 / H02 | MEDIO | Respuesta/recálculo | detail_stages, state/options; informe §8 | E06 state 28.82 y options 5.54 ms inclusivos | Relecturas y opciones repetidas; ahorro no aislado | CONFIRMADO coste; evitabilidad PROBABLE |
| B04 / H01 | ALTO | Recuperación Billing | boundaries.H01; phase3_cases.BoundaryCases | POST inactivo 22.23 ms, HTTP 422 | ModelChoice restringido a activos antes de emitir; error oculto en paid | CONFIRMADO reproducido PostgreSQL |
| B05 / H04 | ALTO | Validación fiscal tardía | F05/F06, preflight/issuer_snapshot/line_snapshots | Ver trazas por fallo; pago ya persistido | Fronteras independientes, fiscalidad validada tras T2 | CONFIRMADO comportamiento previsto |
| B06 | ALTO | Timeout frontend | frontend_boundaries.timeout | 299.87 ms hasta timeout inyectado | htmx:timeout no usa la rama sendError de feedback | CONFIRMADO: processing termina, falta aviso |
| B07 | ALTO | Caja entre T1/T2 | between_transactions | HTTP 409 repetido en checkout; ruta Payment alternativa comprobada | Sale completed usa sesión ya cerrada | CONFIRMADO, recuperación de servicios existente, UX pendiente |
| B08 | MEDIO | Locks | L01–L04, wait_event transactionid + pg_blocking_pids | 250 ms artificiales → execute bloqueado medido en informe | Contención sobre Sale/sesión/inventario/serie | CONFIRMADO local; no evidencia productiva |
| B09 | ALTO | Render tras T3 | F07 HTTP 500 con un documento y replay 200 | Ver boundaries.F07_after_T3_render | Error de respuesta no revierte commits | CONFIRMADO por inyección |
| B10 | MEDIO | Instrumentación | overhead ON/OFF, seis pares/tamaño | Delta en informe §4 | Recopilación añade trabajo; logger de HTTP no aislado | CONFIRMADO, límite de interpretación |
| B11 | — | Incidencia original ~20 s | Matriz warm sin episodio natural; pausa artificial aparte | Caso real null; control 20982.43 ms | No determinada | NO EVALUABLE en producción |
| B12 | CRÍTICO si apareciera | Duplicidad económica/fiscal | C01–C07, replays/fallos con invariantes | Sin duplicación observada en esos fixtures | Locks, saldo autoritativo e identidad | DESCARTADO EN EL ENTORNO PROBADO; no garantía global |
| B13 | — | Worker/WAN/pooler/Render | Config versionada + runtime local | null para despliegue | Requiere timestamps edge y proceso/BD efectivos | HIPÓTESIS / NO EVALUABLE |

## Reproducción, impacto y soluciones que requieren otro bloque

### B01–B03: volumen de trabajo

Reproducir matriz E02/E04/E06 y fiscal_model_costs. Impacto: crece tiempo en función de líneas; no se ha probado una sentencia normal de 20 s. La validación fiscal de líneas supone gran parte del guardado de hijos. Propuesta: perfilar equivalencia de validaciones y reuso de lecturas solo dentro de una frontera consistente. Requiere autorización de corrección para modificar Inventory, Billing, consultas del dominio o validaciones. No se autoriza bulk/omitir full_clean por este diagnóstico.

### B04/H01

POST pagado con Billing fallido, desactivar método, repetir cuerpo: 422 y error de método no visible. GET nuevo permite emisión sin recobrar. Impacto: recuperación bloqueada en el formulario ligado. Propuesta: distinguir intención ya confirmada de nuevo pago y mostrar errores. Requiere modificar view/form/template y añadir regresiones de replay/split/método inactivo en Bloque C; no cambiar compatibilidad del UUID ni permisos.

### B05/H04 y B07: estados parciales

Inyectar fallo de Billing o cierre justo entre T1/T2. Pago o stock pueden persistir sin el siguiente paso. Hay recuperación prevista; en caja cerrada se ensayó un pago en sesión nueva mediante el servicio ya existente y emisión posterior, sin duplicar efectos. Impacto: el cajero necesita saber qué está confirmado y qué paso falta. Propuesta: diseño explícito de recuperación y contexto de caja, validaciones informativas anticipables y revalidación fiscal dentro de Billing. Cambiar transacciones, reasignación de caja, numeración o semántica económica requiere autorización posterior.

### B06: timeout real

En navegador de prueba, xhr.timeout=250 y demora de servidor=800 ms antes de Billing. Se reciben afterRequest + timeout, sin sendError; processing se limpia, no aparece feedback desconocido. El servidor termina y el replay mantiene un pago/documento/stock. Impacto: resultado ambiguo sin aviso visible. Propuesta: manejar timeout/abort conservando identidad y recuperando estado. Requiere cambio frontend autorizado; no basta ampliar timeout y no debe reenviar cobros automáticamente.

### B08: contención

Retener una fila sintética, observar Lock y blocker, liberar tras 250 ms. También ejecutar carreras C01–C07. Impacto medido: espera de unos cientos de ms con bloqueo provocado; entre dos operaciones naturales se observaron waits, sin deadlock. Propuesta: medir pids/locks del intervalo lento real y alcance de joins select_related; no cambiar locks productivos sin pruebas de integridad y autorización.

### B09: render después del commit

Lanzar RuntimeError solo en _render después de emitir. Se recibe 500 con economía/documento confirmados; reintento no duplica. Impacto: error HTTP no identifica el estado económico. Propuesta: resultado desconocido más GET de estado y documento persistido. Requiere cambio de recuperación y tests HTTP de plantilla/transporte. No se sugiere borrar documentos ni revertir pagos como respuesta automática al 500.

### B10–B13: límites de atribución

ON/OFF alternado mide coste de capturar, no permite descontar una constante de cada span. La pausa artificial de 20 s enseña una espera después de T2 sin flush lento; no identifica el fallo del usuario. Faltan SHA/configuración/traza del caso lento real, cola edge→worker, WAN/pooler y cold start. Obtener evidencia requiere una captura controlada de staging; despliegue o acceso productivo no están autorizados en este bloque.

## Priorización para Bloque C

1. Recuperación pagada sin documento e H01; timeout/abort con resultado desconocido; contexto de caja entre commits.
2. Pruebas de pérdidas tras cada commit y error real de plantilla; conservar pagos/documentos/stock únicos y autorización actual.
3. Captura del caso lento en configuración representativa, con overhead controlado y sin datos sensibles.
4. Optimización demostrable de trabajo por línea y después relecturas, en cambios separados y con equivalencia económica/fiscal.

No se confirma pérdida económica ni cobro duplicado en lo ensayado. Beta: **evidencia insuficiente para decidir**, con defectos de recuperación/feedback identificados. Las soluciones anteriores son propuestas, no cambios realizados ni una autorización para implementarlas.
