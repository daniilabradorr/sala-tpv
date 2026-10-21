# Diagnóstico temporal TPV — fase 1.5

Base: `48f2f4d4a6be6904b8a54f8fe1062ddd41eb7f59`.
Rama local: `diagnostic/tpv-phase-1-5`. Sin push, merge ni despliegue.

## Resultados obtenidos el 20 de octubre de 2026

Entorno cloud local, Python 3.12.12, Django 5.2.12, Gunicorn 25.1.0,
PostgreSQL 16.15 directo (sin pooler), Chromium 151.0.7922.173. Gunicorn sync,
un worker y un thread, timeout=30s; conexiones Django persistentes 600s.
PostgreSQL: max_connections=100; statement_timeout, lock_timeout e
idle_in_transaction_session_timeout=0. Estos valores pertenecen a la prueba.
No se conoce el SHA desplegado ni la configuración efectiva de Render.

Matriz HTTP loopback: un warmup y cinco muestras por celda; p50 en ms:

| Operación | 1 línea | 20 líneas | 50 líneas |
|---|---:|---:|---:|
| Añadir | 85,0 | 89,4 | 113,4 |
| Cantidad | 82,2 | 81,9 | 67,8 |
| Eliminar | 56,9 | 83,4 | 90,2 |
| Abrir checkout | 51,0 | 72,1 | 74,6 |
| Confirmar efectivo y emitir documento | 298,3 | 629,9 | 1.303,4 |

Descomposición del POST; valores inclusivos, no aditivos:

| Medida | 1 línea | 20 líneas | 50 líneas |
|---|---:|---:|---:|
| HTTP p95 | 439,3 | 754,2 | 1.355,5 |
| Django p50 | 281,38 | 620,06 | 1.289,12 |
| execute SQL p50 | 143,46 | 287,26 | 609,39 |
| Operaciones SQL | 334 | 1.078 | 2.248 |
| complete_sale p50 | 72,69 | 364,60 | 898,93 |
| inventory p50 | 18,82 | 302,90 | 788,28 |
| payment p50 | 65,31 | 58,76 | 56,46 |
| billing p50 | 59,51 | 135,43 | 250,02 |
| html_render p50 | 6,28 | 5,08 | 4,84 |
| Commit DB, agregado p50 | 5,78 | 4,94 | 6,15 |
| Residuo HTTP−Django, p50 por petición | 11,04 | 9,64 | 11,26 |
| Respuesta→dos frames, p50 | 53,6 | 44,3 | 50,9 |
| Interacción→dos frames, p50 | 358,2 | 678,7 | 1.359,9 |

No se midieron de forma separada red pura, cola pre-worker ni duración exacta de
locks. Las warm no abrieron conexiones nuevas dentro del POST. El tiempo desde
pre_request a entrada del middleware fue aproximadamente 0,27–0,32 ms.
La prueba artificial vio Lock/transactionid en la PID de la traza y un blocker
distinto. No demuestra locks durante las muestras normales ni en el despliegue.

Comparación alternada, diez pares por tamaño, coste mediano relativo por pareja:
1 línea +2,50%; 20 líneas +3,82%; 50 líneas −1,99% (ruido, no aceleración).
El coste de recopilar parece moderado en esta prueba; no hay un límite de overhead
demostrado y el logger de staging debe medirse aparte. La comparación secuencial
ON/OFF tuvo ruido de hasta +53 ms en checkout_20 y no se usa como efecto causal.

**CONFIRMADO:** fuerte crecimiento del trabajo con el ticket, principalmente
inventario y después Billing; número de llamadas inventory 1/20/50.
**NO REPRODUCIDO:** demora de 20 segundos en estos escenarios locales.
**NO VERIFICADO:** causa de la grabación, WAN, cold start, cola de workers,
pooler o contención de producción. Primera optimización propuesta: reducir
lecturas/validaciones repetidas por línea de inventario manteniendo locks,
movimientos, integridad e idempotencia; después Billing. Medir el despliegue
puede cambiar esta prioridad. No se ha implementado ninguna optimización.

Evidencias crudas en work/tpv-diagnostic/: postgres/server.json (diez muestras),
postgres/browser.json (servidor WSGI de Django), gunicorn/browser.json y logs
correlacionados, postgres/controlled-lock.json, postgres/overhead-paired.json,
runtime-local.json, postgres/runtime.json y summary.json. Los resultados
históricos del repositorio no se han sobrescrito. Las cifras HTTP de esta tabla
proceden exclusivamente de gunicorn/browser.json.

## Alcance y seguridad

Los módulos nuevos solo se cargan con settings de diagnóstico. No se editan
views/services/modelos/templates productivos. `DiagnosticMiddleware` instala
wrappers en memoria, incluidos los alias importados por Sales/Checkout; no se
cambian argumentos, valores de retorno, excepciones, locks ni transacciones.
`TPV_DIAGNOSTICS=0` y reiniciar desactiva los wrappers. No hay migraciones ni
dependencias nuevas. Las bases de pruebas y todos sus documentos son ficticios.

Los JSON contienen UUID de traza, estado HTTP, duraciones, contadores, nombres
fijos de etapas y PID técnico. No contienen URL, parámetros SQL, texto SQL,
POST, HTML, nombres, clientes, tarjetas, efectivo entregado, importes ni claves
de idempotencia. El UUID no identifica al pago y no sustituye su idempotencia.
El servidor valida el formato del UUID recibido y genera otro si es inválido.
La retención en memoria está limitada a 1.000 trazas; exportar solo el intervalo
necesario y aplicar retención corta a los archivos. Un resumen por petición;
ninguna consulta de diagnóstico SQL por sentencia ejecutada.

## Puntos de instrumentación y semántica

| Etapa | Punto real | Qué incluye |
|---|---|---|
| django | Middleware primero en la cadena | Middleware, view y render; excluye enviar bytes y escribir el log diagnóstico |
| view | SaleCheckoutView.get/post y vistas de añadir/cantidad/eliminar | Handler, formularios, servicios y render; excluye dispatch/permisos previos |
| checkout | run_checkout | Estado, preflight, venta, pagos y Billing |
| state/options | checkout_state/checkout_options | Relecturas y opciones, sumadas por llamada |
| complete_sale | Alias usado por run_checkout | Validaciones, stock y commit del servicio |
| inventory | decrease_stock, alias usado por complete_sale | Lock de InventoryItem, validación, movimiento y escritura |
| payment | register_sale_payment | Payment, CashMovement, balances y transacción |
| billing | issue_sale_document | Snapshots, líneas, desglose, serie, emisión y transacción |
| billing_lines | _create_lines_and_breakdowns | Guardados de hijos y sus validaciones |
| html_render | render de apps.sales.views | Context processors, templates y construcción de HttpResponse |
| db_connect/commit/rollback | BaseDatabaseWrapper, solo proceso diagnóstico | Tiempo de estas operaciones; separadas de execute |
| sql_execute | connection.execute_wrapper | Duración de execute/executemany, también fallidos |

Las etapas son **inclusivas**: inventario está dentro de complete_sale, que está
dentro de checkout y view. No sumar sus duraciones ni SQL. SQL incluye red hacia
DB, ejecución, espera de locks dentro de execute y parte del driver; no mide
por separado servidor PostgreSQL, fetch completo o commit. El contador también
incluye comandos de savepoint visibles por execute_wrapper. El cliente Django
TestCase añade una transacción exterior y no mide commits como HTTP real.

Gunicorn pre_request se ejecuta después de asignar y parsear una petición:
`assigned_request_to_django_ms` **no mide la cola anterior al worker**.
post_request mide hasta terminar el manejo/envío al socket; no acredita recepción
ni pintura en cliente. Para medir cola real hace falta un timestamp de entrada
del proxy/edge correlacionado, con reloj sincronizado y semántica documentada.
No se confía en un timestamp enviado por el navegador.

El script de navegador exporta Resource Timing (HTTP, TTFB, DNS, conexión,
descarga), espera del evento hasta beforeRequest, swap/settle y dos
requestAnimationFrame posteriores. Ese último dato es un **proxy de oportunidad
de pintura**, no una medición física de píxeles ni del tiempo de impresión.
Las pruebas comprueban además el DOM esperado. No sumar p50/p95 entre etapas.
El resumen calcula residuos por petición antes de calcular percentiles.
HTTP menos Django/Gunicorn es un residuo combinado, nunca «red pura».

## Ejecución reproducible

Desde la raíz del repositorio, usando el entorno virtual existente. No ejecutar
contra bases de negocio. Los settings ignoran DATABASE_URL para seleccionar la
base sintética y exigen nombres tpv_diag_* para PostgreSQL. Django crea y destruye
test_tpv_diag_*; no ejecutar dos matrices contra esa misma base a la vez.

SQLite, sin sockets:

```sh
TPV_DIAGNOSTICS=1 DJANGO_SETTINGS_MODULE=config.settings.diagnostic \
  .venv/bin/python manage.py test tests.performance.test_diagnostic \
  tests.performance.diagnostic_matrix.ServerMatrix --noinput
```

PostgreSQL 16 efímero, puerto solo loopback y credenciales ficticias:

```sh
docker run --detach --name tpv-phase15-postgres \
  -p 127.0.0.1:55432:5432 \
  -e POSTGRES_USER=tpv_diag -e POSTGRES_PASSWORD=synthetic-local-only \
  -e POSTGRES_DB=tpv_diag_phase15 postgres:16
docker exec tpv-phase15-postgres pg_isready -U tpv_diag -d tpv_diag_phase15
export TPV_TEST_DATABASE_URL='postgresql://tpv_diag:synthetic-local-only@127.0.0.1:55432/tpv_diag_phase15'
export DJANGO_SETTINGS_MODULE=config.settings.diagnostic_postgres
export TPV_DIAGNOSTICS=1
export TPV_DIAGNOSTIC_SAMPLES=10
TPV_DIAGNOSTIC_OUTPUT=work/tpv-diagnostic/postgres \
  .venv/bin/python manage.py test tests.performance.test_diagnostic \
  tests.performance.diagnostic_matrix.ServerMatrix --noinput
TPV_DIAGNOSTIC_OUTPUT=work/tpv-diagnostic/postgres \
  .venv/bin/python manage.py test tests.performance.diagnostic_lockcheck --noinput
```

Si pg_isready no confirma disponibilidad, esperar a que lo haga antes de medir.
En el entorno cloud gestionado usar el daemon local y las reglas Docker del
entorno; no cambiar contextos ni acceder a otros servicios existentes.

HTTP real con Chromium instalado y Gunicorn local de un worker sync:

```sh
TPV_DIAGNOSTIC_GUNICORN=1 TPV_DIAGNOSTIC_SAMPLES=5 \
TPV_CHROMIUM=/usr/bin/chromium \
TPV_DIAGNOSTIC_OUTPUT=work/tpv-diagnostic/gunicorn \
  .venv/bin/python manage.py test tests.performance.diagnostic_matrix.BrowserMatrix --noinput
```

El runner arranca y detiene Gunicorn en loopback, apuntándolo exclusivamente a
su test DB, y crea navegador autenticado con usuario ficticio. No hay credenciales
en los argumentos de Gunicorn. Bloquea recursos externos deliberadamente: esta
medición no representa fuentes remotas, WAN ni hardware del establecimiento.
Sin TPV_DIAGNOSTIC_GUNICORN se usa el servidor WSGI de Django de pruebas.

Cada operación usa una venta fresca: añadir producto visible #21, cantidad 1→2,
eliminar primera línea, GET checkout y POST efectivo exacto. Se repite para
1/20/50 líneas, un warmup y N muestras. El POST completa venta, stock, pago,
movimiento de caja y documento ficticio con servicios reales. Se comprueban
estado persistido, número de líneas, pago, documento y movimiento. Cinco muestras
solo ofrecen una exploración inicial: su p95 es el máximo observado.

Comparación básica ON/OFF, secuencial y sin otras pruebas simultáneas:

```sh
TPV_DIAGNOSTICS=0 TPV_DIAGNOSTIC_SAMPLES=10 \
TPV_DIAGNOSTIC_OUTPUT=work/tpv-diagnostic/postgres-off \
  .venv/bin/python manage.py test tests.performance.diagnostic_matrix.ServerMatrix --noinput
.venv/bin/python -m tests.performance.diagnostic_summary \
  --root work/tpv-diagnostic > work/tpv-diagnostic/summary.json
.venv/bin/python -m tests.performance.diagnostic_runtime --database \
  > work/tpv-diagnostic/runtime.json
```

La comparación secuencial no identifica causalmente el overhead: repetir en orden
alternado y aumentar muestras si se necesita un límite preciso. El runtime probe
solo exporta opciones permitidas; los defaults de Gunicorn están etiquetados y
no se presentan como configuración del proceso desplegado.

También existe una comparación alternada con dos warmups y pares ON/OFF:

```sh
TPV_DIAGNOSTICS=1 TPV_DIAGNOSTIC_SAMPLES=10 \
TPV_DIAGNOSTIC_OUTPUT=work/tpv-diagnostic/postgres \
  .venv/bin/python manage.py test tests.performance.diagnostic_overhead --noinput
```

Esta comparación mide el coste de recopilar trazas; el cliente OFF conserva
wrappers inactivos en memoria, y se excluye el I/O del log. Para comprobar el
logger del despliegue repetir en staging con su destino real. No interpretar un
delta negativo por ruido como una aceleración producida por la instrumentación.

Prueba aislada del observador de navegador, sin datos comerciales:

```sh
DJANGO_SETTINGS_MODULE=config.settings.diagnostic \
  .venv/bin/python manage.py test tests.performance.diagnostic_browsercheck --noinput
```

## Locks y pooler

La prueba diagnostic_lockcheck retiene el lock de una Sale en otra conexión,
inicia checkout real, observa wait_event_type=Lock y pg_blocking_pids en la misma
PID y libera el bloqueo. Comprueba éxito y un solo pago/documento/movimiento.
Es una prueba artificial del instrumento, no una reproducción de los 20 s.

Para una captura en entorno de pruebas, primero tomar las PID de una petición
warm del mismo worker/conexión y luego observar durante la siguiente operación:

```sh
export TPV_LOCK_DSN='DSN_DIRECTO_DE_PRUEBAS_DESDE_GESTOR_DE_SECRETOS'
.venv/bin/python -m tests.performance.diagnostic_locks \
  --pids 123 124 --seconds 30 --interval 0.1 > work/locks.jsonl
```

Sustituir PID por las reales. El sampler usa sesión separada, read-only y
statement_timeout=2s. No exporta SQL, usuario, nombres de tablas o credenciales.
Necesita visibilidad autorizada sobre pg_stat_activity; no cambiar grants desde
esta herramienta. El muestreo detecta esperas, no las cronometra exactamente y
puede omitir las menores al intervalo. Reutilizar PID solo mientras la conexión
siga viva. driver_backend_pids es fiable para conexión PostgreSQL directa; en
pooling transaccional no identifica necesariamente el backend real. En ese caso
usar métricas del pooler y mapear pg_backend_pid dentro de la transacción mediante
instrumentación adicional revisada. No atribuir al pooler todo el tiempo SQL.

## Captura en el despliegue real: pendiente, sin despliegue autorizado

1. Obtener el commit del deploy de Render (dashboard → deploy activo → commit),
   o leer RENDER_GIT_COMMIT en su shell. Si la aplicación tiene .git, contrastar
   git rev-parse HEAD. Comparar ese SHA con la base auditada usando git diff.
   La captura debe conservar hora, versión y número de instancia; evitar mezclar
   versiones durante un rolling deploy. No se ha accedido a Render en esta fase.
2. Revisar Start Command efectivo, región, plan, suspensión/reinicio y logs de
   worker. Obtener workers, threads, worker_class, timeout y límites de recursos
   del proceso realmente arrancado, no de defaults locales ni solo render.yaml.
3. Consultar en lectura los timeouts/versión/límites PostgreSQL con el runtime
   probe; confirmar conexión directa o pooler, modo de pooling, límites y espera
   de adquisición en el proveedor. No copiar DATABASE_URL ni logs SQL completos.
4. Para hoy, DevTools Network/Performance puede observar una sesión existente sin
   desplegar cambios. Registrar marcas y tiempos manualmente, sin exportar HAR
   crudo, cuerpos, cookies o datos personales. No efectuar un cobro real como test.
   Sin instrumentación desplegada no habrá separación de etapas del servidor.
5. Una vez autorizado, reproducir la misma versión en staging aislado, con datos
   ficticios e integraciones reales deshabilitadas. Incorporar middleware al
   principio, TPV_DIAGNOSTICS=1 y logger JSON de resumen; usar el hook Gunicorn.
   Revisar ese overlay como cambio de diagnóstico antes de cualquier despliegue.
   Los settings diagnostic_* de este paquete son de pruebas, con password hasher
   de pruebas: **no son settings aptos para producción**.
6. En staging, pegar diagnostic-browser.js en DevTools después de cargar el TPV.
   Ejecutar una acción cada vez, comprobar visualmente el resultado y exportar
   solo JSON.stringify(window.tpvDiagnostic.rows). Correlacionar UUID con logs
   Django/Gunicorn y PID con sampler. Detener con window.tpvDiagnostic.stop().
7. Para medir cola antes del worker, solicitar al proveedor tiempos de entrada
   edge y upstream con el mismo identificador. Si no están disponibles, marcar
   esa separación como NO MEDIDA. No deducirla restando relojes navegador/servidor.
8. Repetir primera petición tras inactividad y warm, 1/20/50 líneas, después
   concurrencia representativa, misma región/DB/pooler y configuración efectiva.
   Medir recursos externos en una captura separada de la baseline loopback.

Ni este documento ni el flag autorizan cambios de producción. No hay push/merge
ni despliegue. Para finalizar la sesión local, detener y retirar únicamente el
contenedor creado: docker rm -f tpv-phase15-postgres.
