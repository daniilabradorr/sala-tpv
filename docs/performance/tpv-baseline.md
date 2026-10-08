# TPV — Fase 6: baseline antes de optimizar

Medición de la aplicación de Fases 1–5; no se han cambiado vistas, selectors, services, forms, modelos, índices, cachés, templates ni JavaScript de producción. Los cambios son herramientas de test, regresiones, resultados/documentación y la inclusión de esas regresiones en el gate PostgreSQL existente.

## Base, entorno y alcance

- Base real de `develop`: `ecf4e43e5e9cbfc3561e4f088453bfeffae7cba2`, actualizado con `git fetch`.
- PR #225 fusionada: merge en ese mismo SHA. Historial comprobado: #222 (Fase 1), #223 (Fase 2), #224 (Fases 3–4), #225 (Fase 5).
- Fecha: 2026-10-08 (Europe/Madrid).
- Python 3.12.12; Django 5.2.12; psycopg y Playwright del entorno del repositorio, sin nuevas dependencias.
- **DB de referencia: PostgreSQL 16**, concretamente 16.15 (Debian), imagen `postgres:16`. Base dedicada `tpv_baseline`; Django crea y destruye `test_tpv_baseline`.
- Entorno cloud Linux, 2 CPU de cuota y 8 GiB de límite de memoria; PostgreSQL local en Docker, un proceso de medición sin concurrencia ni pruebas simultáneas. Las cifras no representan capacidad bajo carga, red WAN, hardware de tienda ni PostgreSQL con catálogo de producción.
- Chromium local `/usr/bin/chromium`, headless, viewport 1440×900, una sesión autenticada y contexto de browser compartidos, animaciones normales. Versión exacta en JSON browser.

## Revisión del contrato actual

Se inspeccionaron `apps/sales/{views,selectors,services,forms,urls}.py`, Catalog (Product, Category, Tax y resolución fiscal), Business Config (POSSettings y helpers), Payments y Billing (selectors/services y opciones de checkout), los cinco templates requeridos, `sales_tpv.js`, `core/htmx-events.js`, los E2E TPV/checkout/full_flow, `ci.yml` y `pyproject.toml`.

| Operación | Lectura/escritura actual | Respuesta medida |
|---|---|---|
| `sale_detail` editable | `get_sale_detail`, `get_sellable_products_for_workspace`, Paginator(24), categorías, impuesto por producto y POSSettings | Full: `sale_workspace.html`; HTMX: `_product_grid.html` más chips OOB |
| `sale_header_update` POST | `get_sale_header`, `SaleHeaderUpdateForm`, `update_sale_header` | `_workspace_header.html` → `#workspace-header` |
| `sale_line_add` POST | `get_sale_detail`, `SaleLineCreateForm`, `add_sale_line`, relectura `get_sale_cart` | `_cart_content.html` → `#sale-cart-content` |
| `sale_line_quantity_update` POST | `get_sale_header`, `get_sale_cart_line`, `update_sale_line`, `get_sale_cart` | `_cart_content.html` → `#sale-cart-content` |
| `sale_line_update` GET/POST | `get_sale_header`, `get_sale_cart_line`, form por modo; POST `update_sale_line` | GET `_line_editor.html`; POST `_line_update_success.html` con cart OOB |
| `sale_line_delete` POST | `get_sale_detail`, `get_sale_line_detail`, `delete_sale_line`, `get_sale_cart` | `_cart_content.html` → `#sale-cart-content` |
| `sale_checkout` GET | `get_sale_detail`, `checkout_options`, `checkout_state`, Payments/Billing/POSSettings | `_checkout.html` → `#checkout-panel`; dialog visible por JS |
| Cart aislado | `get_sale_cart` + render real del template de snapshots | Lectura de selector/template, **no request HTTP** |

Para requests sin HX-Request existen respuestas full-page o redirects según el endpoint; las escrituras del baseline usan el contrato real HTMX. Un history restore de `sale_detail` devuelve full workspace. No se introduce ningún endpoint público.

## Dataset

Fixtures semánticamente deterministas, sin mocks: nombre/SKU/barcode de producto numerados, precio base 10 €, coste 4 €, tres categorías, IVA explícito 21/10 % y un tercio con fallback al IVA predeterminado. Cada producto controla stock y tiene InventoryItem real con 1.000 unidades; dos clientes ficticios activos, owner, Store, POSSettings, caja y sesión abierta, dos métodos (cash/card) y series F1/F2 del año local.

Catálogos de **50 → 250 → 1.000** productos en un tenant; crecen entre bloques sin materializar por adelantado el generador. Cada página sigue limitada a 24. Las operaciones restantes usan un segundo tenant con 250 productos, igual tamaño que browser. Tickets **0/1/5/20/50** líneas con snapshots e importes calculados por el helper existente. Inserts masivos solo en preparación de fixtures, fuera de la medición; ninguna optimización de aplicación. Cada escritura usa venta fresca por iteración, y se verifica el cambio persistido y la consistencia de totales fuera del intervalo medido. No hay ventas completadas reutilizadas ni datos reales.

## Metodología

- Por escenario: **1 primera medición independiente + 5 warmups descartados + 20 muestras warm**. Se conserva la primera medición y todas las muestras; no se escoge el mejor run.
- Server: Django `Client` autenticado, pipeline real de middleware/view/form/service/template, `DEBUG=False`, `HTTP_HX_REQUEST=true` en parciales. `time.perf_counter()` rodea únicamente la ejecución de request y materialización del body. Se excluyen fixture setup, login, verificaciones, resúmenes SQL y serialización del informe. **No incluye transporte HTTP, Gunicorn, proxy ni navegador.** Es un baseline in-process server-side reproducible, no una simulación de concurrencia.
- Queries: `CaptureQueriesContext`. El harness limpia el deque de queries antes de cada muestra y rechaza una captura vacía; evita truncamiento al superar las 9.000 entradas del log Django. Incluye consultas de autorización/tenant/sesión y sentencias de transacción visibles al capturador.
- SQL ms: wrapper local de `connection.execute_wrapper` con `perf_counter`; suma tiempo de ejecución/round trip del cursor. No es CPU de PostgreSQL, no mide fetch/ORM ni confirma el tiempo de commits ejecutados fuera del cursor. Instrumentación de test añade overhead y no debe confundirse con latencia sin profiling.
- Bytes: `len(response.content)`, HTML sin compresión. IDs de filas/sales varían entre iteraciones y pueden cambiar unos bytes; se reporta min–max. El cart de selector aislado carece de RequestContext/CSRF, por lo que sus bytes no sustituyen el tamaño de cart swap HTTP.
- p50: `statistics.median`, promedio de las dos muestras centrales cuando n es par. **p95 nearest rank**: ordenar y elegir `ceil(0.95*n)-1`; con n=20 es la muestra 19. Min y max también se conservan en JSON. No hay librería estadística ni assert de milisegundos.
- Primera medición **no equivale a cold start**: no se vacían buffers PostgreSQL, page cache OS ni caches del browser. El primer request del tenant también persiste la tienda activa en sesión; la fase warm ya tiene ese contexto.
- Browser: `performance.now()` desde input/click/change/keydown Enter capturado en la página, correlación del mismo XHR, respuesta → swap → `htmx:afterSettle` → primer animation frame con el estado esperado visible. Checkout termina cuando el dialog está abierto y el control de método visible/habilitado. Cada operación parte de workspace precargado con una venta fresca; se excluye `goto` y la creación de fixtures. Contexto/sesión/caché browser compartidos, página nueva por interacción para controlar el estado. Estas son interacciones con aplicación warm y UI preparada, no una medida cold ni ráfagas en el mismo ticket.
- `request_to_response_ms` de browser incluye transporte local y servidor; **no es** server duration ni se resta del total para estimar SQL. El desfase respuesta→settle y settle→estado visible son mediciones separadas; percentiles de componentes no son aditivos.
- La captura conserva únicamente fingerprints, operación, tablas y conteos; no se exportan SQL literales, HTML, cookies, contraseñas, tokens CSRF ni UUIDs de pago. Las consultas idénticas se distinguen de patrones normalizados: el mismo patrón no prueba duplicación innecesaria.

## Reproducción

Usar una instancia PostgreSQL 16 local y una base dedicada vacía; no apuntar a una base con datos reales. Instalar las dependencias existentes con `uv sync --dev`. El harness rechaza settings distintos de `config.settings.test`, SQLite y versiones distintas de PostgreSQL 16, y gestiona el ciclo de vida de la base de test mediante DiscoverRunner.

```bash
export DJANGO_SETTINGS_MODULE=config.settings.test
export SECRET_KEY=phase6-test
export DATABASE_URL=postgresql://postgres:postgres@127.0.0.1:5432/tpv_baseline
uv run python manage.py collectstatic --noinput
uv run python -m tests.performance.baseline --warmups 5 --iterations 20 \
  --output work/tpv-server.json
uv run playwright install chromium
uv run python -m tests.performance.baseline --browser --warmups 5 --iterations 20 \
  --output work/tpv-browser.json
# Alternativa local usada aquí: --chromium /usr/bin/chromium
uv run python manage.py test tests.performance.test_queries tests.performance.test_metrics
```

Los dos JSON versionados de esta ejecución permiten comparar Fase 7: `tpv-baseline-server.json` y `tpv-baseline-browser.json`. Schema v1 con SHA, versiones, escenario, método/endpoint anonimizado, tipo, templates, queries, bytes, distribuciones y muestras. Sin timestamps aleatorios. No se ejecuta el benchmark temporal en CI.

## Resultados

Run de referencia completo: **44 escenarios server**, 1144 invocaciones medidas (primera + warmups + muestras), **44.969 s** incluyendo setup de fixtures dentro del profiler y excluyendo creación/migración/destrucción de test DB. Browser: **7 escenarios**, 182 interacciones, **140.355 s** de bucle de medición/navegación, excluyendo preparación previa de fixtures y ciclo de vida de test DB. Chromium **151.0.7922.173**. Todos los status medidos: **200**.

Tiempos en ms; bytes min–max sin compresión. La fila `cart_read` mide selector/template, no un endpoint HTTP. UI N/A significa que ese escenario exacto no se midió en browser. La UI de añadir usa ticket de 5 líneas; no se atribuye a los POST server de 1/20 líneas.

| Escenario | Queries warm | Bytes | p50 server | p95 server | p50 UI | p95 UI |
|---|---:|---:|---:|---:|---:|---:|
| grid_50_all | 13 | 19609 | 28.31 | 32.66 | N/A | N/A |
| grid_50_search | 13 | 19635 | 27.19 | 30.58 | N/A | N/A |
| grid_50_search_exact | 12 | 1491 | 23.70 | 33.19 | N/A | N/A |
| grid_50_category | 14 | 13937 | 27.05 | 31.35 | N/A | N/A |
| grid_50_category_search | 14 | 13937 | 27.19 | 30.35 | N/A | N/A |
| grid_50_page_2 | 13 | 19737 | 27.44 | 31.17 | N/A | N/A |
| grid_250_all | 13 | 19610 | 31.69 | 37.50 | N/A | N/A |
| grid_250_search | 13 | 19635 | 29.65 | 39.44 | N/A | N/A |
| grid_250_search_exact | 12 | 1491 | 24.91 | 26.42 | 354.80 | 377.10 |
| grid_250_category | 14 | 19618 | 29.33 | 32.31 | N/A | N/A |
| grid_250_category_search | 14 | 19644 | 34.54 | 41.63 | N/A | N/A |
| grid_250_page_2 | 13 | 19738 | 32.49 | 39.60 | N/A | N/A |
| grid_1000_all | 13 | 19610 | 35.94 | 41.41 | N/A | N/A |
| grid_1000_search | 13 | 19635 | 34.23 | 40.03 | N/A | N/A |
| grid_1000_search_exact | 12 | 1491 | 25.11 | 29.30 | N/A | N/A |
| grid_1000_category | 14 | 19619 | 27.67 | 32.31 | N/A | N/A |
| grid_1000_category_search | 14 | 19644 | 28.25 | 32.72 | N/A | N/A |
| grid_1000_page_2 | 13 | 19738 | 32.22 | 56.32 | N/A | N/A |
| workspace_0_lines | 14 | 48770 | 36.20 | 49.61 | N/A | N/A |
| workspace_1_lines | 14 | 50844 | 39.34 | 88.50 | N/A | N/A |
| cart_read_1_lines | 2 | 2823 | 2.38 | 3.15 | N/A | N/A |
| workspace_5_lines | 14 | 58917 | 40.66 | 53.80 | N/A | N/A |
| cart_read_5_lines | 2 | 9928 | 3.79 | 4.67 | N/A | N/A |
| workspace_20_lines | 14 | 89299 | 42.96 | 48.85 | N/A | N/A |
| cart_read_20_lines | 2 | 36678 | 8.08 | 9.22 | N/A | N/A |
| workspace_50_lines | 14 | 149989 | 54.77 | 66.17 | N/A | N/A |
| cart_read_50_lines | 2 | 90108 | 17.11 | 20.90 | N/A | N/A |
| checkout_get_1_lines | 18 | 7287 | 35.28 | 39.84 | 101.45 | 134.00 |
| checkout_get_20_lines | 18 | 7292 | 38.20 | 43.17 | 106.75 | 126.10 |
| header_ticket_to_invoice | 38 | 1862 | 28.95 | 30.75 | 112.05 | 143.50 |
| header_invoice_to_ticket | 38 | 1723 | 29.59 | 31.64 | N/A | N/A |
| header_customer_none_to_customer | 40 | 1723 | 30.61 | 35.93 | N/A | N/A |
| header_customer_to_other | 40 | 1723–1726 | 30.49 | 33.91 | N/A | N/A |
| add_product_1_lines | 68 | 5161 | 54.89 | 60.05 | N/A | N/A |
| delete_line_1_lines | 48 | 998 | 45.39 | 46.73 | N/A | N/A |
| add_product_20_lines | 68 | 44097–44307 | 62.00 | 64.58 | N/A | N/A |
| delete_line_20_lines | 48 | 40189 | 54.62 | 57.95 | N/A | N/A |
| quantity_1_to_2 | 66 | 11359 | 45.28 | 52.29 | 116.95 | 143.80 |
| quantity_2_to_1 | 66 | 11361 | 44.10 | 45.76 | N/A | N/A |
| quantity_1_to_1.5 | 66 | 11361 | 41.77 | 45.32 | 130.10 | 161.10 |
| editor_discount_get | 8 | 1596 | 7.90 | 10.16 | N/A | N/A |
| editor_discount_post | 67 | 11476 | 43.02 | 44.72 | N/A | N/A |
| editor_price_get | 8 | 1532 | 8.09 | 8.61 | N/A | N/A |
| editor_price_post | 67 | 11383 | 43.74 | 49.21 | N/A | N/A |
| browser_add_5_lines | N/A | N/A | N/A | N/A | 171.65 | 220.30 |

### Distribuciones y SQL acumulado

Todas las muestras y las primeras mediciones están en JSON. Este desglose conserva también los outliers; el p95 no sustituye al máximo. SQL es suma de ejecución del cursor, no duración total de la request.

| Escenario | min server | max server | p50 SQL | p95 SQL | Primera request: queries / ms |
|---|---:|---:|---:|---:|---:|
| grid_50_all | 25.59 | 83.61 | 12.64 | 13.61 | 16 / 74.23 |
| grid_50_search | 25.07 | 31.46 | 11.66 | 13.95 | 13 / 27.84 |
| grid_50_search_exact | 21.13 | 35.38 | 12.01 | 14.50 | 12 / 22.13 |
| grid_50_category | 25.46 | 31.88 | 12.44 | 13.36 | 14 / 24.41 |
| grid_50_category_search | 25.33 | 30.50 | 12.43 | 13.60 | 14 / 27.96 |
| grid_50_page_2 | 24.80 | 35.32 | 12.38 | 14.62 | 13 / 29.77 |
| grid_250_all | 28.18 | 85.15 | 14.30 | 16.75 | 13 / 30.07 |
| grid_250_search | 26.59 | 42.73 | 13.36 | 15.49 | 13 / 30.54 |
| grid_250_search_exact | 23.67 | 26.89 | 12.48 | 13.70 | 12 / 24.75 |
| grid_250_category | 27.49 | 32.85 | 12.98 | 14.50 | 14 / 29.21 |
| grid_250_category_search | 29.02 | 50.22 | 14.44 | 18.91 | 14 / 32.30 |
| grid_250_page_2 | 28.26 | 44.26 | 14.10 | 18.59 | 13 / 30.16 |
| grid_1000_all | 31.46 | 115.19 | 17.38 | 22.52 | 13 / 42.09 |
| grid_1000_search | 27.37 | 53.97 | 15.71 | 17.85 | 13 / 36.13 |
| grid_1000_search_exact | 24.06 | 36.22 | 13.48 | 14.89 | 12 / 23.75 |
| grid_1000_category | 25.41 | 32.54 | 12.04 | 14.00 | 14 / 30.53 |
| grid_1000_category_search | 25.82 | 33.46 | 12.69 | 15.10 | 14 / 27.47 |
| grid_1000_page_2 | 28.34 | 83.05 | 15.28 | 28.29 | 13 / 35.57 |
| workspace_0_lines | 33.05 | 101.47 | 14.12 | 22.13 | 17 / 89.76 |
| workspace_1_lines | 33.88 | 89.84 | 14.97 | 29.47 | 14 / 33.55 |
| cart_read_1_lines | 2.06 | 4.10 | 0.70 | 1.32 | 2 / 2.72 |
| workspace_5_lines | 33.82 | 62.18 | 15.07 | 20.13 | 14 / 38.60 |
| cart_read_5_lines | 3.43 | 5.33 | 0.78 | 0.97 | 2 / 5.37 |
| workspace_20_lines | 38.61 | 52.57 | 14.42 | 16.02 | 14 / 55.98 |
| cart_read_20_lines | 6.99 | 9.79 | 0.86 | 0.96 | 2 / 9.74 |
| workspace_50_lines | 50.78 | 70.49 | 15.56 | 17.93 | 14 / 53.80 |
| cart_read_50_lines | 14.31 | 21.03 | 1.18 | 2.20 | 2 / 16.12 |
| checkout_get_1_lines | 31.62 | 116.72 | 16.51 | 17.36 | 18 / 39.53 |
| checkout_get_20_lines | 35.68 | 43.56 | 16.84 | 18.60 | 18 / 37.34 |
| header_ticket_to_invoice | 25.10 | 30.85 | 13.79 | 14.38 | 38 / 28.92 |
| header_invoice_to_ticket | 25.88 | 56.46 | 14.23 | 15.14 | 38 / 28.76 |
| header_customer_none_to_customer | 27.90 | 38.26 | 14.76 | 19.57 | 40 / 30.60 |
| header_customer_to_other | 27.41 | 41.92 | 14.69 | 16.71 | 40 / 30.99 |
| add_product_1_lines | 51.49 | 60.76 | 27.46 | 31.47 | 68 / 79.10 |
| delete_line_1_lines | 44.42 | 47.42 | 23.86 | 24.85 | 48 / 51.92 |
| add_product_20_lines | 58.05 | 64.72 | 28.39 | 30.13 | 68 / 65.57 |
| delete_line_20_lines | 51.28 | 58.82 | 25.62 | 26.96 | 48 / 62.48 |
| quantity_1_to_2 | 40.63 | 64.01 | 21.19 | 24.98 | 66 / 42.06 |
| quantity_2_to_1 | 42.74 | 46.83 | 20.86 | 21.63 | 66 / 45.22 |
| quantity_1_to_1.5 | 37.19 | 46.65 | 19.21 | 22.63 | 66 / 44.32 |
| editor_discount_get | 7.31 | 77.92 | 2.72 | 3.69 | 8 / 10.64 |
| editor_discount_post | 39.13 | 45.24 | 19.90 | 21.14 | 67 / 38.71 |
| editor_price_get | 7.37 | 8.62 | 2.93 | 3.13 | 8 / 8.43 |
| editor_price_post | 37.91 | 56.09 | 19.31 | 22.43 | 67 / 45.41 |

### Browser: componentes de latencia

| Interacción | min UI | p50 UI | p95 UI | max UI | p50 evento→request | p50 request→response | p50 response→settle | p50 settle→visible |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| search | 339.60 | 354.80 | 377.10 | 413.10 | 277.70 | 42.40 | 20.90 | 12.05 |
| add | 140.00 | 171.65 | 220.30 | 230.70 | 3.85 | 131.40 | 23.75 | 6.35 |
| quantity_plus | 108.10 | 116.95 | 143.80 | 145.60 | 3.95 | 84.20 | 22.30 | 4.90 |
| quantity_enter | 104.80 | 130.10 | 161.10 | 186.30 | 3.60 | 95.40 | 22.55 | 5.50 |
| header | 87.20 | 112.05 | 143.50 | 244.60 | 2.45 | 79.20 | 20.90 | 10.25 |
| checkout_1 | 85.30 | 101.45 | 134.00 | 138.60 | 2.40 | 68.10 | 21.10 | 8.05 |
| checkout_20 | 89.70 | 106.75 | 126.10 | 139.10 | 1.80 | 75.90 | 21.20 | 6.45 |

### Consultas únicas, repetidas y top 3 patrones

Un patrón normalizado puede agrupar comprobaciones distintas con valores diferentes. Los checks sin FROM son evaluaciones de constraints por `full_clean`, no consultas idénticas que puedan eliminarse sin analizar su semántica. Top 3 para escenarios importantes; cuando cada patrón aparece una vez no se detectan repetidos. Fingerprints completos y resumen de todos los escenarios están en el JSON.

| Escenario | Total | Únicas exactas | Repeticiones exactas | Patrones únicos | Repeticiones de patrón | Top 3: patrón / apariciones |
|---|---:|---:|---:|---:|---:|---|
| grid_1000_all | 13 | 13 | 0 | 13 | 0 | SELECT django_session ×1 (`c51e4ea6f50b`); SELECT users_customuser ×1 (`17bed91a026f`); SELECT stores_store ×1 (`7fd8a6498e80`) |
| workspace_20_lines | 14 | 14 | 0 | 14 | 0 | SELECT django_session ×1 (`c51e4ea6f50b`); SELECT users_customuser ×1 (`17bed91a026f`); SELECT stores_store ×1 (`7fd8a6498e80`) |
| header_ticket_to_invoice | 38 | 36 | 2 | 33 | 5 | SELECT checks sin FROM ×5 (`7e9b92dc96aa`); SELECT customers_customer+sales_sale ×2 (`d8b2d15159e5`); SELECT django_session ×1 (`c51e4ea6f50b`) |
| header_customer_to_other | 40 | 38 | 2 | 35 | 5 | SELECT checks sin FROM ×5 (`7e9b92dc96aa`); SELECT customers_customer+sales_sale ×2 (`d8b2d15159e5`); SELECT django_session ×1 (`c51e4ea6f50b`) |
| add_product_20_lines | 68 | 62 | 6 | 55 | 13 | SELECT checks sin FROM ×10 (`7e9b92dc96aa`); SELECT business_config_possettings ×3 (`7c58813a5be8`); SELECT catalog_category+catalog_product+catalog_tax ×2 (`cb71e054b382`) |
| quantity_1_to_2 | 66 | 62 | 4 | 55 | 11 | SELECT checks sin FROM ×10 (`7e9b92dc96aa`); SELECT business_config_possettings ×2 (`7c58813a5be8`); SELECT core_business ×2 (`f8900cb03637`) |
| editor_discount_post | 67 | 62 | 5 | 55 | 12 | SELECT checks sin FROM ×10 (`7e9b92dc96aa`); SELECT business_config_possettings ×3 (`7c58813a5be8`); SELECT core_business ×2 (`f8900cb03637`) |
| delete_line_20_lines | 48 | 47 | 1 | 44 | 4 | SELECT checks sin FROM ×5 (`7e9b92dc96aa`); SELECT django_session ×1 (`c51e4ea6f50b`); SELECT users_customuser ×1 (`17bed91a026f`) |
| checkout_get_20_lines | 18 | 16 | 2 | 16 | 2 | SELECT payments_paymentmethod ×3 (`371ea3c562f4`); SELECT django_session ×1 (`c51e4ea6f50b`); SELECT users_customuser ×1 (`17bed91a026f`) |

## Crecimiento y hallazgos

- Grid sin filtro: **13 / 13 / 13 queries** para 50/250/1.000 productos, cuerpo ~19,6 KB. Filtro de categoría: **14 / 14 / 14**; búsqueda exacta: **12 / 12 / 12**. La búsqueda amplia devuelve 24 resultados por página; búsqueda exacta devuelve 1 y no necesita fallback fiscal. Las categorías y el Paginator añaden coste constante. No hay query por cada uno de los 24 productos: `select_related(category,tax,business)` y `resolved_taxes` del request ya evitan repetir el impuesto por defecto dentro de la página. No se cambiaron.
- Cart de lectura: **2 / 2 / 2 / 2 queries** con 1/5/20/50 líneas. El template consume snapshots de SaleLine, sin queries por producto. El HTML y el tiempo de render sí crecen: ~2,8/9,9/36,7/90,1 KB y p50 2,38/3,79/8,08/17,11 ms. Esto es coste O(n) de representación, no N+1 de queries.
- Full workspace: **14 queries** también con 0/1/5/20/50 líneas; ~48,8 → 150,0 KB. p50 36,20 → 54,77 ms. El crecimiento está en datos transferidos/renderizados, aunque el número de round trips siga constante.
- Añadir mantiene **68 queries** con 1/20 líneas; eliminar **48** con 1/20. `_recalculate_locked_sale` lee y suma todas las líneas una vez y la respuesta vuelve a renderizar el cart completo. Se documenta ese coste proporcional de filas/HTML; no se cambia la operación ni la cola.
- Quantity hace **66 queries**, con POSSettings dos veces y varias consultas de validación/relaciones/constraints. No carga el catálogo completo. `SaleLine.save` y `Sale.save` ejecutan `full_clean`; los patrones de checks SQL normalizados explican parte del número, pero no equivalen a diez duplicados eliminables. SQL acumulado p50 ~19–21 ms frente a request ~42–45 ms. No se ha perfilado CPU por función: el resto incluye Django/ORM/validación/templates/instrumentación, y no puede atribuirse solo al template.
- Header hace **38 queries** al cambiar documento y **40** al cambiar cliente. Los dos reads del header y el lock/revalidación de escritura incluyen relectura del estado autoritativo para devolver lo persistido. La regresión protege que no cargue Product ni SaleLine. No se debilitan validaciones ni reglas de Ticket/Factura.
- Checkout GET: **18 queries** con 1/20 líneas, ~7,3 KB; método activo consultado **3 veces**, **2 repeticiones exactas** en ese patrón. SQL acumulado p50 ~16–17 ms y request p50 35–38 ms. UI p95 134/126 ms: modal visible, control interactuable y settle finalizado. Sin N+1 por línea observado. El resultado solo cubre el estado editable inicial con dos métodos y una serie válida por tipo; no extrapola a split, documento ya emitido o grandes históricos de pagos.
- Grid HTMX aún pasa por `get_sale_detail` y prefetch de líneas/devoluciones, y construye formularios de header/cash-session aun cuando renderiza solo el grid. Queries constantes no significan que sea la lectura mínima posible. Candidato de separación para Fase 7; mantener comprobaciones tenant/store y contrato OOB.
- Primera request de grid tiene 16 queries y la primera full workspace 17; sus warm respectivos tienen 13 y 14. El contexto de tienda se guarda en sesión. Estas consultas iniciales son comportamiento existente; no se eliminan para mejorar cifras.
- Variabilidad visible: grid grande sin filtro tuvo máximo ~115 ms frente a p95 ~41 ms; checkout de 1 línea máximo ~117 ms frente a p95 ~40 ms; editor discount GET máximo ~78 ms frente a p95 ~10 ms. Se conserva cada muestra y no se adjudica el outlier a una query sin evidencia adicional. Veinte muestras sirven como referencia exploratoria, no como garantía estadística de SLO.

### Search, debounce y barcode

El template configura **`input changed delay:275ms`** y `submit` en el mismo form. La latencia UI de búsqueda incluye esa espera; la columna server no. La búsqueda browser usa `BASE-0020`, equivalente al escenario server `grid_250_search_exact`, con un resultado visible.

Barcode se busca por el mismo `q` (`name OR sku OR barcode`): input sin submit sigue el debounce; un submit/Enter del form usa el trigger `submit`, sin ese delay configurado. No existe un handler específico de scanner en `sales_tpv.js`. No se ha medido scanner físico ni aplicado la mejora de barcode inmediato.

### Objetivos de referencia

Referencia Netxodo: HTMX warm p95 ~250–300 ms; full page ~500 ms; heavy report ~1–1,5 s. Ninguna request server medida supera la referencia de su tipo, y las interacciones browser distintas de search también quedan por debajo de 250 ms en este entorno. Search UI p95 **377 ms** supera esa referencia de interacción total, con **275 ms de debounce explícito** y server p95 **26 ms**. No se suman ni restan p95 de mediciones independientes ni se interpreta 500 ms como una medida de carga full-page en browser: esa navegación no se perfiló. Heavy reports quedan fuera de este baseline.

### Checkout POST

**"Checkout POST se medirá por separado en Fase 8/9."**

La revisión confirma que `run_checkout` coordina pasos durables independientes Sales → Payments → Billing, incluyendo stock, caja, snapshots fiscales, series y claves de idempotencia. Medir la confirmación exigiría tratar preparación y verificación de todos esos efectos, no solo la apertura del modal. Se mantiene el foco del harness en interacciones editables y checkout GET; no se reutiliza una venta completada ni se altera el dominio para forzar esta métrica. Sus flujos funcionales siguen cubiertos por las suites existentes.

## Candidatos de optimización — Fase 7

| Prioridad | Problema y escenario | Evidencia / impacto estimado | Posible actuación posterior |
|---|---|---|---|
| **ALTO** | Búsqueda frecuente y entrada barcode con debounce | 275 ms configurados frente a server exacto p95 26 ms; UI p95 377 ms. La espera explica la mayor parte de la interacción; no la lentitud SQL. | Evaluar UX/debounce y tratamiento específico de scanner/submit con pruebas de cola y concurrencia; esta fase no cambia el delay. |
| **ALTO** | Escrituras frecuentes de quantity/add | 66/68 round trips; settings repetidos 2/3 veces, revalidaciones y constraints. SQL p50 ~19–28 ms más coste Django y cart completo. A mayor latencia DB podría importar más que el número local en ms. | Atribuir coste por patrón y revisar reutilización **por request** de configuración/lecturas compatibles. Conservar seguridad, locks, validación e importes; no suprimir checks solo por conteo. No se estima ahorro en ms sin experimento. |
| **MEDIO** | Grid parcial carga estado de venta más amplio del necesario | 13 queries y prefetch de líneas/devoluciones pese a responder grid; 50→1.000 mantiene queries, pero más filas de ticket pueden requerir trabajo adicional. | Evaluar selector específico de workspace/grid y carga de contexto solo necesario manteniendo tenant/store/OOB. |
| **MEDIO** | Cart completo en cada swap de ticket largo | 90 KB en render de 50 líneas; workspace 150 KB. Queries O(1), tiempo/HTML O(n), scroll/cola deben permanecer idénticos. | Investigar alcance del swap y coste de render con medición de 50 líneas; evitar dar por asumido que payload pequeño preserve revisiones y scroll. |
| **BAJO** | Consultas repetidas de métodos al abrir checkout | Mismo SELECT 3 veces, 18 queries totales, 7,3 KB y p95 UI 126–134 ms. Operación menos frecuente y por debajo del objetivo local. | Revisar materialización/reutilización de métodos en Fase 8 tras Fase 7; ninguna optimización de checkout aquí. |
| **BAJO** | Header con 38–40 queries y relectura autoritativa | 1,7–1,9 KB; p95 server 31–36 ms y UI ~144 ms. Sin carga de cart/catalog. Parte de lecturas protege estado correcto. | Investigar duplicados compatibles manteniendo autosave, revisions, hx-sync y validación de cliente/documento. |

No se detecta un candidato de índice dominante que justifique EXPLAIN en este dataset; no se realizó EXPLAIN ANALYZE ni se crearon índices. No se introducen cachés globales, APM, middleware permanente ni dependencias.

## Regresiones y deuda técnica

Se conserva `CartLayoutTests.test_twenty_line_cart_has_constant_query_count` de Fase 5. Las nuevas pruebas protegen: grid 50/250/1.000 con 24 productos paginados; cart 1/5/20/50 con dos queries; header sin consultas Product/SaleLine; quantity sin crecimiento con catálogo y con lookup acotado al producto editado; checkout 1/20 sin crecimiento; captura válida con buffer SQL lleno; percentiles nearest-rank; resumen sin valores SQL privados. Los máximos se fijan **después de medir**, sobre requests warm: grid ≤13, header con cliente ≤40, quantity ≤66 y checkout ≤18. Protegen crecimiento/contratos saludables, no fijan un N+1 como comportamiento deseable.

Deuda técnica documentada: lectura amplia de `SaleObjectMixin` en grid/add/delete; validación de modelos y settings repetidos en escrituras; HTML proporcional al ticket; opciones checkout consultadas reiteradamente; instrumentación añade overhead; falta de perfil CPU por función, scanner físico, prueba bajo concurrencia, navegación full-page en browser y confirmación fiscal/pagos medida. El owner sintético no representa todas las consultas adicionales de roles con StoreAccess; las pruebas funcionales existentes mantienen tenant/store isolation. Las relaciones reales y los dos métodos no modelan grandes históricos de devoluciones/pagos, muchas categorías o miles de clientes en el select de header. Son límites de la fotografía actual, no resultados inventados.

Se corrigió además una prueba existente de aislamiento de caja (`test_session_detail_lists_only_its_sales_and_opened_by`): pedía la pestaña Resumen y comprobaba `#pk`, que podía coincidir con el ID de sesión en SQLite o una ejecución aislada. La suite completa PostgreSQL con secuencias distintas reveló el falso positivo. Ahora pide `tab=sales` y verifica los href exactos de la venta incluida y de la excluida, sin modificar producción.

## Validación y archivos

Ruff lint/format, Django check y makemigrations dry-run sin cambios; ninguna migración. Pruebas afectadas y los cinco gates PostgreSQL: **218 tests, OK sin omisiones**. Las 8 pruebas nuevas también pasan en SQLite; prueba de caja corregida más las 8 nuevas: **9 tests, OK**. La suite Django completa SQLite ejecutó **1.526 tests, OK con 27 omisiones de backend/entorno**; se verificó después la prueba corregida. La validación completa final en PostgreSQL, los 27 browser tests TPV/checkout/full_flow/HTMX, los 23 módulos de browser CI y los checks Actions se registran en la PR sobre su SHA final. El benchmark temporal permanece manual; las regresiones rápidas se ejecutan en CI general y en el job PostgreSQL Sales existente.

Archivos creados: `tests/performance/{__init__,dataset,metrics,baseline,browser,test_queries,test_metrics}.py`, este informe y los dos JSON. Archivos modificados: `.github/workflows/ci.yml` (añade regresiones rápidas al gate Sales PostgreSQL) y `apps/cash_register/tests/integration/test_views.py` (repara la prueba de aislamiento descrita). Ningún otro archivo de aplicación.
