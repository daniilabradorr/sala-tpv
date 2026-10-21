# Fase 2C — carrito optimista: auditoría y endurecimiento

Base: `a356003`. Rama de trabajo `hardening/tpv-phase2c`; el usuario autoriza
publicar por avance directo en `feat/tpv-optimistic-cart`. Sin merge, despliegue,
cobros reales ni envíos fiscales. No cambian modelos, migraciones, Inventory,
Payments, Billing ni reglas económicas. El plan previo está en
[tpv-phase2c-plan.md](tpv-phase2c-plan.md).

## Hallazgos y soluciones

| Limitación inicial | Tratamiento | Estado |
| --- | --- | --- |
| Una petición por añadido durante una ráfaga | Lote opcional atómico, hasta 50 operaciones, sin fusionar líneas ni recibos | CORREGIDO |
| El diario sobrevive a reload, pero no garantiza cierre definitivo | Se mantiene sessionStorage por identidad/pestaña, advertencia al salir, bloqueo ante corrupción y recuperación con recibos | MITIGADO; cierre definitivo sin durabilidad garantizada |
| Recibos durante toda la vida de Sale | Métricas agregadas de solo lectura y plan de capacidad; sin TTL/borrados | MITIGADO |
| Workers y clientes de versiones distintas | Protocolo verificable, guard de identidad, assets con hash y procedimiento de drenaje | MITIGADO; infraestructura real no inspeccionada |
| Polling sin plazo y continuaciones de modales antiguos | Promises/eventos, plazo, GET y envío acotados, invalidación por cierre y bloqueo ante cabecera desconocida | CORREGIDO |

## Transporte atómico, idempotencia y versiones

La URL existente `/sales/stores/{store}/sales/{sale}/cart-sync/` mantiene el POST
individual anterior y admite un segundo formato:

```json
{
  "version": 12,
  "operations": [
    {"key": "UUID-A", "kind": "add", "product": 7, "quantity": "1.000"},
    {"key": "UUID-B", "kind": "quantity", "line_ref": "UUID-A", "quantity": "2.125"}
  ]
}
```

`UUID-A/B` representan UUID reales. `line_ref` resuelve el añadido anterior por
su recibo dentro de la misma Sale, o una operación anterior del mismo lote.
No se aceptan referencias a otra Sale ni referencias futuras sin confirmar.
`line` y `line_ref` son excluyentes. Hay entre 1 y 50 operaciones y claves únicas.
Se conservan orden, servicios, validaciones, save(), señales y snapshots por
operación. No hay bulk_create/update de dominio ni agrupación fiscal.

El servidor bloquea Sale una vez para el transporte y llama al mismo núcleo de
mutación; los servicios conservan sus propios bloqueos/transacciones. La revisión
inicial se comprueba bajo ese lock y cada mutación efectiva avanza la versión
original. Un no-op mantiene su versión y recibe recibo. Todos los nuevos efectos
y recibos se confirman juntos: cualquier excepción revierte el lote entero.
No existe confirmación parcial de un lote nuevo.

Los recibos se precargan bajo el lock. Si todos existen, se comprueba el fingerprint
de cada intención y se devuelve el estado actual sin repetir efectos. Si solo
existe parte, se rechaza con 409/code=key; no se añade silenciosamente un sufijo.
Un subconjunto formado exclusivamente por recibos existentes puede reproducirse.
El `version` original no forma parte del fingerprint económico, como antes.

HTTP 200 devuelve `{cart, results:[{key,line,replayed,accepted_version}],
accepted_version}`. 409 conserva code=version|key|line, 422 indica rechazo/entrada
inválida. Snapshot final único por lote, en lugar de uno por cada operación;
las consultas de recibos se reutilizan. Los servicios comerciales por línea
siguen ejecutándose: se reduce sobre todo el número de viajes HTTP y lecturas
redundantes del protocolo, no se promete un coste SQL constante.

El diario `flight` es una escritura atómica de la petición preparada antes de
transmitir. Congela sus operaciones y UUID hasta resolverla; no se consolidan
cantidades que ya pertenezcan al vuelo. Las cantidades consecutivas aún no
enviadas mantienen la consolidación previa, y los añadidos siguen separados.
Se guardan los mapas de líneas antes de retirar operaciones. Si la limpieza local
se interrumpe después del commit, `flight` reconstruye la petición completa y la
reproduce por los mismos recibos. No se interpreta timeout como rollback.

## Protocolo y cuenta activa

GET añade `protocol:2` y `user_id`; las respuestas del endpoint incluyen
`X-Sales-Cart-Protocol: 2` y siguen usando `Cache-Control: no-store`.
El frontend nuevo valida usuario, Business, Store y Sale de la instantánea antes
de iniciar recuperación. Un POST nuevo incluye `X-Sales-Cart-User`; el servidor
rechaza un usuario diferente antes de mutar. Los clientes anteriores pueden
seguir usando el POST individual; sus escrituras atraviesan los servicios que
avanzan revisiones. Una respuesta incompatible no constituye prueba de rechazo
ni permite descartar automáticamente una operación de resultado desconocido.

Esto no transforma un backend antiguo en compatible ni impide que sus procesos
antiguos escriban fuera de este protocolo. Es obligatorio retirarlos/drenarlos.
Los formularios HTMX anteriores se mantienen; una página de checkout sin revisión
sigue recibiendo 409. Los escritores SQL y tareas externas deben inventariarse.

## Esperas, errores y UX

- La red de carrito y lecturas tiene timeout de 15 s. Un flush tiene presupuesto
  de 20 s; puede fallar de forma recuperable antes de terminar una cola muy larga.
- `flush` espera notificaciones de cambios de estado, con temporizador de límite
  y limpieza de listeners, en lugar de polling cada 20 ms.
- Cerrar el modal cancela su espera y sus GET. No cancela/reinterpreta la mutación
  comercial ya enviada. Reabrir crea una nueva tentativa; la antigua no puede
  insertar HTML ni cambiar el estado de la nueva.
- Cada petición de cabecera tiene su temporizador y finalización única. Un evento
  HTMX ausente no deja el contador activo indefinidamente. Un resultado fallido o
  desconocido bloquea checkout y pide recargar/revisar la cabecera. Una respuesta
  tardía válida puede reconciliar su transición, sin descontar dos veces el contador.
- Estado explícito: pending/syncing/saved/offline/conflict/intervention mediante
  `data-state` y mensajes accesibles. «Guardado» solo tras confirmación y sin
  peticiones de cabecera/operaciones activas. Sin conexión se ofrece reintento
  explícito; no se rebasan intenciones silenciosamente al reconectar.
- `beforeunload` advierte si hay operaciones, cabeceras o resultados sin verificar.
  El navegador decide si muestra el diálogo, exige interacción previa y puede
  omitirlo en cierres abruptos/móviles: no es una garantía de durabilidad.
- Corrupción o indisponibilidad del diario inicial bloquea edición/cobro, conserva
  los datos y pide revisión; no activa un fallback que pueda repetir intenciones.
  Una cuota agotada antes de aceptar un clic no añade una intención visual falsa.

## Persistencia local y cierre de pestaña

| Alternativa | Durabilidad/cierre | Aislamiento y coordinación | Coste/riesgo |
| --- | --- | --- | --- |
| sessionStorage, conservado | Reload; cierre definitivo no garantizado | Pestaña + User/Business/Store/Sale; sin consumidor compartido | Sin nuevos servicios; datos locales expuestos al mismo origen |
| localStorage | Persiste al cerrar, según navegador | Compartido; necesita propiedad/lease y reconciliación multi-tab | Sin transacciones de varias claves; cuotas, cuenta compartida |
| IndexedDB | Mejor transacción de diario, cierre recuperable habitualmente | Requiere gestión de identidad, ownership y exclusión de consumidores | Más complejidad; almacenamiento borrable/no seguro; no garantiza durabilidad absoluta |

Se mantiene sessionStorage para evitar introducir una cola compartida duradera en
terminales de varios usuarios sin diseñar su ciclo completo. No guarda pagos,
credenciales, tokens ni clientes: UUID y metadatos del carrito/productos. El diario
solo se importa en su namespace y tras revalidar la cuenta/ámbito. Logout/cambio de
cuenta con pendientes requiere resolver/revisar antes de salir; no se eliminan
operaciones desconocidas para «limpiar». Otro usuario no recupera esa cola desde
la aplicación. El almacenamiento del mismo origen no ofrece aislamiento
criptográfico frente a DevTools, scripts comprometidos o acceso físico.

Abrir una pestaña independiente tras un cierre NO reconstruye intenciones que
solo existían en la pestaña cerrada. El test registra ese límite, no lo presenta
como recuperación. Reabrir la venta sí recupera sus líneas confirmadas desde SQL.

**Propuesta pendiente:** si el producto exige recuperar intenciones no confirmadas
tras cierre definitivo, diseñar y aprobar el ciclo de IndexedDB: ownership por
cola, exclusión multi-tab (Web Locks con soporte/fallback definidos), pantalla de
recuperación explícita autenticada, verificación de recibos antes de reintentar,
caducidad solo para borradores nunca enviados, cuarentena de desconocidos y
procedimiento de cuenta compartida. No se añade en esta fase una falsa garantía.

## Crecimiento de CartOperation

Índices existentes: PK, FK Business, FK Sale y UNIQUE(Sale,key). La recuperación
filtra Sale/Business y hasta 50 UUID: el índice compuesto mantiene la búsqueda
acotada por identidad. No se añade migración, índice ni expiración. Recibos de
líneas borradas siguen siendo necesarios: su ID resultado no es FK a SaleLine.

Comando nuevo de solo lectura:

```bash
python manage.py cart_receipt_stats
python manage.py cart_receipt_stats --exact
```

En PostgreSQL informa estimaciones `pg_stat_user_tables`, filas muertas y bytes
de tabla/índices, sin datos de clientes, productos o pagos. `--exact` hace COUNT y
MIN/MAX de fechas: usar fuera de hora punta en tablas grandes; no ejecutarlo en
cada petición ni de forma automática. No requiere extensiones de PostgreSQL.

Ejemplo de capacidad, no medición: 1.000 ventas/día × 50 operaciones × 365 días =
18.250.000 recibos/año. Medir bytes reales, pendiente semanal, filas muertas,
latencia del índice, autovacuum y espacio disponible. Alertar por crecimiento y
espacio; analizar con EXPLAIN en staging y estadísticas actuales. No estimar bytes
por fila a partir de un único ticket pequeño ni lanzar COUNTs continuos.

Conservar recibos durante la vida de Sale. Sin límite contractual equivalente de
reintento, TTL/compactación/archivado que quite la consulta activa es inseguro.
Una futura ventana o partición/archivo con consulta debe presentar contrato,
rechazo de claves antiguas y migración por separado: PENDIENTE DE AUTORIZACIÓN.

## Preparación de staging y compatibilidad de versiones

Evidencia del repositorio, no del proceso desplegado:

- `render.yaml`: `gunicorn config.wsgi:application --bind 0.0.0.0:$PORT`, plan free.
  No contiene números de workers/threads, timeout ni configuración de pooler.
  No deducir la configuración efectiva de esos valores ausentes.
- `build.sh` y `docker-entrypoint.sh` ejecutan `migrate --noinput` automáticamente.
  Revisar este comportamiento antes de cualquier despliegue/rollback; no permitir
  que arranques concurrentes gestionen el cambio de esquema sin coordinación.
- `CompressedManifestStaticFilesStorage` + WhiteNoise generan nombres con hash;
  no basta con vaciar el caché del JS sin recargar HTML ya abierto.
- No se encontraron registros de service workers en static/templates. No se
  puede descartar un proxy/CDN o un cliente histórico instalado fuera del repo.
- Fase 2C no añade migración. `0007` de fase 2B conserva la columna con DEFAULT 0
  y los recibos; ese default no hace compatibles los escritores previos.

Procedimiento para el operador, en staging; **no se ha ejecutado en Render**:

1. Crear staging con copia anonimizada, endpoints fiscales/bancarios deshabilitados
   y credenciales de prueba. Registrar commit y variables no sensibles relevantes.
2. Obtener backup y probar restauración antes del cambio. Ejemplo con conexión
   configurada de staging, sin escribir DSN en logs:

   ```bash
   pg_dump --format=custom --file=/ruta-segura/staging-pre-cart.dump
   pg_restore --list /ruta-segura/staging-pre-cart.dump
   ```

   Listar el archivo no verifica restaurabilidad: restaurarlo en otra base
   desechable y ejecutar las comprobaciones de integridad antes de continuar.
3. Establecer una ventana sin nuevas ediciones/cobros y pedir que cada caja
   sincronice su cola. Si hay resultados desconocidos, conservar diarios y
   comprobar recibos; no forzar borrados ni cerrar pestañas con pendientes.
4. Registrar el SHA real en la consola interna de Render:

   ```bash
   python -c 'import os; print(os.getenv("RENDER_GIT_COMMIT", "commit no proporcionado"))'
   uv run python manage.py showmigrations sales --plan
   uv run python manage.py migrate --plan
   uv run gunicorn config.wsgi:application --print-config | \
     rg '^(workers|threads|worker_class|timeout|graceful_timeout|max_requests|preload_app)\s'
   ```

   Repetir en cada instancia. Revisar también dashboard/start command y cualquier
   `WEB_CONCURRENCY`/`GUNICORN_CMD_ARGS` sin volcar credenciales ni el entorno.
5. Con escritores detenidos/drenados, aplicar únicamente la migración prevista:
   si staging parte de antes de fase 2B, ejecutar `uv run python manage.py migrate
   sales 0007 --noinput`. Revisar dependencias y plan completo previamente.
   Evitar aplicar otras migraciones inesperadas del build/entrypoint automático.
6. Construir con `collectstatic`, publicar HTML y assets del mismo commit y
   arrancar exclusivamente workers compatibles. Comprobar SHA, salud, cantidad
   real de workers y ausencia de procesos/tareas externos antiguos. No usar un
   despliegue rolling con escritores previos a `cart_version` activos.
7. Empezar con `TPV_OPTIMISTIC_CART=0` en todos los workers compatibles. Verificar
   formularios progresivos, revisión de checkout, permisos y SQL/movimientos.
8. Recargar todas las cajas/dispositivos; retirar HTML cacheado e impedir que
   permanezcan cajas vendiendo con páginas incompatibles. Revisar los hashes del
   manifiesto y cabecera `X-Sales-Cart-Protocol:2`. Una página sin versión de
   checkout debe obtener 409; un cliente nuevo con servidor incompatible debe
   detener el envío y pedir recarga.
9. Activar `TPV_OPTIMISTIC_CART=1` para un grupo controlado **solo después de que
   todos los escritores sean compatibles**. El flag actual es global por proceso:
   un piloto por Business no existe; usar staging/instancia/grupo de terminales
   separado, no asumir que el flag tiene segmentación por negocio.
10. Ejecutar los tests y la matriz con latencia representativa. Capturar también
    traza navegador + diagnóstico 1.5, SQL/locks, workers y conexiones. Supervisar
    409/422/timeouts, duración/edad de colas, latencia de locks, recibos y p95 de
    cobro. Comparar el SHA desplegado con el auditado antes de atribuir causas.

Para forzar recarga sin perder intenciones, primero resolverlas/verificarlas en
el backend compatible. Un operador no debe vaciar almacenamiento a la fuerza.
No se añade un endpoint remoto para exponer configuración o credenciales.

## Rollback A — desactivar solamente la UX

1. Pausar nuevas operaciones del piloto y vaciar/verificar colas existentes.
2. Si hay desconocidos, mantener backend nuevo y sus assets disponibles para
   recuperar la misma petición/recibos. Si no se pueden resolver, mantener esa
   caja pausada y pedir asistencia; no descartar ni limpiar por TTL.
3. Configurar `TPV_OPTIMISTIC_CART=0` en todos los workers compatibles, reiniciar
   de forma coordinada y recargar páginas ya reconciliadas.
4. Conservar `0007`, CartOperation, versiones y endpoint batch: un cliente viejo
   abierto puede necesitar reproducir su vuelo. Verificar formularios HTML y
   revisión de checkout. El flag solo cambia el frontend servido en páginas nuevas.
5. No volver a activar hasta revisar logs, recibos y coherencia de tickets.

## Rollback B — revertir backend

1. Detener nuevas escrituras en todas las cajas y tareas. Capturar el SHA y hacer
   backup; conciliar cada diario con los recibos mediante el backend actual.
2. Si una petición nueva batch está sin resolver, NO retirar todavía ese backend:
   un backend anterior puede no entender su payload. Mantenerlo para recuperación
   o diseñar una herramienta de conciliación explícita; no convertir el payload
   ni emitir UUID nuevos ante un resultado desconocido.
3. Tras verificar que no quedan desconocidos, drenar los procesos actuales y
   arrancar el commit anterior con UX apagada. Conservar esquema y recibos.
   Volver a a356003 mantiene los escritores con versión, pero pierde el contrato
   batch y su comprobación nueva de identidad; requiere páginas/journals conciliados.
4. Retroceder más allá de fase 2B es incompatible con escritores de versión:
   mantener el protocolo nuevo apagado, impedir clientes nuevos, documentar las
   ventas editadas por código antiguo y no reactivarlo sin conciliar y avanzar
   controladamente sus revisiones. No improvisar UPDATEs globales de versión.
5. Recargar todas las cajas verificadas, probar venta/checkout/devolución y vigilar
   discrepancias. No ejecutar `migrate sales 0006`: destruiría los recibos.

Un rollback de código no es rollback de pagos/documentos ya confirmados. No se
alteran los procedimientos económicos existentes para «deshacer» estas pruebas.

## Ejecución reproducible y validación

Preparar únicamente una base local desechable, nunca DATABASE_URL de producción:

```bash
uv sync --dev
uv run python -m playwright install --with-deps chromium
docker run --rm --name netxodo-phase2c-pg \
  -e POSTGRES_PASSWORD=local-diagnostic-only -e POSTGRES_DB=tpv_diag_phase2c \
  -p 127.0.0.1:55433:5432 postgres:16
```

El último comando mantiene PostgreSQL en primer plano; usar otra terminal y
comprobar `docker exec netxodo-phase2c-pg pg_isready -U postgres` antes de continuar.

```bash
export SECRET_KEY=local-phase2c-diagnostic-only
export DJANGO_SETTINGS_MODULE=config.settings.diagnostic_postgres
export TPV_DIAGNOSTICS=0
export TPV_TEST_DATABASE_URL=postgresql://postgres:local-diagnostic-only@127.0.0.1:55433/tpv_diag_phase2c
uv run ruff check .
uv run ruff format --check .
uv run python manage.py check
uv run python manage.py makemigrations --check --dry-run
uv run python manage.py test --noinput
uv run python manage.py test e2e.browser_optimistic_cart e2e.browser_cart_hardening \
  e2e.browser_checkout e2e.browser_full_flow e2e.browser_htmx_global_ux --noinput
mkdir -p work/tpv-optimistic-cart
TPV_BURST_REPORT=work/tpv-optimistic-cart/phase2c-bursts.json \
TPV_BURST_REPRESENTATIVE_SAMPLES=20 \
  uv run python manage.py test tests.performance.cart_burst_matrix.CartBurstMatrix --noinput
```

No ejecutar runners simultáneos contra la misma base de test. Los settings exigen
PostgreSQL y nombre `tpv_diag_*`; el runner crea/destruye `test_tpv_diag_*`.
El benchmark lee `a356003:static/js/sales_cart.js` desde Git: conservar ese commit.
Usar `TPV_BURST_SMOKE=1 TPV_BURST_REPRESENTATIVE_SAMPLES=1` para un ensayo corto,
no para reemplazar la matriz final. Detener el PostgreSQL local al terminar.

Resultados de validación antes de la matriz:

- Suite completa PostgreSQL: **1.613 tests correctos, 192,350 s**. Incluye Sales,
  Payments, Billing, Inventory, aislamiento, validaciones, stock/devoluciones,
  idempotencia, rollback y carreras con locks reales.
- Gate conjunto de navegador: **61 tests correctos, 180,457 s**. Incluye 20 del
  carrito original, 19 de endurecimiento, 16 de checkout, 1 flujo completo
  venta/devolución y 5 de HTMX/fallback.
- Tras reforzar la validación del diario y mensajes: **23 tests correctos,
  61,108 s**, con los 20 de endurecimiento actuales, 2 regresiones específicas
  de timeout/dos pestañas y 1 smoke A/B PostgreSQL con pago ficticio por interfaz.
  Son **62 casos únicos de navegador**, además del smoke de rendimiento.
- Prueba final de respuesta de checkout tardía, retenida en el servidor de test
  y sin tareas de rutas Playwright pendientes: **1/1, 2,851 s**. No hay error JS
  ni HTML antiguo insertado en el modal nuevo.
- `ruff check`, formato de los 460 Python versionados/nuevos destinados al commit,
  `node --check`, Django check, ausencia de migraciones nuevas y diff check: correctos.
  Se excluyó del formato solamente `work/`, directorio de evidencias locales no
  versionadas que no existe en un checkout de CI.
- `collectstatic` con `CompressedManifestStaticFilesStorage`: correcto; manifiesto
  con hash para el JS actual (`js/sales_cart.946d8e34ff4b.js`) y el JS legado.
  No se modifica la configuración real.
- Compose config y build Docker local: correctos. Se usó una copia temporal sin
  `.env` real ni evidencias, y se montó la CA del proxy como secreto de BuildKit
  solo en `uv sync` para mantener TLS. Esa adaptación no modifica Dockerfile,
  Compose ni dependencias del proyecto. La imagen **no se arrancó ni publicó**.
- El job de navegador de CI incluye ahora `e2e.browser_cart_hardening`. El job
  PostgreSQL existente descubre las tres carreras nuevas de lotes. Push de una
  rama de feature no dispara por sí solo los workflows limitados a main/develop
  y pull requests; no se afirma que GitHub Actions haya ejecutado estos checks.

Los errores iniciales del arnés se corrigieron y se repitieron: espera de campos
hidden con estado `attached`, revisión de un radio que el servidor puede revertir,
lectura de resumen vacío en el smoke y liberación del GET retardado. No fueron
invariantes comerciales fallidas; los resultados anteriores solo cuentan gates
correctos después de esos ajustes.

Se comprobaron ráfagas, cantidades decimales, eliminación, dependencias
provisionales, foco/teclado/tablet, dos pestañas, reconexión, respuesta perdida
tras commit, cuota/corrupción, diario parcialmente limpiado, expiración de sesión,
namespace de usuario/Business/Store/Sale, error/aborto/timeout de cabecera,
`busy`/`headerPending` atascados, cierre/reapertura y versión obsoleta. El lector
se simula como teclado y búsqueda por código: no se ha probado hardware físico.

No se han ejecutado pruebas en Render, pooler real, dispositivos físicos ni
navegadores distintos de Chromium. No se ha probado restore de backup real ni
migración de producción, ni se modifica configuración para hacerlo. Las pruebas
locales de rollback económico y migración anterior no sustituyen ese gate operativo.

## Diseño de las mediciones

Se compara el JavaScript de `a356003` con el de `7bd6416`, sobre **el mismo backend
actual**, servicios, catálogo, precios, impuestos, configuración y PostgreSQL.
No se comparan distintos despliegues históricos ni se atribuyen cambios de CPU
al transporte. El orden baseline/hardened se alterna para reducir sesgo de orden.
No hubo otros runners/builds pesados concurrentes durante la matriz final.

Entorno: Python 3.12.12, Django 5.2.12, psycopg 3.3.3, Chromium 151.0.7922.173,
PostgreSQL 16, x86_64, cuota de CPU de 2 cores y memoria máxima de 8 GiB. Datos
sintéticos, stock inicial holgado de prueba; cada caso usa una Sale nueva con
1/20/50 líneas previas y añade 10/20/50 líneas del mismo producto, sin fusionarlas.
El stock y documentos confirmados se acumulan en esa base desechable, sin llegar
al umbral de insuficiencia. Ambos tratamientos comparten ese entorno y se alternan;
no son muestras independientes de múltiples máquinas o de producción.

La demora de 100/300/600 ms se impone antes de enviar cada POST de carrito y cada
GET/POST de checkout al servidor local. Los GET de conciliación del carrito no
llevan demora impuesta. No equivale a emular toda una red de ida/vuelta, pérdidas,
ancho de banda o el servicio real de Render.

Las 27 combinaciones se ejecutan una vez por interfaz. La celda de 20 líneas,
300 ms y 20 pulsaciones se repite hasta **20 muestras por interfaz**: 92 casos
medidos en total. Solo esa celda tiene p50 y p95 descriptivos; p95 usa rango más
próximo (muestra ordenada 19 de 20). No es una garantía del p95 de producción ni
un intervalo de confianza. Las otras celdas tienen n=1 y se muestran como
observaciones exploratorias, sin percentiles inventados.

Definiciones separadas:

1. **Visual:** cota de dos requestAnimationFrame después de generar la ráfaga
   completa en una tarea JS. Incluye el coste de todos sus handlers/DOM; no es
   tiempo puro de pintura ni la latencia de un clic humano aislado. No se compara
   directamente con los 13–23 ms anteriores medidos para un único añadido.
2. **Persistencia:** desde el inicio de la ráfaga hasta primera confirmación de
   todas las operaciones, cola vacía y ningún envío activo. Cada caso comprueba
   suma de cantidades y número exacto de SaleLine en PostgreSQL.
3. **Peticiones:** número de POST de carrito para confirmar la ráfaga; no cuenta
   como mutaciones los GET de conciliación ni los GET/POST de checkout.
4. **Apertura:** tiempo JS hasta mostrar la carcasa modal tras pulsar Cobrar.
5. **Utilizable:** desde pulsar Cobrar hasta formulario autoritativo de checkout
   visible. Incluye la cola que faltaba por confirmar y su GET final.
6. **Confirmación:** desde pulsar Confirmar hasta éxito completo de checkout
   visible. Incluye inventario, registro de pago local y emisión ficticia del
   documento; no representa una pasarela bancaria ni una emisión fiscal real.

Se comprueba un solo Payment por Sale y éxito de checkout en todos los casos.
El producto ya está visible antes de terminar HTTP en ambos frontends optimistas;
la mejora perseguida aquí es drenar las ráfagas, no adelantar un pago sin verificar.

## Resultados de rendimiento

Matriz completada sobre `7bd6416`: **92 casos correctos en 793,549 s**.
Muestras, métricas por petición y resúmenes en
[tpv-phase2c-measurements.json](tpv-phase2c-measurements.json).

Celda repetida: **20 líneas previas, 300 ms impuestos, 20 pulsaciones; n=20
por interfaz**. Valores p50 / p95 en ms, salvo peticiones:

| Medida | Baseline a356003 | Endurecido |
| --- | ---: | ---: |
| Cota visual de la ráfaga completa | 46,0 / 66,6 | 45,7 / 64,8 |
| Persistencia completa | 7 439,7 / 7 739,5 | 1 189,6 / 1 283,3 |
| POST de carrito | 20 / 20 | 1 / 1 |
| Apertura de carcasa de checkout | 16,3 / 25,5 | 18,6 / 25,9 |
| Checkout utilizable | 7 904,4 / 7 943,5 | 1 363,2 / 1 384,0 |
| Confirmación y éxito completo local | 1 659,4 / 1 672,6 | 1 657,4 / 1 696,0 |

La persistencia p50 cae un **84,0 %** en esa celda; los viajes de
mutación pasan de 20 a 1. La confirmación final sigue alrededor de 1,66 s:
no se presenta como aceleración del pago ni del motor fiscal. La cota visual
es comparable entre interfaces; su mejora no es la conclusión de esta prueba.

Cobertura completa. Cada celda tiene una observación por interfaz, salvo la
marcada * que muestra medianas de n=20. No son p95 de las celdas exploratorias.

| Líneas | Demora ms | Pulsaciones | POST antes/después | Persistencia ms antes/después | Utilizable ms antes/después |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | 100 | 10 | 10 / 1 | 1 718,7 / 560,3 | 1 892,5 / 863,6 |
| 1 | 100 | 20 | 20 / 1 | 3 331,8 / 1 043,8 | 3 892,3 / 1 352,5 |
| 1 | 100 | 50 | 50 / 1 | 8 191,6 / 2 408,9 | 8 440,0 / 2 883,1 |
| 1 | 300 | 10 | 10 / 1 | 3 660,1 / 743,8 | 3 879,6 / 864,6 |
| 1 | 300 | 20 | 20 / 1 | 7 321,1 / 990,6 | 7 907,4 / 1 333,4 |
| 1 | 300 | 50 | 50 / 1 | 18 139,4 / 2 351,1 | 18 479,6 / 2 872,9 |
| 1 | 600 | 10 | 10 / 1 | 6 623,4 / 1 018,2 | 6 871,8 / 1 349,5 |
| 1 | 600 | 20 | 20 / 1 | 13 326,5 / 1 755,9 | 13 466,6 / 2 355,5 |
| 1 | 600 | 50 | 50 / 1 | 33 848,7 / 2 814,5 | 34 161,5 / 3 394,6 |
| 20 | 100 | 10 | 10 / 1 | 1 779,6 / 560,1 | 2 389,0 / 855,2 |
| 20 | 100 | 20 | 20 / 1 | 3 453,1 / 1 035,5 | 3 917,8 / 1 402,2 |
| 20 | 100 | 50 | 50 / 1 | 8 898,3 / 2 145,8 | 8 929,8 / 2 372,3 |
| 20 | 300 | 10 | 10 / 1 | 3 712,7 / 762,3 | 3 902,6 / 869,5 |
| 20 * | 300 | 20 | 20 / 1 | 7 439,7 / 1 189,6 | 7 904,4 / 1 363,2 |
| 20 | 300 | 50 | 50 / 1 | 19 408,4 / 2 431,0 | 19 583,6 / 2 878,9 |
| 20 | 600 | 10 | 10 / 1 | 6 743,8 / 1 116,9 | 6 900,7 / 1 370,2 |
| 20 | 600 | 20 | 20 / 1 | 13 550,2 / 1 493,9 | 13 982,0 / 1 908,1 |
| 20 | 600 | 50 | 50 / 1 | 34 155,2 / 2 761,3 | 34 187,7 / 2 892,6 |
| 50 | 100 | 10 | 10 / 1 | 1 801,3 / 621,1 | 1 901,8 / 883,4 |
| 50 | 100 | 20 | 20 / 1 | 3 762,3 / 1 079,1 | 3 952,6 / 1 359,2 |
| 50 | 100 | 50 | 50 / 1 | 8 892,3 / 2 726,8 | 8 959,3 / 2 933,6 |
| 50 | 300 | 10 | 10 / 1 | 3 836,2 / 1 004,3 | 3 919,4 / 1 413,7 |
| 50 | 300 | 20 | 20 / 1 | 7 558,9 / 1 356,1 | 7 932,0 / 1 882,3 |
| 50 | 300 | 50 | 50 / 1 | 18 606,6 / 2 380,8 | 18 518,6 / 2 388,9 |
| 50 | 600 | 10 | 10 / 1 | 6 746,8 / 1 094,6 | 6 905,1 / 1 366,6 |
| 50 | 600 | 20 | 20 / 1 | 13 710,3 / 1 578,2 | 14 045,1 / 1 871,7 |
| 50 | 600 | 50 | 50 / 1 | 35 140,2 / 2 796,3 | 35 274,2 / 2 883,6 |

En las 92 ejecuciones, el baseline usa un POST por pulsación y el nuevo
transporte un POST por ráfaga de hasta 50. No se perdió ninguna unidad,
se preservó una SaleLine por añadido y hubo un único Payment por Sale.
El caso exploratorio de 50 líneas + 50 pulsaciones a 600 ms pasó de
**35 140,2 a 2 796,3 ms** de persistencia, con 50 → 1 POST. Es n=1, no
una promesa de latencia real. Las seis medidas de cada caso permanecen en JSON.

## Archivos y commits

- `apps/sales/cart.py`: núcleo reutilizado y transporte atómico sin alterar servicios.
- `apps/sales/views.py`: selección del formato, protocolo, guard de usuario.
- `static/js/sales_cart.js`: diario de vuelo, lotes, esperas/eventos, recuperación,
  estados, protección de identidad y modal.
- `apps/sales/management/commands/cart_receipt_stats.py` y paquetes: observabilidad.
- `apps/sales/tests/integration/test_cart_batch.py`, `tests_postgres_cart.py`:
  contratos, rollback, idempotencia, aislamiento y carreras.
- `e2e/browser_cart_hardening.py`, `browser_optimistic_cart.py`: pruebas de navegador
  y metadatos del protocolo en el arnés existente.
- `.github/workflows/ci.yml`: gate nuevo de navegador; no hay job de despliegue nuevo.
- `tests/performance/cart_burst_matrix.py`: matriz y datos reproducibles.
- Este informe, el plan previo y JSON de mediciones. No se versionan logs de `work/`.

Commits: `3a1dc08` (implementación y pruebas), `7bd6416` (GET tardío del arnés sin
fugas de rutas), `abcb9a7` (límite de cierre forzado y reapertura probado,
1/1 correcto en 2,795 s). El commit de cierre añade informe y muestras, sin cambiar
el código de aplicación medido. Se conserva todo el historial de fase 2B e inventario.

## Riesgos y siguientes pasos

- Un guardado de cabecera puede coincidir con un lote ya iniciado; ambos usan
  el lock de Sale y pueden exigir revisión por 409. No se fusionan intenciones
  externas ni se ignora el conflicto para habilitar el cobro.
- Un lote mantiene el lock de Sale durante más trabajo servidor que una operación
  aislada. Máximo 50, sin concurrencia de lotes por cola; otras cajas pueden
  esperar o recibir conflicto. No se eliminan locks para bajar tiempos.
- Un fallo nuevo revierte el lote completo; las intenciones se conservan para
  revisión. La interfaz actual permite descartar el conjunto rechazado, no editar
  individualmente un lote de resultado desconocido. No hay aplicación parcial
  silenciosa ni sustitución de UUID para eludir recibos.
- Sigue habiendo cálculo/validación por operación, crecimiento de recibos y límites
  de almacenamiento local. El diario `flight` duplica temporalmente sus intenciones
  para soportar limpieza interrumpida; agotamiento de cuota requiere intervención.
- Una cola de más de 50 operaciones se divide secuencialmente. El presupuesto de
  flush puede agotarse en una cola grande: la espera termina con error recuperable
  y se conserva el trabajo, en lugar de habilitar un cobro anticipado.
- No se garantiza recuperar intenciones nunca confirmadas tras cierre definitivo,
  borrado del almacenamiento o pérdida del dispositivo. Debe aprobarse una
  estrategia durable si ese requisito es obligatorio para las cajas.
- Los workers anteriores al versionado y los clientes antiguos necesitan el
  procedimiento de drenaje/recarga. El flag de UX no subsana esa incompatibilidad.

Siguiente prioridad: validar en staging representativo y capturar la traza real
según [DIAGNOSTIC.md](../../tests/performance/DIAGNOSTIC.md), correlacionando
navegador, espera de worker, Django, servicios, SQL y locks. **La causa de los
20 segundos reales sigue sin identificarse**; no se atribuye a red, Render o
PostgreSQL a partir de esta matriz local.

Después, decidir el requisito de durabilidad al cerrar pestañas y la política de
terminal compartido. Si el procesamiento CPU/SQL del lote domina tras quitar los
viajes HTTP, presentar una optimización del contexto/recalculo de Sales con
pruebas de equivalencia; no compactar snapshots ni saltar validaciones por intuición.


## Veredicto

**APTO PARA STAGING** con el procedimiento de backend homogéneo, datos ficticios,
recarga de cajas conciliadas y supervisión descritos. Las pruebas críticas pasan;
no se considera validado el despliegue real ni se ha autorizado producción.

- **CORREGIDO:** viajes HTTP de ráfagas, diario atómico del vuelo, esperas sin
  plazo, contador de cabecera, continuación de modal cerrado y envío nuevo ante
  identidad/protocolo incompatibles.
- **MITIGADO:** desconexiones/recarga/corrupción/cuota, crecimiento de recibos y
  compatibilidad operativa entre versiones. La pérdida definitiva de contexto de
  pestaña sigue sin recuperación garantizada; si se exige esa durabilidad, este
  alcance no satisface ese requisito y debe completarse antes del piloto de cajas.
- **PENDIENTE DE AUTORIZACIÓN:** nueva retención contractual/TTL, archivado que
  altere consultas de reintento, migraciones estructurales y despliegue/configuración
  real. Solo se presentan propuestas; no se ejecutaron esas actuaciones.
- **NO REPRODUCIDO:** la causa de los 20 s de la grabación real. Una cola artificial
  puede superar ese tiempo, pero no demuestra que esa fuera la etapa o causa real.
