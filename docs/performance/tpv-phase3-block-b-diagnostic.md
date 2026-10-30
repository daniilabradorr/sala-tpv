# Netxodo — Fase 3, Bloque B: diagnóstico de checkout

Fecha de recogida: 2026-10-28T19:30:17.371534+01:00. El informe parte del [Bloque A](tpv-phase3-block-a-audit.md) y se acompaña de [mediciones JSON](tpv-phase3-block-b-measurements.json) y [matriz de causas](tpv-phase3-block-b-findings.md).

## 1. Rama, SHA y límites de actuación

Rama existente: `fix/tpv-checkout-audit-phase3`. HEAD inicial: `453e9c61de9c2a61b0c628c8e966b1c4983b03fc`. `origin/main` verificado por fetch/ls-remote: `cdbf88c7df6b5c9d75ccdeda84c8ac8b67b03983`. El remoto de la rama seguía en el mismo HEAD. El árbol inicial estaba limpio y el Bloque A presente. No se incorporó main ni se creó otra rama. Los únicos cambios son documentación, settings de diagnóstico opt-in, observadores y pruebas; no se modifican servicios/modelos/plantillas/JS de aplicación, migraciones ni contratos económicos. Este bloque se deja sin commit/push/merge/PR/despliegue por la instrucción nueva del encargo.

## 2. Entorno aislado y procedencia de datos

Contenedor propio `tpv-phase3-b-postgres`, creado con `postgres:16-alpine`, digest `postgres:16-alpine@sha256:0cefaabd882e42bcb2a2f3dc56d3ce4770560ba62fd7f197f1a2e008fd5731ab`. Puerto publicado exclusivamente `127.0.0.1:55437`; datos sin volumen persistente, contenedor --rm. Base inicial sintética `tpv_diag_phase3`; Django crea y destruye `test_tpv_diag_phase3` en cada runner. Se verificaron la creación del contenedor, su puerto/label y su conectividad: el aislamiento no se deduce del nombre de la base. Se usa autenticación trust solo en este contenedor loopback desechable, sin credenciales reales. No se usa DATABASE_URL ni docker-compose del producto ni su volumen postgres_data.

Python 3.12.12, Django 5.2.12, psycopg 3.3.3, Gunicorn 25.1.0, Chromium 151.0.7922.173 (ejecutable del sistema). CPU virtual AMD EPYC 9V74: 3 CPUs visibles, cuota 2 cores; límite memoria 8 GiB; Linux 6.18.55. Runtime/versiones/SHOW PostgreSQL están en el JSON. HTTP loopback, conexión directa sin pooler, Gunicorn sync 1 worker/1 thread/timeout 30 s, conexiones Django persistentes 600 s. No representa hardware del comercio, WAN ni configuración efectiva Render.

Fixtures Dataset: perfil/emisor/cliente ficticios, dos impuestos, 60 productos, inventario sintético, métodos cash/card y series F1/F2. Creación de fixtures y cambios de configuración quedan fuera de los intervalos medidos. Bulk solo en fixtures. Cada muestra parte de Sale nueva; se validan saldos, stock, pagos y documentos después de medir. No hubo cobros, documentos fiscales ni datos reales.

## 3. Instrumentación reutilizada

Se revisaron `tests/performance/DIAGNOSTIC.md`, diagnostic.py, diagnostic_http.py, diagnostic_gunicorn.py, diagnostic_locks.py, diagnostic_matrix.py, settings diagnostic_* y los tests de checkout/concurrencia.

Se reutilizan middleware, Trace/RECENT, ContextVar de correlación, execute_wrapper, spans de alias de servicios, tiempos connect/commit/rollback, Server-Timing y observador HTMX/Resource Timing. Los UUID de tracing son técnicos, independientes de los UUID económicos. No se exportan POST, cookies, tokens, texto SQL, parámetros, HTML ni datos personales. Los nombres de tablas exportados son identificadores de esquema filtrados. Se conservaron únicamente contadores/estados de pruebas y duraciones.

El middleware base no habilita esto en producción. El arnés histórico usa firmas antiguas en algunos helpers (`checkout_data(dataset)` sin Sale en lockcheck/overhead); no se utilizó ese recorrido obsoleto. Se añadieron pruebas separadas con la firma actual, sin corregir código económico ni reescribir mediciones históricas.

## 4. Ampliaciones y coste del recolector

`config/settings/diagnostic_phase3.py` requiere settings dedicados PostgreSQL y, en Gunicorn hijo, el marcador de runner. `TPV_DIAGNOSTICS=1` **y** `TPV_PHASE3_DIAGNOSTICS=1` activan el detalle; por defecto permanece desactivado. No hay dependencia nueva. Los wrappers en memoria conservan argumentos, resultados, excepciones y orden de operaciones. Reiniciar el proceso deshabilita los parches instalados. No son settings para producción: heredan hashers de pruebas.

`phase3_trace.py` añade spans de preflight, forms, lectura inicial, recálculo/integridad, UUID/saldo/estado de pago, cash, snapshots, serie/numeración, auditoría, full_clean y contexto app_shell. Registra transacciones exteriores T1/T2/T3, duración de execute de FOR UPDATE y agregados por fingerprint SQL. `exclusive_ms` resta únicamente hijos directos de **detalle**, no todos los spans base; no se presenta como CPU puro. El tiempo de execute FOR UPDATE es una cota compuesta de ejecución/red/espera, no espera de lock pura.

Se cachea por hash la forma de SQL dentro de la traza y se agrupan los comandos de savepoint; no se guarda texto ni parámetros. La caché está limitada a 4096 hashes por petición. Los grupos exportan count/tiempo total/máximo individual. No se guardan todos los tiempos individuales, planes EXPLAIN ni textos; una atribución a línea exacta requiere una captura adicional revisada.

Se midió ON/OFF alternado, 2 warmups y 6 pares por tamaño, con transacciones reales y logger in-process sin I/O de archivo:

| Líneas | Delta mediano ON/OFF | Rango pares | Delta mediano ms |
|---|---:|---:|---:|
| 1 | 5.19% | -9.23%–15.34% | 10.37 |
| 20 | 3.43% | -3.09%–9.73% | 18.13 |
| 50 | 12.57% | 5.18%–22.87% | 117.78 |

El recolector **sí añade coste apreciable**, especialmente a 50 líneas; no se declara overhead despreciable ni se restan medianas para fabricar tiempos sin tracing. La primera versión dio +4,72/+5,85/+10,58% medianos; la caché redujo trabajo redundante pero los pares finales no prueban una reducción universal bajo este ruido. El JSON conserva ambos juegos. La matriz final usa solo v2; v1 no se mezcla como muestra adicional. No se recomienda habilitar el detalle continuamente en un negocio real; el logger HTTP de la matriz añade un coste que esta comparación sin archivo no aísla.

## 5. Método, muestras y estadística

Doce celdas E01–E12: 1 warmup separado y 7 muestras warm por celda (84 medidas + 12 calentamientos). Se informa min/mediana/max y valores individuales; p95=null por tamaño exploratorio insuficiente. No se midió cold start. Flujo real Chromium → HTTP → Gunicorn → PostgreSQL, con DOM esperado e invariantes persistidas. Recursos externos bloqueados en esta matriz.

La prueba adicional fiscal usa Client con TransactionTestCase en autocommit real, 1 warmup + 5 muestras/tamaño. Las carreras C01–C07 tienen 3 repeticiones con fixtures nuevas; no sirven para p95. Locks artificiales, fallos y pruebas browser tienen n=1 por condición. Las suites no se ejecutaron a la vez que la matriz.

Para obtener tiempo de máquina sin selección de método se suman **intervalos de cada petición individual** (abrir hasta dos frames + confirmar hasta dos frames); no medianas de etapas. El JSON también conserva el tiempo scripted desde COBRAR hasta confirmar: incluye latencia de automatización y selección, no un tiempo humano representativo.

## 6. Matriz funcional y resultados warm

Todos los valores son medianas ms, salvo número de operaciones SQL. T1 incluye preflight y complete_sale/Inventory. Payment es la suma de sus llamadas; en split son dos T2 independientes. T3 incluye Billing. SQL y etapas se solapan; **no sumar columnas**.

| ID | Líneas | Pago | Solicitud documento | HTTP POST | T1 | Payments | Billing/T3 | SQL execute | Operaciones SQL | Render |
|---|---:|---|---|---:|---:|---:|---:|---:|---:|---:|
| E01 | 1 | cash | ticket | 292.70 | 98.83 | 72.44 | 53.19 | 141.23 | 328.00 | 5.48 |
| E02 | 1 | card | ticket | 273.90 | 99.07 | 48.38 | 54.27 | 131.03 | 282.00 | 5.36 |
| E03 | 20 | cash | ticket | 662.30 | 372.64 | 67.74 | 149.25 | 326.04 | 882.00 | 5.72 |
| E04 | 20 | card | ticket | 587.70 | 340.84 | 39.32 | 139.41 | 289.09 | 836.00 | 5.39 |
| E05 | 50 | cash | ticket | 1136.20 | 721.77 | 64.39 | 268.77 | 559.44 | 1752.00 | 5.46 |
| E06 | 50 | card | ticket | 1145.80 | 727.99 | 41.05 | 288.58 | 556.67 | 1706.00 | 5.83 |
| E07 | 1 | split | ticket | 337.20 | 96.83 | 110.09 | 53.20 | 159.44 | 397.00 | 5.76 |
| E08 | 20 | split | ticket | 640.20 | 339.85 | 100.00 | 133.59 | 312.84 | 951.00 | 5.59 |
| E09 | 20 | card | invoice | 614.60 | 340.31 | 41.38 | 144.36 | 284.59 | 842.00 | 5.53 |
| E10 | 50 | card | invoice | 1129.50 | 734.55 | 41.81 | 282.97 | 543.00 | 1712.00 | 5.52 |
| E11_stock_off | 20 | card | ticket | 360.60 | 88.51 | 49.61 | 144.07 | 172.32 | 395.00 | 5.21 |
| E12_repeated | 20 | card | ticket | 585.70 | 345.17 | 38.05 | 134.49 | 289.00 | 833.00 | 5.41 |

E01–E10: stock ON y productos distintos. E11: 20 líneas tarjeta F2 stock OFF. E12: 20 líneas del mismo producto, movimientos separados. Comparar E04/E11 explora stock; E04/E12 productos repetidos. No son comparaciones aleatorizadas de causalidad pura. Las comparaciones de cajas/series están en C03/C06/C07.

Todas las ventas medidas finalizaron completed/paid/pendiente cero, un documento y un pago (dos en split), stock una vez por línea física cuando habilitado y cash solo en métodos físicos. También se verifica el efectivo total esperado por sesión frente a CashMovement. Ninguna celda final tuvo error HTTP ni JavaScript, ni processing persistente en el punto de dos frames. La ausencia de solicitudes duplicadas de confirmación en estas muestras no certifica todos los dispositivos/listeners.

## 7. Frontend y recorrido hasta confirmación

| ID | Clic→modal | Flush | GET checkout HTTP | COBRAR→dos frames | Confirmar→beforeRequest | Confirmar→dos frames | Respuesta→dos frames |
|---|---:|---:|---:|---:|---:|---:|---:|
| E02 | 8.40 | 32.80 | 65.10 | 177.30 | 4.70 | 327.60 | 52.20 |
| E04 | 13.10 | 43.50 | 45.30 | 176.90 | 4.40 | 643.30 | 55.70 |
| E06 | 19.10 | 42.60 | 41.90 | 182.20 | 4.30 | 1196.30 | 48.10 |
| E08 | 13.70 | 33.60 | 41.60 | 146.70 | 4.30 | 699.80 | 52.80 |
| E10 | 18.10 | 43.50 | 51.20 | 173.10 | 4.20 | 1194.80 | 57.20 |

phase3-browser.js usa performance.now, MutationObserver, fetch y eventos HTMX. Envuelve flush solo en la página sintética, manteniendo su retorno. Captura operaciones pendientes/inicialización, peticiones cart-sync, afterRequest/afterSwap/afterSettle, timeout/sendError/abort y contador de errores JS; una sola instalación por página/prototipo. Resource Timing permite TTFB/DNS/conexión/descarga; TTFB contiene trabajo servidor y **no** es red pura. El instante beforeRequest no acredita envío físico de bytes. Dos frames son oportunidad de pintura, no píxel físico ni impresión.

Pruebas dirigidas browser, independientes de la matriz:

- Inicialización retenida 300 ms: flush vio initialization_pending=True, espera observada 252.00 ms y flush 311.80 ms. No abrió formulario antes de drenar.
- POST cart-sync retenido 300 ms: una operación pendiente, flush 370.40 ms; la venta continuó abierta y sin pago. Es la fase previa a GET, no POST de cobro.
- Respuesta perdida: route.fetch deja terminar backend y route.abort elimina solo respuesta del navegador; sendError y mensaje desconocido, reintento con formulario conservado finaliza sin otro Payment/documento/stock.
- Timeout real de XHR configurado a 250 ms **solo en prueba**, servidor retenido 800 ms antes de Billing: timeout observado a 299.87 ms, processing=False, feedback visible=False. Aparece `htmx:timeout`, no sendError; el handler de aplicación no muestra el aviso desconocido. El servidor sigue y el reintento posterior deja un Payment/documento/movimiento. Es un defecto UX confirmado de este evento, no timeout productivo demostrado.
- Pausa artificial 20 s antes de entrar en Billing, después de pago: clic→éxito 20982.43 ms y flush previo 32.80 ms. Reproduce deliberadamente una espera visual similar, con causa conocida inyectada; **no reproduce ni atribuye la incidencia original**. No hay error fiscal natural en este control.

No hubo telemetría externa. No se instrumentó una impresora física. El timeout específico de 15 s del GET sigue siendo distinto del POST, cuyo default HTMX es 0.

## 8. Descomposición Django y H02/H04

| ID | Recálculo líneas | state acumulado | options acumulado | Preflight | Snapshots líneas | Numerar/emitir | Lock serie (servicio) | Auditoría acumulada |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| E02 | 16.89 | 27.20 | 4.64 | 11.93 | 1.15 | 21.22 | 0.78 | 11.73 |
| E04 | 12.79 | 28.62 | 4.81 | 10.58 | 1.51 | 22.61 | 0.98 | 11.63 |
| E06 | 22.72 | 28.82 | 5.54 | 11.86 | 2.06 | 23.02 | 0.96 | 11.77 |

Lectura inicial, forms, full_clean, app_shell y métricas exclusivas están en detail_stages del JSON. Dispatch incluye permisos y handler; su residual no es una medición aislada de autenticación. La carga bloqueada de SaleLine y la resolución de InventoryItem se observan por SQL/locks y por sus servicios, pero no tienen spans Python independientes para todos los pasos internos. Los tiempos de commit/connect/rollback están en stages; cada T2 y T3 tiene su registro de transacción. No se equiparan transacción completa y execute SQL.

H02: se confirman y cuantifican llamadas de state/options y recálculo; el agregado no es el ahorro alcanzable. Refresh después de commits, saldo bajo lock y reread autoritativo de stock son necesarios para consistencia. Reutilizar la respuesta run_checkout dentro de un contrato revisado y evitar repetir opciones en una misma respuesta son candidatos; aún no se eliminaron consultas.

H04: preflight se ejecuta dentro de T1, antes de completar Sale y modificar stock; perfil emisor y snapshots fiscales se validan dentro de Billing después de T2. Fallos de perfil fiscal/soporte pueden dejar paid sin documento. Comprobar configuración estática antes puede mejorar UX, pero cliente/serie/año/permisos e idempotencia deben revalidarse en la emisión. Cierre de caja, cambio de serie/configuración, error BD y fallo de respuesta pueden ocurrir después de T2; no hay preflight capaz de eliminar todos esos casos.

## 9. SQL: volumen frente a coste individual

Ejemplo E06, agregado de sus siete peticiones. `ms` es total del grupo en las siete, `max` la sentencia individual más lenta del grupo; no dividir ni comparar con mediana HTTP como si fueran la misma muestra.

| Fingerprint/comando | Operación | Tablas allowlist | Ejecuciones | Total ms | Máximo individual ms |
|---|---|---|---:|---:|---:|
| 0953787d37195ff4 | SELECT | inventory_inventoryitem | 350 | 392.03 | 3.248 |
| 9e654422b597350b | SELECT | expresión/check o fuera de allowlist | 1134 | 369.09 | 3.898 |
| SAVEPOINT | SAVEPOINT | expresión/check o fuera de allowlist | 1687 | 300.36 | 2.579 |
| RELEASE | RELEASE | expresión/check o fuera de allowlist | 1687 | 257.78 | 1.987 |
| cd5e36ccd3aa504b | SELECT | expresión/check o fuera de allowlist | 770 | 228.96 | 2.722 |
| 59252ab3cc74a5a0 | SELECT | sales_saleline | 700 | 214.56 | 2.250 |
| e2e9370ed01bea95 | INSERT | inventory_stockmovement | 350 | 210.82 | 1.341 |
| 98d3e520860da551 | SELECT | expresión/check o fuera de allowlist | 700 | 191.15 | 1.668 |
| 7d5e0671eb043e7e | INSERT | billing_billingdocumentline | 350 | 154.97 | 2.029 |
| 9aa33aeb38df8abd | UPDATE | inventory_inventoryitem | 350 | 143.73 | 2.165 |

Los grupos más repetidos incluyen lecturas/validaciones por línea y SELECT de checks/constraints (algunos sin FROM). La lista allowlist no enumera todas las tablas de joins ni garantiza identificar la línea del llamador. El máximo execute SQL individual observado en las 84 peticiones warm fue 16,750 ms; no demuestra una consulta normal de 20 s ni un plan caro de producción. El JSON conserva ese máximo por petición y su distribución por escenario. Con muchos statements de baja duración, volumen × round-trip también consume tiempo. Los savepoints se incluyen en sql_count; no se llama a ese contador “SELECTs”. No se hicieron EXPLAIN ANALYZE, extensiones o cambios globales de BD.

## 10. H03: validación e inserción fiscal por línea

Sonda separada, cinco muestras/tamaño sobre PostgreSQL con Client y transacciones reales. Se temporiza full_clean por clase y save de documento/línea/desglose en memoria, sin alterar argumentos/retornos. save residual resta full_clean observado dentro de esa llamada: incluye preparación ORM/INSERT/FK/señales y no es tiempo puro de INSERT.

| Líneas | full_clean líneas ms | save líneas inclusivo ms | Residuo save sin full_clean ms | full_clean documento ms | full_clean serie ms |
|---|---:|---:|---:|---:|---:|
| 1 | 3.24 | 3.89 | 0.64 | 21.44 | 5.49 |
| 20 | 71.88 | 85.69 | 13.81 | 26.44 | 6.13 |
| 50 | 189.37 | 225.39 | 36.02 | 26.46 | 5.88 |

El crecimiento de Billing está confirmado; gran parte del guardado de hijos corresponde a validación de modelos con consultas, no solo inserciones. Snapshots, clasificación fiscal, validación de documento, serie/numeración y auditoría tienen costes separados en las trazas. No se omite full_clean ni se altera numeración; bulk sería un cambio de garantías, no una optimización automáticamente segura.

## 11. Locks y carreras sobre PostgreSQL real

Bloqueo artificial: otra conexión retiene exactamente el objeto de prueba; se inicia checkout, se espera ver Lock + PID bloqueador en pg_stat_activity y solo entonces se añade una retención conocida de 250 ms. El tiempo execute es compuesto y el muestreo no da una duración exacta pura de lock.

| Recurso | Retención adicional ms | Mayor execute FOR UPDATE ms | Petición Client ms | PID solicitante ← bloqueador | wait_event |
|---|---:|---:|---:|---|---|
| L01_Sale | 250.15 | 274.01 | 600.33 | 287 ← [286] | transactionid |
| L02_CashSession | 250.11 | 259.96 | 569.71 | 289 ← [288] | transactionid |
| L03_InventoryItem | 250.11 | 268.55 | 655.95 | 291 ← [290] | transactionid |
| L04_BillingSeries | 250.13 | 262.93 | 592.88 | 293 ← [292] | transactionid |

En todos los controles se terminó con un Payment, un documento y una salida de stock. Los bloqueadores y PID de driver/traza están guardados; no se exportó texto SQL del servidor.

Carreras naturales de dos conexiones, tres fixtures por caso; tiempo incluye toda operación. Número de observaciones no equivale a número de locks ni milisegundos de espera (muestreo ~20 ms).

| Caso | Configuración | Repeticiones | Operaciones min–max ms | Observaciones Lock | Resultados |
|---|---|---:|---:|---:|---|
| C01 | Misma Sale, dos usuarios y claves diferentes | 3 | 307.70–511.48 | 20 | 200 |
| C02 | Dos ventas, última unidad y cajas distintas | 3 | 212.99–494.25 | 3 | 200, 422 |
| C03 | Ventas/cajas distintas, misma serie y producto | 3 | 390.21–581.43 | 5 | 200 |
| C04 | Checkout contra cierre concurrente de caja | 3 | 78.04–133.65 | 0 | 409, closed |
| C05 | Dos checkouts split sobre la misma Sale | 3 | 346.33–539.51 | 30 | 200 |
| C06 | Dos ventas, misma CashSession | 3 | 441.95–592.65 | 26 | 200 |
| C07 | Ventas/cajas/series diferentes, mismo producto | 3 | 468.69–579.91 | 4 | 200 |

C01/C05: un único resultado económico, dos partes en split; C02: una venta gana la última unidad y otra recibe 422 sin saldo negativo; C03/C06/C07: ambas ventas emitidas, saldos coherentes. En las carreras C04 ganó cierre antes del cobro (409); no demuestra por sí solo el interleaving entre T1 y T2, por eso se añadió la prueba siguiente. No se observó deadlock ni se capturó SQLSTATE 40P01; no se afirma su imposibilidad.

Los tiempos de transacciones y execute de locks por participante están en traces. C03/C07 también comparten producto; no aíslan causalmente solo BillingSeries. El control L04 sí prueba que un bloqueo de esa serie puede demorar la emisión. El uso de select_related sin of en algunos locks puede abarcar filas relacionadas; no se deduce de wait_event=transactionid el conjunto exacto de filas bloqueadas.

## 12. Fronteras T1/T2/T3, recuperación y H01

| Fallo inyectado | HTTP | Sale/payment tras error | Payments | StockMovements | Documentos | HTTP reintento |
|---|---:|---|---:|---:|---:|---:|
| F01_before_T1 | 422 | open/unpaid | 0 | 0 | 0 | 200 |
| F02_inventory | 422 | open/unpaid | 0 | 0 | 0 | 200 |
| F03_after_T1 | 422 | completed/unpaid | 0 | 1 | 0 | 200 |
| F04_during_payment | 422 | completed/unpaid | 0 | 1 | 0 | 200 |
| F05_after_T2 | 200 | completed/paid | 1 | 1 | 0 | 200 |
| F06_during_billing | 200 | completed/paid | 1 | 1 | 0 | 200 |
| F07_after_T3_render | 500 | completed/paid | 1 | 1 | 1 | 200 |

Cada fila usa fixtures nuevas y después reintenta el mismo cuerpo. F02 lanza error después de crear movimiento dentro de T1: revierte toda salida. F04 falla tras efecto de cash dentro de Payment: T2 revierte. F06 falla después de asignar número dentro de T3: documento/hijos/número se revierten. F07 lanza RuntimeError al construir _render después de T3: la respuesta es 500 pero queda documento emitido, y replay no duplica nada. Se prueba fallo del punto de render, no un defecto de una plantilla fiscal concreta.

H01 sigue reproducido en PostgreSQL sin transacción exterior TestCase: paid sin documento + desactivar método → HTTP 422, sin field-error visible y sin documento; GET nuevo + emisión → 200, un Payment y un documento. El test conserva el escenario de A y añade medición. No se modificó formulario.

Cierre colocado exactamente después de T1 y antes de T2: Sale completed/unpaid, una salida de stock, cero pagos/documentos, caja closed; checkout y su repetición devuelven 409. No se puede editar su sesión mediante el formulario de Sale completada. Se verificó una **ruta existente alternativa**, register_sale_payment con una sesión nueva abierta (mismo negocio/tienda), y luego checkout para emitir: un Payment/documento/stock, sin duplicación. Esto demuestra recuperación a nivel de servicios; no valida que el cajero encuentre esa ruta en UX. El documento mantiene contexto histórico de Sale y Payment referencia la nueva sesión: Bloque C debe revisar visibilidad/operación de esa divergencia, sin reescribir historia silenciosamente.

## 13. Infraestructura: qué se sabe y qué no

`render.yaml` declara runtime Python, plan free y arranque `uv run gunicorn ... --bind ...`, sin workers/threads explícitos. Defaults locales y presencia de WEB_CONCURRENCY/GUNICORN_CMD_ARGS están etiquetados en runtime.json; no equivalen a procesos efectivos Render. build.sh y docker-entrypoint.sh incluyen migraciones, por eso **no se ejecutaron**. docker-compose tiene un volumen persistente y lee .env, por eso no se usó para el aislamiento.

Base configura conn_max_age=600 y ssl_require=False; production configura redirección SSL y cookies seguras, proxy header y almacenamiento de medios. Middleware incluye WhiteNoise, sesión, HTMX, CSRF, auth y adaptación login. Assets se sirven localmente en el arnés, sin simular CDN, logo remoto ni TLS. No se conoce la configuración efectiva de SSL/pooler, CPU/RAM/cola/worker del despliegue. No se instalaron plugins ni se accedió a Render.

HTTP−Django es residuo combinado (transporte local, servidor, serialización y medición), **no red pura ni cola de workers**. El hook pre_request empieza tras asignar worker; falta timestamp edge/upstream correlacionado para cola previa. Sin estos datos no se puede explicar el caso productivo.

Hubo un intento del arnés que agotó readiness 20 s antes de medir: master Gunicorn registró escucha sin “Booting worker”, y se limpió un proceso hijo. Las ejecuciones finales usan --no-control-socket y grupo de procesos propio para limpiar master/worker. No se presenta ese fallo de arranque del arnés como síntoma del checkout ni se afirma causalidad interna del control socket.

## 14. Causas confirmadas, hipótesis y alcance

- CONFIRMADO local: trabajo por línea en Inventory y Billing; coste de full_clean; state/options/relecturas; contención observada; T1/T2/T3 independientes; H01 y ausencia de feedback de timeout; error de render posterior a commits con recuperación idempotente en pruebas.
- DESCARTADO EN EL ENTORNO PROBADO: una demora natural de 20 s en estas 84 muestras warm; duplicación económica/documental en C01–C07 y fallos probados. Esto no descarta otros interleavings, red o despliegues.
- HIPÓTESIS: espera productiva por locks/cola de worker/pooler/WAN/arranque, o error fiscal concreto tras espera. La pausa artificial no identifica cuál.
- NO EVALUABLE aquí: causa temporal de la grabación original, cold start y p95 productivo, configuración y saturación Render, impresora física y diversidad de dispositivos reales.

Ver severidad/evidencia/propuesta de cada hallazgo en findings.md.

## 15. Validación y fidelidad de las mediciones

| Ejecución final | Tests | Segundos | Resultado |
|---|---:|---:|---|
| matrix-final | 1 | 214.26 | OK |
| cases-final | 5 | 34.348 | OK |
| frontend-final | 1 | 36.492 | OK |
| overhead-final | 1 | 30.074 | OK |
| regression | 728 | 120.103 | OK |
| fiscal-counter-final | 1 | 13.026 | OK |

Ruff check y format --check: OK; node --check del observador: OK; Django check: sin incidencias; makemigrations --check --dry-run: No changes detected. El contador de llamadas de la sonda fiscal se corrigió únicamente en el harness y se volvió a ejecutar esa sonda (fiscal-counter-final); no cambia el código económico ni la matriz HTTP. Los 7 tests unitarios de los recolectores verifican privacidad, contabilidad anidada, limpieza de contexto y desactivación. Las suites económicas se ejecutan con el diagnóstico desactivado en la misma PostgreSQL desechable, nunca SQLite para inferir locks.

Los logs 409/422/500 esperados en fallos no son fallos del runner. Se conservan v1 y el intento de readiness únicamente en scratch para trazabilidad, fuera de las muestras finales. No se declara un p95 con n=7. Las estadísticas no combinan cold/warm ni Client/HTTP ni v1/v2.

## 16. Recomendaciones priorizadas y preparación beta

1. **Recuperación operativa:** corregir H01 y el feedback htmx:timeout/abort; mantener identidad económica y lectura autoritativa antes de repetir. Dar una ruta visible para completed/unpaid con sesión cerrada y para paid/documento pendiente. No resolverlo aumentando plazos o generando nuevos UUID.
2. **Errores posteriores a commit:** manejar/presentar resultado desconocido y permitir GET de recuperación del estado/documento ya emitido. Cubrir TemplateError real y pérdidas después de cada commit con servidor vivo.
3. **Captura real controlada:** obtener SHA y configuración efectiva del despliegue y traza del caso lento con timestamp de edge, stages y PID; sin cobros reales ni benchmark de producción. El detalle tiene overhead y no debe activarse permanentemente.
4. **Rendimiento con evidencia:** priorizar coste por línea y validaciones que este diagnóstico sitúa en Inventory/Billing; después relecturas de respuesta. Diseñar equivalencia semántica y pruebas antes de optimizar, conservando locks, snapshots, save/full_clean, numeración y auditoría.

**Beta: evidencia insuficiente para decidir.** El entorno sintético supera invariantes y recuperación ensayadas, pero hay defectos operativos reproducidos, muestra limitada y falta evidencia de infraestructura/red/operación real. No se certifica una beta con negocios reales ni se afirma que los datos prueben pérdida económica. Resolver los bloqueos UX y ensayar staging y procedimientos de recuperación es un gate recomendado.

## 17. Bloque C propuesto: transacciones, idempotencia y recuperación

- Mantener fronteras durables explícitas T1/T2/T3 y un estado reconstruible por GET. No envolver todo en atomic ni introducir compensación fiscal automática sin diseño revisado.
- Separar intención histórica confirmada de validación de pago nuevo en recuperación de emisión; conservar autorización actual, fingerprint Billing, UUID de cada parte y comparación de identidad. Probar método desactivado, split parcial, serie cambiada y claves repetidas/distintas.
- Diseñar recuperación de completed/unpaid con caja cerrada: mostrar qué efecto ya existe, qué sesión recibe el pago y dónde queda el documento; utilizar contratos actuales o un servicio explícito revisado, sin editar documentos ni stock histórico.
- Manejar sendError, timeout y abort de POST como resultado potencialmente desconocido; restaurar processing, ofrecer consulta de estado y evitar nuevos pagos implícitos.
- Mantener lock Sale antes de saldo/estado/documento y lock serie en numeración. Inventariar writers externos a estos servicios; probar dos pestañas HTTP con versiones/keys distintas y barreras entre commits.
- Optimización posterior separada: aprovechar respuesta de orquestación/consultas ya materializadas si es consistente; perfilar validación por línea y operaciones SQL agrupadas. Sin omitir garantías por reducir contador de queries.

Pruebas pendientes: staging con configuración efectiva, cold/warm separados y más muestras para colas; transporte con interrupción exactamente post-T1/post-cada-T2/post-T3, timeout con operación externa de pago simulada, cierres y recuperaciones en UI real, drivers de impresión y matriz de dispositivos. Las carreras aquí cubren dos participantes y no una carga sostenida.

## 18. Reproducción, evidencias y cierre

Crear un contenedor nuevo sin volúmenes y publicar solo loopback; verificar docker inspect/pg_isready y usar el guard de puerto/host. No ejecutar estos settings en una base compartida. Variables de prueba sin credenciales reales:

```bash
export TPV_TEST_DATABASE_URL=postgresql://postgres@127.0.0.1:55437/tpv_diag_phase3
export DJANGO_SETTINGS_MODULE=config.settings.diagnostic_phase3
export TPV_DIAGNOSTICS=1
export TPV_PHASE3_DIAGNOSTICS=1
export TPV_PHASE3_SAMPLES=7
export TPV_DIAGNOSTIC_OUTPUT=/workspace/work/phase3-b/matrix
.venv/bin/python manage.py test tests.performance.phase3_harness.BrowserMeasurements --noinput
```

Ejecutar secuencialmente, cambiando OUTPUT a cases/frontend/overhead: `phase3_cases.BoundaryCases`, `BetweenTransactions`, `FiscalModelCosts`, `phase3_frontend.FrontendBoundaries`, `phase3_cases.CollectionOverhead`. Módulos pertenecen a `tests.performance`. Para las suites de regresión, ambos flags en 0. Generar JSON con `python -m tests.performance.phase3_summary --root /workspace/work/phase3-b --output docs/performance/tpv-phase3-block-b-measurements.json`.

Evidencia primaria: JSON (muestras, transacciones, locks, estados, queries agregadas, fixtures comprobadas, overhead y runtime) y código diagnóstico versionable. Scratch local: `/workspace/work/phase3-b`, trazas/logs sin publicar. Cierre verificado: cero conexiones cliente ajenas al lector de comprobación y cero bases test antes de retirar el contenedor; contenedor eliminado y cero procesos Gunicorn del arnés. El worker huérfano del intento fallido de readiness requirió SIGKILL al cerrar la sesión. No queda servidor de pruebas abierto. El informe final del chat confirma estado Git y limpieza reales; no se realiza push.


Referencias de código para contrastar los hallazgos:

| Hallazgo / medida | Implementación inspeccionada | Prueba / observador añadido |
|---|---|---|
| H01 y validación del método antes de emitir | `apps/sales/views.py:1397`, `apps/sales/views.py:1533`, `apps/sales/forms.py:43`, `templates/sales/partials/_checkout.html:50` y `:69` | `tests/performance/phase3_cases.py`, BoundaryCases.test_failures_and_h01 |
| H02 recálculo y relecturas | `apps/sales/services.py:697`, `:1066`; `apps/sales/checkout.py:68`; `apps/sales/views.py:1650` | phase3_trace.measured, detail_stages y state/options |
| H03 validaciones fiscales por hijo | `apps/billing/services.py:498`, `apps/billing/models.py:596` | phase3_cases.FiscalModelCosts.test_model_validation_and_save_costs |
| H04 transacciones y fiscalidad tardía | `apps/sales/checkout.py:230`, `:274`, `:307`; `apps/billing/services.py:365` y `:722` | phase3_cases.BoundaryCases; transactions del JSON |
| Timeout y resultado desconocido | `static/js/core/htmx-events.js:77`, `:86`, `:110`; `static/vendor/htmx/1.9.12/htmx.min.js:1` | phase3_frontend.FrontendBoundaries, caso timeout; phase3-browser.js |
| Caja cerrada entre commits | `apps/sales/services.py:612`, `apps/sales/views.py:676`, `apps/payments/services.py:118` y `:285` | phase3_cases.BetweenTransactions.test_cash_close_exactly_after_t1 |
| Render fuera de transacciones | `apps/sales/views.py:1650` | phase3_cases.BoundaryCases, F07_after_T3_render |
| Locks correlacionados | `tests/performance/diagnostic_locks.py:16`; select_for_update de los servicios auditados en A | phase3_cases.BoundaryCases.test_controlled_locks/test_contention |

Las referencias abreviadas `:línea` corresponden al archivo inmediatamente anterior. Ninguna inferencia de rendimiento sustituye estas pruebas ni los límites de instrumentación descritos.
