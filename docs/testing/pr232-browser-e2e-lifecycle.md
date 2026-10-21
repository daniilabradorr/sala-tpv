# PR #232: aislamiento del servidor E2E antes de flush

## Evidencia y causa

Se analizó el log completo del job `browser-e2e` 119409867395 de la ejecución
[39654151259](https://github.com/daniilabradorr/sala-tpv/actions/runs/39654151259),
que ejecutó el merge provisional `67e9542` con head `6ef1612`.
PostgreSQL era 16.15. Resultado original: 133 tests, dos errores.

A las 18:43:00.617 UTC PostgreSQL registró este ciclo real:

| Proceso | Operación | Espera | Bloqueado por |
| --- | --- | --- | --- |
| 802 | `TRUNCATE` de las tablas de prueba (flush) | `AccessExclusiveLock`, relación 16866, base 16389 | 804 |
| 804 | `SELECT sales_saleline ... WHERE sale_id = 88 ORDER BY id` | `AccessShareLock`, relación 16872, base 16389 | 802 |

Los OID identifican relaciones de aquella base desechable; el log no permite
asignarles nombres con certeza después de su destrucción. Sí contiene ambas
consultas y ambos participantes: limpieza de fixtures frente a una lectura HTTP
aún en curso. No es un conflicto entre dos operaciones económicas.

El primer error ocurre al limpiar `test_close_reopen_cancels_only_local_flush_wait`.
El `TRUNCATE` aborta y deja las fixtures anteriores. El siguiente test,
`test_corrupt_storage_blocks_editing_without_silent_fallback`, falla en `setUp`,
antes de probar storage: `Business.full_clean()` produce `ValidationError` porque
ya existe `browser-cart`. El segundo error es consecuencia del primero, no otro
fallo del protocolo ni una violación SQL independiente.

`LiveServerTestCase` hereda de `TransactionTestCase`: cada test hace flush, pero
el servidor HTTP vive hasta la limpieza de clase. Django 5.2 usa
`ThreadedWSGIServer.daemon_threads = True`. Cerrar una página/contexto cancela el
cliente, pero no interrumpe ni espera el código WSGI que ya se está ejecutando.
Las conexiones Django son locales al hilo; `connections.close_all()` en el hilo
principal o del servidor no cierra las de sus workers. Es `close_request()` en
cada worker quien las cierra.

La primera validación de una unión sin cierre de sockets detectó otro recurso
relevante: `route.fetch()` usa el agente HTTP keepalive compartido de Playwright.
En Playwright 1.55, cerrar el BrowserContext dispone sus respuestas, pero no
destruye ese pool global. Se observó un worker idle y su conexión PostgreSQL
esperando `ClientRead` después del test de cabecera. Por eso la corrección final
cierra también los sockets aceptados al apagar el servidor, antes de unir los
workers; esperar sólo threads tampoco basta. No se aumenta ningún timeout.

El cierre del modal aborta su XHR y lanza `queue.refresh()`; ni ese abort ni ver
el formulario del segundo checkout garantiza que el primer handler haya
terminado. Esto explica que la ejecución por push pase y la de PR falle con el
mismo head: depende de la planificación de threads, peticiones y locks.

## Revisión de recursos y corrección

Se revisaron los handlers de rutas de `browser_optimistic_cart`,
`browser_cart_hardening`, `browser_checkout` y `browser_tpv`. `route.fetch()`
completa la petición upstream antes de retener o descartar su respuesta;
`route.continue_()` permite que el servidor siga ejecutando. Retener una ruta sin
continuarla no equivale a una petición ya ejecutándose en Django. El test de
checkout obsoleto libera su `Event` en `finally`, pero su evento `finished`
marca el retorno de la vista, no la salida completa del worker y cierre de su
conexión.

La corrección se limita al arnés común de los tests de carrito y su subclase:

1. Los workers HTTP dejan de ser daemon para que `server_close()` los espere.
2. Después de `tearDown` y de todos los cleanups de unittest (contextos cerrados),
   se detiene la aceptación de peticiones. Se hace `shutdown(SHUT_RDWR)` de los
   sockets aceptados y se unen los workers **antes** del flush de Django.
   El shutdown despierta lectores HTTP idle; no interrumpe el código WSGI que ya
   está trabajando. La unión espera su salida y el cierre de sus conexiones.
3. El siguiente test crea otro servidor, conservando la gestión de conexiones
   SQLite compartidas y el cleanup de clase de Django.
4. La limpieza de rutas admite una página ya cerrada; el contexto se cierra de
   forma idempotente. El navegador y Playwright se cierran al terminar la clase.

No se modifican frontend, servicios, reglas económicas, concurrencia de negocio,
ni timeouts existentes. No se añaden sleeps ni reintentos de flush. Si no termina
un worker, no se adelanta la limpieza de su base.

## Regresión determinista

`test_aborted_checkout_worker_finishes_before_database_flush` retiene un checkout
real mediante un `Event`, abre además una conexión keepalive con
`context.request.get()`, cancela la petición desde el navegador y lo libera al
detener el servidor. Antes del flush comprueba que terminó la vista, que salió
el worker y, en PostgreSQL, que su PID ya no existe en `pg_stat_activity`.
Los límites de diez segundos son guardas de fallo de la prueba, no esperas para
ocultar la carrera.

Se ejecutó con el ciclo original de Django: falló con
`flush raced an aborted request`. Con el ciclo corregido pasa. La ejecución
negativa dejó temporalmente una conexión que impidió destruir su base; después
de terminar el proceso se eliminó esa base antes de las validaciones positivas.
No se reutiliza ese estado.

## Validación

Validación local previa al commit (PostgreSQL 16.15):

- Regresión: falla con el ciclo original, pasa con el corregido.
- Cada test investigado por separado: tres ejecuciones correctas por test.
- Pareja en orden normal: tres ejecuciones correctas.
- Pareja en orden inverso (`--reverse`): tres ejecuciones correctas.
- Las doce ejecuciones crean/destruyen su base; después de cada una se comprueba
  que no quedan sesiones en `pg_stat_activity` ni la base `test_netxodo_test`.
- Suite general: 1.613 tests, OK, 44 omisiones previstas.
- Grupos PostgreSQL de CI: Billing 10, Sales 27, Payments 3, Purchases 2 y Cash 6;
  todos correctos, con base nueva en cada grupo.
- Ruff lint y formato, Django check y comprobación de migraciones: correctos.

Protocolo adicional de validación completa: tres pasadas de los 134 tests E2E,
en directorios de trabajo y bases PostgreSQL independientes,
sin `--keepdb`, verificando sesiones y destrucción de la base después de cada
pasada, más todos los workflows automáticos de la PR tras el push a `develop`.
Los resultados finales y los enlaces a Actions se incluyen en la entrega.

La descarga local del Chromium de Playwright está bloqueada por la política de
red del entorno. Las pasadas completas locales usan Chromium 151 del sistema
mediante un lanzador temporal externo al repositorio que únicamente selecciona
el ejecutable. La CI conserva su instalación habitual de Chromium. Una primera
pasada local sin ese requisito instalado se interrumpió y no cuenta como
validación completa.

Comandos reproducibles (con Chromium de Playwright instalado como en CI):

```sh
export DJANGO_SETTINGS_MODULE=config.settings.test
export SECRET_KEY=test-secret-key
export DATABASE_URL=postgresql://postgres:postgres@127.0.0.1:5432/netxodo_test
python manage.py test \
  e2e.browser_cart_hardening.HardenedCartBrowserTests.test_close_reopen_cancels_only_local_flush_wait \
  e2e.browser_cart_hardening.HardenedCartBrowserTests.test_corrupt_storage_blocks_editing_without_silent_fallback \
  --verbosity 2 --noinput
# Repetir con --reverse; ejecutar también cada etiqueta individualmente.
# Para la suite completa, usar las mismas etiquetas del job browser-e2e de ci.yml.
```


## Hallazgo adicional al repetir la suite bajo carga

Las tres pasadas locales simultáneas de 134 tests sobre PostgreSQL 16.15
terminaron sin deadlocks, sin datos residuales y sin conexiones de prueba.
Una pasó completamente; dos detectaron otro fallo de preparación en
`test_keyboard_wedge_search_and_enter_preserve_units` (4 y 9 unidades frente a 10).
Las CI de push y PR habían pasado los 134 tests completos.

El test escribía el SKU y esperaba una primera tarjeta que ya existía entre las
20 tarjetas iniciales. La búsqueda tiene un debounce de 175 ms y sustituye
`#product-grid` mediante HTMX. Si esa respuesta llega durante los diez Enter,
se elimina la tarjeta enfocada y los Enter restantes se envían a `BODY`.
Se reprodujo reteniendo la respuesta de búsqueda: 20 tarjetas iniciales, primer
Enter sobre la tarjeta, respuesta liberada, foco en `BODY`, una unidad tras diez
Enter. No intervienen flush ni datos de otro test.

La preparación ahora espera que aparezca la única tarjeta del SKU filtrado antes
de enfocarla. Conserva la misma aserción de diez unidades y no añade sleeps,
timeouts ni cambios en código de producto. Se repiten el test, la suite completa
y las dos CI automáticas con esta sincronización.

## Sincronización del recorrido ERP al revisar caja

La CI por push `39668616218` y una pasada local reprodujeron un fallo distinto
al leer «Cobro de venta en efectivo», con `htmx:swapError` y
`Cannot read properties of null (reading 'querySelector')`.
El POST de arqueo devuelve 204 y dispara cierre de modal y `nx:refresh-region`.
Cerrar el modal no garantiza que haya terminado ese GET automático del panel.
El test solicitaba después Resumen y Movimientos, mientras las aserciones de
Resumen podían satisfacerse con el contenido anterior ya visible.
Varias respuestas `outerHTML` apuntaban al mismo nodo retirado.

Se reprodujo reteniendo la recarga automática hasta recibir la petición de
Resumen y liberando ambas respuestas sobre el mismo panel: el test falla por
los errores JavaScript, sin alterar operaciones económicas.
`browser_full_flow` ahora espera `htmx:afterSettle` del panel después de la
recarga automática y de cada cambio de pestaña. Conserva todos los pasos y las
aserciones de importes, stock, pagos, documentos, PIN y cierre. Las nuevas
condiciones usan el límite existente de cinco segundos; no se introducen
sleeps, reintentos ni cambios en los servicios o en el comportamiento de caja.
