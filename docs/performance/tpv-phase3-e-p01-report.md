# Fase 3 — Informe E-P01: EUR e integridad monetaria

Fecha: 30/10/2026. Rama `fix/tpv-checkout-audit-phase3`; HEAD base de validación `ad110fe46b777bf7522444ed72353fdba5177128`. Tras la autorización posterior del usuario, E y E-P01 se incorporan a un commit local en esta rama. No se realiza push, PR, merge ni despliegue.

## Restricción implementada

El backend admite únicamente EUR para nuevas configuraciones y escrituras económicas. Rechaza USD y otras monedas mediante formulario, servicio, validación de modelo y los puntos HTTP/Admin existentes. Lee la moneda persistida; una relación BusinessProfile en caché que todavía indique EUR no permite operar si la base de datos dice USD.

Los perfiles históricos no EUR conservan su valor exacto. Se bloquean nuevos efectos de venta, pago, caja, emisión, cuenta de cliente, compra y precios/costes monetarios. No se cambia configuración ni se convierten importes. El bloqueo de checkout sucede antes de llamar a T1; Sales lo aplica antes del descuento de stock. Los guards de modelo son una barrera adicional para escrituras normales directas.

La [implementación](tpv-phase3-e-p01-implementation.md) detalla todos los puntos encontrados y los archivos modificados. Se conserva la configuración EUR implícita de Businesses sin perfil; no se materializa un perfil ni se interpreta un perfil inválido como EUR. El alta normal crea un perfil fiscal válido EUR. Esta compatibilidad no acredita la moneda de importaciones ni de historia sin procedencia verificable.

## Invariantes comprobadas

- Bloquear una operación no crea Payments, documentos, movimientos, números ni auditoría económica parcial; las comparaciones incluyen stock, caja, saldo, documentos y contador de serie.
- No hay conversión, reasignación de Payments/sesiones, reapertura de caja, sobrepago ni regeneración de UUID confirmados.
- Las fórmulas, fiscalidad, redondeos, fingerprints, numeración, locks y fronteras T1/T2/T3 se conservan. No se añaden migraciones ni dependencias.
- Los permisos y el aislamiento entre negocios siguen vigentes. La impresión autorizada por un superusuario usa el negocio del documento para el aviso monetario.
- Lecturas, reimpresión y replay compatible de Billing mantienen las filas históricas. El replay Billing solo devuelve el documento existente; registrar Payment puede reparar deuda y por ello se bloquea en no EUR.
- Las consultas y el CSV histórico incorporan una advertencia sin cambiar cifras ni sustituir símbolos. El símbolo € no se presenta como prueba de la moneda histórica.

## Validación reproducible

Entorno: PostgreSQL 16.15 desechable, `postgres:16-alpine`, contenedor etiquetado `codex.task=tpv-phase3-e-p01`, puerto `127.0.0.1:55442`, base inicial `tpv_diag_phase3ep01` y base de test propia. Chromium del sistema, sin instalar dependencias. No se accede a producción ni a proveedores fiscales. Los runners de BD se ejecutan secuencialmente.

**Restricción implementada y validada en el alcance descrito.** Las recuperaciones históricas no EUR siguen bloqueadas y pendientes de autorización adicional.

| Lote | Resultado |
|---|---|
| Pruebas específicas de moneda | **15 métodos backend y 2 E2E nuevos validados**, incluidos en los runners finales siguientes |
| Crecimiento de consultas | 9 PASS; presupuesto anterior conservado para SQL ajeno a moneda, lecturas nuevas acotadas por separado |
| Pytest completo final | **1619 PASS, 533 subtests PASS**, 188,55 s; cuatro avisos de la deprecación Django60 ya conocida, repetida también por los formularios Admin nuevos |
| Regresión final y 13 sondas E | **1133 PASS**, 275,642 s; incluye las quince pruebas específicas, los módulos económicos/configuración y las trece sondas E de integridad/rendimiento |
| Chromium completo final | **37 PASS**, 345,276 s; F1/F2, impresión/PDF, errores y recuperaciones EUR, bloqueo no EUR y consulta histórica advertida |
| Comparación económica final con E | **38/38 escenarios y 54/54 registros EUR coinciden**, sin diferencias de importes, estados, pagos, caja, stock o numeración. Solo se excluyen HTTP/tiempos y se normaliza el orden de listas |
| Ruff / formato / Django checks / migraciones | **PASS**: Ruff sin incidencias; 474 archivos con formato válido; Django sin incidencias; `makemigrations --check --dry-run`: no hay cambios |

Los quince métodos específicos de backend cubren alta EUR, rechazo USD/GBP/JPY/eur, EUR→USD por formulario/servicio/modelo/POST/Admin, borrado y traslado del perfil, metadatos históricos, objeto en caché, venta nueva, Payment, CashMovement, nueva sesión/arqueo, F1/F2 pendientes, POST Billing directo, P01/P02 con UUID y sesión cerrada, lecturas/reimpresión, CSV, precios, cross-business, superusuario y carreras PostgreSQL de emisión y pago. La prueba de checkout previo a T1 comprueba además que no se llaman finalización ni descuento de stock.

Comandos, con `SECRET_KEY` sintético, `TPV_TEST_DATABASE_URL` apuntando exclusivamente a la base aislada y `TPV_DIAGNOSTICS=0`:

```sh
.venv/bin/python -m pytest --ds=config.settings.diagnostic_postgres -q
DJANGO_SETTINGS_MODULE=config.settings.diagnostic_postgres .venv/bin/python manage.py test apps.billing apps.sales apps.payments apps.cash_register apps.inventory apps.business_config apps.customers apps.purchases apps.reports tests.performance.phase3_billing_audit --noinput
DJANGO_SETTINGS_MODULE=config.settings.diagnostic_postgres TPV_CHROMIUM=/usr/bin/chromium .venv/bin/python manage.py test e2e.browser_billing_phase3_e e2e.browser_billing e2e.browser_checkout_authorized e2e.browser_checkout_recovery e2e.browser_checkout e2e.browser_htmx_global_ux e2e.browser_currency_policy --noinput
.venv/bin/ruff check .
.venv/bin/ruff format --check .
DJANGO_SETTINGS_MODULE=config.settings.diagnostic_postgres .venv/bin/python manage.py check
DJANGO_SETTINGS_MODULE=config.settings.diagnostic_postgres .venv/bin/python manage.py makemigrations --check --dry-run
```

Los logs y evidencia sintética se conservan en `/workspace/work/phase3-e-p01/`. Las suites se solapan; sus contadores no se suman como pruebas únicas. La sonda E02 pasa a verificar rechazo de configuración USD; su reproducción original y las mediciones del Bloque E siguen intactas.

### Iteraciones y coste de integridad

El primer pytest completo detectó **tres fallos nuevos de presupuestos SQL**, no los seis fallos antiguos: `test_header_autosave_does_not_load_cart_or_catalog`, `test_profiler_handles_a_full_django_query_buffer` y `test_quantity_queries_do_not_grow_with_whole_catalog`. Los guards y el aviso añaden SELECTs. Se conserva el techo anterior para el resto de consultas y se acotan por separado las lecturas de moneda (hasta tres en cabecera y cuatro en cantidad). El profiler espera doce consultas en lugar de once por el aviso. La estabilidad respecto al tamaño de catálogo sigue comprobándose. No se eliminan guards ni se presenta la sobrecarga como una optimización.

Una primera prueba de navegador usó por error el helper de checkout sobre una venta ya emitida y esperó un enlace de recuperación inexistente; también impidió limpiar una conexión de ese runner. Se corrigió la preparación de autenticación de la prueba de reimpresión y el cierre de conexiones. Los runs fallidos quedan en scratch y no cuentan como validaciones favorables. La repetición específica pasó los dieciséis métodos. La revisión final de Admin conservó expresamente el borrado EUR y bloqueó selecciones colectivas con perfiles no EUR; después se repitió pytest completo. Hubo asimismo ajustes de contratos del harness inicial (nombres de argumentos y estados HTTP), conservados en los logs.

### Los seis fallos anteriores de pytest

Estos fallos fueron preexistentes en D y **corregidos en los tests/fixtures del Bloque E**. E-P01 conserva exactamente esos tres archivos modificados; no deben describirse ahora como seis fallos activos aceptados.

| Caso anterior | Corrección E conservada |
|---|---|
| `ProductTaxResolutionTests.test_inactive_specific_tax_is_an_error` | Asignar impuesto válido y desactivarlo después; se conserva/refuerza rechazo de asignación inactiva |
| `ProductTaxResolutionTests.test_one_default_per_business_and_defaults_for_two_businesses` | Slugs independientes válidos para los dos negocios |
| `ProductTaxResolutionTests.test_other_business_default_is_never_used` | Fixtures de negocio/impuestos coherentes y aislamiento de fallback |
| `TaxFormTests.test_tax_update_form_exposes_is_active_but_not_business_or_is_default` | Expectativa obsoleta sustituida por `test_tax_update_form_excludes_lifecycle_and_tenant_fields`, acorde al contrato real |
| `CatalogMediaDeleteTests.test_protected_delete_keeps_media` | Import del helper de imagen en su ubicación real |
| `CatalogMediaDeleteTests.test_successful_product_delete_cleans_media_after_commit` | Mismo helper corregido, manteniendo la comprobación poscommit |

## Limitaciones históricas y recuperación pendiente de autorización

Los documentos, ventas y pagos no guardan una moneda histórica verificable. No se deduce de su símbolo ni se reconstruye a partir de un perfil mutable. Un perfil ya cambiado antes de esta restricción o una importación incompleta requieren evidencia externa y revisión.

Para un negocio actualmente no EUR:

- **P01:** venta completada y pagada sin documento: nueva emisión bloqueada; pago e identidad original conservados.
- **P02:** parte cobrada y parte pendiente con sesión cerrada: nuevo pago bloqueado incluso con otra sesión válida; ninguna parte confirmada se mueve o se repite.
- **Caja antigua abierta:** apertura, arqueos y cierre con nuevos importes están bloqueados; no se registra un cierre monetario para sortear la restricción.
- **Documento emitido:** consulta, reimpresión advertida y replay de Billing compatible disponibles; no se crea otro número.
- **Borrador inconsistente ya persistido:** se conserva el rechazo actual de su UUID; no se borra, renumera ni cambia de intención como reparación. Debe investigarse aparte, puesto que una T3 ordinaria es atómica.

La recuperación exige una propuesta individual con moneda acreditada, conciliación de importes, Payments/sesiones y UUID originales, y análisis fiscal. Conversión, relabel, backfill, rectificación, cambio de numeración/contabilidad o snapshots nuevos necesitan autorización adicional. No se ha implementado ni ejecutado ninguna transformación histórica.

## Riesgos restantes para beta y producción

La restricción implementa una barrera de aplicación para los escritores encontrados. No es un constraint de BD frente a SQL/bulk/roles privilegiados; el endurecimiento E-P02 sigue pendiente. Las validaciones nuevas tienen coste SQL explícito, sin benchmark productivo ni optimización autorizada de Billing/Inventory.

La beta con negocios reales EUR sigue condicionada a configuración fiscal válida, inventario autorizado del legado, conciliación/procedimiento de pendientes, alcance fiscal soportado y staging representativo. Multimoneda permanece bloqueada para nuevas operaciones. No se certifica validez fiscal de documentos ambiguos, integración fiscal externa ni impresión física. Producción no queda aprobada por estos tests.

## Estado de entrega y conservación

Git al cierre de la validación, antes del commit autorizado posteriormente: rama y HEAD iniciales conservados; **26 archivos modificados y 14 nuevos**, sin cambios staged ni archivos eliminados. De los doce archivos locales originales de E, diez permanecen byte a byte idénticos; solo se actualizan la sonda E02 (nueva expectativa autorizada) y la revisión global. Se conserva copia inicial con SHA-256 en scratch. La revisión de paths/diff y patrones comunes de secretos no encontró archivos ajenos ni secretos; no hay cambios de dependencias ni migraciones.

La comparación final se guarda en `economic-comparison-final.json`, con baseline versionable `tpv-phase3-block-e-measurements.json:financial_http_and_service_cases` y los 54 registros actuales en `financial-regression-preserved.json`. Los 44 registros de navegador y los seis de impresión se guardan por separado en `browser-recovery-final.json` y `browser-billing-final.json`. No se utiliza un fichero de navegador como evidencia de T3 ni se sobrescribe la evidencia E original.

Logs principales: `pytest-final-admin-eur.log` (pytest repetido tras el último ajuste de Admin), `regression-validated.log`, `browser-validated.log`, `ruff-final.log`, `format-final.log`, `check-final.log`, `migrations-final.log` y `cleanup.json`. Los runs intermedios permanecen identificados y no se cuentan como éxitos.

PostgreSQL retirado tras comprobar **cero otros clientes y cero bases de test**. Se verificaron identidad, etiqueta y `--rm` del contenedor propio; quedó parado y eliminado. No se tocaron contenedores o procesos ajenos. El usuario autorizó posteriormente el commit local de esta entrega. Push, PR, merge y despliegue siguen pendientes de autorización; no se ejecutan.
