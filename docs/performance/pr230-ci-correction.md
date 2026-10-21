# PR #230: corrección de CI del carrito optimista

## Alcance y evidencia

Repositorio `daniilabradorr/sala-tpv`, rama `feat/tpv-optimistic-cart`, destino `develop`.
Se investigó `1834c43` y se descargaron los logs completos del job
`browser-e2e` (119234083294) de la [ejecución original 39603618984](https://github.com/daniilabradorr/sala-tpv/actions/runs/39603618984).
Los 51 resultados adversos se enumeran individualmente en
[pr230-ci-failures.md](pr230-ci-failures.md). No corresponden a 51 defectos independientes.

| Grupo | Resultados originales | Causa |
| --- | ---: | --- |
| A | 40 errors | El arnés intercepta los assets con hash y devuelve 404 antes de WhiteNoise. |
| B | 10 failures | `flush()` no espera la lectura inicial que habilita el protocolo del carrito. |
| C | 1 failure | `3 != 4`: resultado agregado tras fallar uno de los cuatro subtests de B. |

## A: servidor estático del arnés

`config.settings.test` hereda `CompressedManifestStaticFilesStorage` y WhiteNoise
con `DEBUG=False`. CI ejecuta `collectstatic` antes de los tests. Las plantillas
producen URLs como `/static/js/sales_cart.946d8e34ff4b.js`.
`StaticLiveServerTestCase` antepone `StaticFilesHandler`, que consulta los
*finders* de los directorios fuente. No encuentra el nombre con hash y devuelve
404; la petición no llega a WhiteNoise y a `STATIC_ROOT`.

Se reprodujo localmente con los mismos settings y PostgreSQL: 404 para
`sales_cart`, `sales_tpv`, `app.js`, HTMX y CSS; tanto `tpvCart` como
`SalesCartQueue` sin definir, raíz del carrito presente, almacenamiento vacío,
cookie CSRF presente y ninguna petición cart-sync. El timeout de 30 segundos es
una consecuencia; aumentarlo no permite inicializar JavaScript ausente.

El arnés base de optimistic/hardening usa ahora `StaticFilesStorage`, como las
otras suites que prueban fuentes mediante `StaticLiveServerTestCase`.
Además, `CollectedCartAssetsBrowserTests` usa `LiveServerTestCase` sin handler
estático interceptador: prueba las URLs con hash y el WSGI/WhiteNoise real,
inicializa protocolo, guarda un producto y obtiene el formulario de checkout.
Así se conserva cobertura explícita de `collectstatic` y Manifest en CI.
La configuración de aplicación, WhiteNoise y CI no se altera.

Las mediciones locales anteriores usaban `diagnostic_postgres`, que sustituye
el storage por `StaticFilesStorage`: no reproducían esta combinación de CI.
Para esta corrección se usó `config.settings.test`, `DEBUG=0` y `collectstatic`.

## B: carrera entre arranque y checkout

La cola publica el estado visual antes de terminar el GET inicial de cart-sync.
Mientras `protocolReady=false`, `pump()` bloquea correctamente las mutaciones.
Pero `flush()` veía `busy=false`, intentaba `pump()`, encontraba las operaciones
aún pendientes y rechazaba el checkout. El diálogo mostraba el error y no el
encabezado esperado. Que el GET terminase después no reiniciaba ese intento.

Se añadió una regresión que retiene deliberadamente el GET inicial: añade un
producto y abre checkout durante esa retención. Antes de la corrección fallaba
al esperar el estado de carga. Ahora conserva el diálogo de carga sin formulario
de pago y, al liberar la lectura, persiste la intención y obtiene el formulario
con la cola vacía.

La aplicación conserva la promesa de inicialización y `flush()` espera esa misma
lectura dentro del plazo existente y con la señal de cancelación del intento.
Después aplica los mismos controles de cabecera, vaciado, errores y lectura
confirmada. No introduce lecturas iniciales duplicadas ni amplía timeouts.
Una lectura fallida o un protocolo/usuario incompatible siguen bloqueando cobro.
Cerrar el diálogo cancela la espera local; no descarta ni duplica mutaciones.

Se mantienen UUID, recibos, namespaces de sessionStorage, protocolo versión 2,
versionado monotónico, CSRF, permisos y headers. No cambian el backend de cobro,
Payments, Billing, Inventory ni reglas fiscales.

## C: discrepancia 3 != 4

`test_cash_blank_insufficient_change_and_small_viewports` tiene cuatro subtests.
El primero (1440×900, entregado vacío) falla al abrir checkout en la ejecución
original. `subTest` permite continuar; los otros tres completan sus pagos
sintéticos. La aserción final de cuatro pagos recibe tres. No se cambia a tres ni
se elimina: los cuatro escenarios y la aserción original pasan tras la corrección.

## Diagnósticos de futuras ejecuciones

`e2e/browser_evidence.py` conserva los últimos 200 eventos: errores de consola,
pageerror, solicitudes fallidas, HTTP 4xx/5xx, respuestas cart-sync, estado del
protocolo/cola/cabecera/modal y flags de cookies. Guarda JSON en `artifacts/e2e/`,
ya recogido por el paso de artifacts de CI. Captura fallos de setUp, optimistic /
hardening y apertura de checkout. No guarda valores de cookies, cuerpos HTTP,
contenido de sessionStorage ni datos completos de pagos; usa datos sintéticos.

## Reproducción

Requiere Python 3.12 y PostgreSQL local o desechable. No utilizar una URL de
producción: Django crea y elimina una base `test_*`.

```bash
uv sync --dev
export DJANGO_SETTINGS_MODULE=config.settings.test
export SECRET_KEY=local-test-only
export DEBUG=0
export ALLOWED_HOSTS=127.0.0.1,localhost
export DATABASE_URL='postgresql://USER:PASSWORD@127.0.0.1:PORT/DATABASE'
uv run python manage.py collectstatic --noinput
uv run playwright install --with-deps chromium

# Mismos 25 módulos browser que CI (incluye las nuevas regresiones):
mapfile -t browser_labels < <(sed -n 's/^          \(e2e\.browser_[a-z_]*\)$/\1/p' .github/workflows/ci.yml)
uv run python manage.py test "${browser_labels[@]}" --noinput --verbosity 2

uv run python manage.py test --noinput
uv run python manage.py test \
  apps.sales.tests_postgres_locking apps.sales.tests_postgres_checkout \
  apps.sales.tests_postgres_cart apps.payments.tests_postgres_locking \
  apps.purchases.tests_postgres_locking apps.billing.tests_concurrency \
  apps.cash_register.tests.integration.test_concurrency \
  tests.performance.test_queries tests.performance.test_metrics --noinput
uv run ruff check .
uv run ruff format --check .
uv run python manage.py check
uv run python manage.py makemigrations --check --dry-run
```

## Validación de la corrección

Entorno local: Python 3.12.12, Django 5.2.12, PostgreSQL 16 y Chromium del
sistema. Settings `config.settings.test`, `DEBUG=0` y `collectstatic`; únicamente
datos sintéticos. El launcher local selecciona `/usr/bin/chromium`; CI usa el
Chromium instalado por Playwright. La ejecución remota es la validación del
entorno exacto de GitHub Actions.

| Comprobación local | Resultado |
| --- | --- |
| Suite completa Django sobre PostgreSQL | 1613 tests, OK (269,592 s) |
| Regresiones: lectura inicial retenida + Manifest/WhiteNoise | 2 tests, OK |
| Checkout completo | Los 16 tests existentes pasan tras la corrección |
| Ruff | OK |
| Formato | OK; se excluye únicamente `work/`, material local no versionado |
| Django check | 0 problemas |
| Migraciones | No changes detected |
| Sintaxis JavaScript (`node --check`) | OK |

La suite completa browser y los grupos de concurrencia se ejecutan con los
comandos anteriores. Los resultados finales y enlaces de ejecución se entregan
en el informe de corrección y pueden verificarse en los
[checks de la PR #230](https://github.com/daniilabradorr/sala-tpv/pull/230/checks).
El criterio de aceptación es que todos los jobs obligatorios estén en verde.
