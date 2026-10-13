# TPV fases 7–9: comparación medida

PR [#227](https://github.com/daniilabradorr/sala-tpv/pull/227), contra develop; no merge.

Base real: `6c29ca27d8a38bbc7a0e998ea5ab16a060202207`. Implementación medida: `95eb203d3c5c399107ebd1ee000837d759a1a3f0`.

El baseline histórico `tpv-baseline-server.json`, `tpv-baseline-browser.json` y `tpv-baseline.md` se conserva sin cambios. Esta comparación vuelve a ejecutar la aplicación de la base exacta y la implementación en el mismo entorno, secuencialmente, sin otras suites locales concurrentes. Se ha repetido BEFORE después del reinicio del entorno; los resultados anteriores de la sesión no se presentan como equivalentes al nuevo host.

Python 3.12.12; Django 5.2.12; PostgreSQL 16.15 (Debian 16.15-1.pgdg13+2); Chromium 151.0.7922.173. Cada escenario incluye 1 primera medición, 5 warmups descartados y 20 muestras calientes. p50 = mediana; p95 = nearest rank. No se añaden umbrales de tiempo a CI. Los ceilings de queries mantienen margen (checkout <=13 con 10 medidos), igualdad de crecimiento y exclusión de consultas de líneas/devoluciones en grid; el payload a 50 líneas debe ser menor que 4000 bytes y contener solo una línea/footer. No se convierten counts HTTP en asserts exactos.

El harness de Fase 6 mantiene sus métricas, captura SQL y verificación de efectos fuera del intervalo. Se adapta el target del observador a la línea reemplazada, registra la apertura del diálogo y añade mutaciones a 50 líneas y los cuatro checkout POST. En BEFORE se añaden únicamente los tres escenarios de 50 líneas y el escenario barcode/Enter al harness; el código de negocio permanece exactamente en la base. Los nuevos POST no tienen un BEFORE comparable y se informan como mediciones AFTER.

Los fixtures se preparan fuera del intervalo; cada POST usa una Sale fresca, claves nuevas y la implementación real. El verificador comprueba Sale completed, payments, pending cero, documento emitido y movimientos de efectivo por el importe asignado. La navegación/fixture setup del navegador queda fuera del tiempo de interacción. El tiempo UI sí incluye red, render y settle. La apertura del loading shell se mide por separado de la disponibilidad de métodos.

## Servidor

| Escenario | Queries B → A | Bytes B → A | p50/p95 B (ms) | p50/p95 A (ms) |
|---|---:|---:|---:|---:|
| `grid_50_all` | 13 → 11 | 19609 → 19764 | 30.12 / 31.83 | 14.16 / 15.50 |
| `grid_50_search` | 13 → 11 | 19635 → 19790 | 30.71 / 36.19 | 15.03 / 17.10 |
| `grid_50_search_exact` | 12 → 10 | 1491 → 1496 | 26.14 / 28.81 | 9.41 / 10.67 |
| `grid_50_category` | 14 → 12 | 13937 → 14022 | 29.22 / 32.15 | 13.88 / 15.14 |
| `grid_50_category_search` | 14 → 12 | 13937 → 14022 | 29.73 / 34.21 | 14.20 / 15.87 |
| `grid_50_page_2` | 13 → 11 | 19737 → 19927 | 31.35 / 35.86 | 14.06 / 15.12 |
| `grid_250_all` | 13 → 11 | 19610 → 19765 | 32.08 / 40.21 | 15.24 / 17.92 |
| `grid_250_search` | 13 → 11 | 19635 → 19790 | 35.36 / 49.42 | 15.26 / 17.07 |
| `grid_250_search_exact` | 12 → 10 | 1491 → 1496 | 26.17 / 31.66 | 10.53 / 12.77 |
| `grid_250_category` | 14 → 12 | 19618 → 19773 | 34.48 / 40.50 | 16.08 / 18.49 |
| `grid_250_category_search` | 14 → 12 | 19644 → 19799 | 31.34 / 42.62 | 18.52 / 25.00 |
| `grid_250_page_2` | 13 → 11 | 19738 → 19928 | 29.83 / 33.88 | 14.68 / 18.35 |
| `grid_1000_all` | 13 → 11 | 19610 → 19765 | 30.70 / 38.25 | 16.16 / 17.93 |
| `grid_1000_search` | 13 → 11 | 19635 → 19790 | 31.50 / 34.28 | 16.18 / 17.73 |
| `grid_1000_search_exact` | 12 → 10 | 1491 → 1496 | 26.37 / 29.54 | 11.44 / 11.91 |
| `grid_1000_category` | 14 → 12 | 19619 → 19774 | 32.97 / 36.07 | 14.77 / 16.45 |
| `grid_1000_category_search` | 14 → 12 | 19644 → 19799 | 30.13 / 33.53 | 16.18 / 19.17 |
| `grid_1000_page_2` | 13 → 11 | 19738 → 19928 | 33.61 / 39.97 | 18.15 / 20.69 |
| `workspace_0_lines` | 14 → 14 | 48770 → 49641 | 35.52 / 46.18 | 34.76 / 51.53 |
| `workspace_1_lines` | 14 → 14 | 50844 → 51783 | 35.16 / 41.51 | 35.98 / 44.71 |
| `cart_read_1_lines` | 2 → 2 | 2823 → 2911 | 2.30 / 2.79 | 2.34 / 2.56 |
| `workspace_5_lines` | 14 → 14 | 58917 → 60054 | 37.59 / 41.32 | 37.96 / 43.59 |
| `cart_read_5_lines` | 2 → 2 | 9928 → 10214 | 3.67 / 3.96 | 3.99 / 9.73 |
| `workspace_20_lines` | 14 → 14 | 89299 → 91210 | 42.08 / 44.43 | 50.91 / 67.51 |
| `cart_read_20_lines` | 2 → 2 | 36678 → 37738 | 7.47 / 8.67 | 10.59 / 20.12 |
| `workspace_50_lines` | 14 → 14 | 149989 → 153430 | 58.94 / 73.70 | 65.46 / 92.75 |
| `cart_read_50_lines` | 2 → 2 | 90108 → 92698 | 15.84 / 17.63 | 19.24 / 21.38 |
| `checkout_get_1_lines` | 18 → 10 | 7287 → 7720 | 35.57 / 41.41 | 25.79 / 33.74 |
| `checkout_get_20_lines` | 18 → 10 | 7292 → 7725 | 37.03 / 44.84 | 23.68 / 31.77 |
| `header_ticket_to_invoice` | 38 → 38 | 1862 → 1862 | 30.11 / 34.79 | 32.91 / 36.52 |
| `header_invoice_to_ticket` | 38 → 38 | 1723 → 1723 | 27.35 / 30.66 | 30.96 / 33.98 |
| `header_customer_none_to_customer` | 40 → 40 | 1723 → 1723 | 29.84 / 34.45 | 33.78 / 214.61 |
| `header_customer_to_other` | 40 → 40 | 1723–1726 → 1723–1726 | 30.11 / 38.32 | 32.77 / 38.11 |
| `add_product_1_lines` | 68 → 65 | 5161 → 5309 | 53.34 / 60.35 | 43.80 / 48.46 |
| `delete_line_1_lines` | 48 → 46 | 998 → 1018 | 47.05 / 62.18 | 34.67 / 36.65 |
| `add_product_20_lines` | 68 → 65 | 44097–44307 → 45271–45544 | 62.36 / 69.78 | 49.89 / 55.25 |
| `delete_line_20_lines` | 48 → 46 | 40189 → 41312 | 56.29 / 67.52 | 43.36 / 47.93 |
| `quantity_1_to_2` | 66 → 64 | 11359 → 2741 | 42.13 / 51.62 | 42.85 / 44.58 |
| `quantity_2_to_1` | 66 → 64 | 11361 → 2743 | 43.19 / 48.15 | 43.08 / 46.33 |
| `quantity_1_to_1.5` | 66 → 64 | 11361 → 2743 | 40.87 / 44.65 | 43.55 / 52.15 |
| `editor_discount_get` | 8 → 8 | 1596 → 1621 | 8.52 / 9.52 | 9.14 / 12.54 |
| `editor_discount_post` | 67 → 65 | 11476 → 2857 | 40.83 / 44.41 | 41.28 / 44.63 |
| `editor_price_get` | 8 → 8 | 1532 → 1557 | 8.28 / 8.80 | 8.83 / 9.28 |
| `editor_price_post` | 67 → 65 | 11383 → 2764 | 45.74 / 48.53 | 39.54 / 45.46 |
| `quantity_50_lines` | 66 → 64 | 104020 → 2746 | 58.11 / 60.45 | 40.60 / 43.09 |
| `discount_50_lines` | 67 → 65 | 104136 → 2861 | 58.12 / 60.55 | 41.79 / 48.56 |
| `price_50_lines` | 67 → 65 | 104043 → 2768 | 56.43 / 62.33 | 43.72 / 48.49 |
| `checkout_post_card` | — → 293 | — → 2330–2332 | — | 191.72 / 197.99 |
| `checkout_post_cash_exact` | — → 339 | — → 2432 | — | 220.70 / 249.94 |
| `checkout_post_cash_change` | — → 339 | — → 2432 | — | 206.81 / 218.25 |
| `checkout_post_split` | — → 411 | — → 2455–2457 | — | 257.26 / 287.20 |

## Navegador

| Escenario | UI p50/p95 BEFORE (ms) | UI p50/p95 AFTER (ms) | Apertura diálogo p50/p95 AFTER (ms) |
|---|---:|---:|---:|
| `search` | 348.75 / 362.80 | 243.25 / 256.80 | — |
| `barcode_enter` | 105.85 / 119.40 | 81.60 / 93.80 | — |
| `add` | 170.90 / 220.80 | 134.70 / 159.80 | — |
| `quantity_plus` | 128.15 / 144.00 | 119.20 / 157.00 | — |
| `quantity_enter` | 137.15 / 179.60 | 119.75 / 143.30 | — |
| `header` | 126.60 / 161.30 | 116.20 / 153.50 | — |
| `checkout_1` | 124.95 / 168.10 | 91.20 / 110.10 | 13.90 / 19.30 |
| `checkout_20` | 109.15 / 137.50 | 92.15 / 120.10 | 16.55 / 25.20 |
| `checkout_post_card` | — | 365.05 / 401.10 | — |
| `checkout_post_cash_exact` | — | 397.65 / 437.10 | — |
| `checkout_post_cash_change` | — | 354.55 / 392.40 | — |
| `checkout_post_split` | — | 393.65 / 428.80 | — |

## Límites de interpretación y reproducibilidad

Las consultas y los bytes son evidencias estructurales; las latencias dependen del host y sus colas. Se conservan las métricas que empeoran: por ejemplo, header_customer_none_to_customer mantiene 40 queries/1723 bytes pero el p95 aumenta de 34,451 a 214,606 ms. No se filtran outliers ni se cambia la metodología para presentar una mejora uniforme. Se publican todas las muestras, primeras mediciones y p95, incluyendo regresiones. No se compara la velocidad de GitHub runners con la del entorno local. Localmente Playwright usa el Chromium del sistema tanto BEFORE como AFTER; CI instala su Chromium mediante el workflow existente. No se añaden dependencias ni se cambia el browser gate.

Comandos (con `DJANGO_SETTINGS_MODULE=config.settings.test`, `SECRET_KEY` y `DATABASE_URL` apuntando a PostgreSQL 16 de pruebas):

```bash
python -m tests.performance.baseline --output result-server.json --warmups 5 --iterations 20
python -m tests.performance.baseline --browser --chromium /usr/bin/chromium --output result-browser.json --warmups 5 --iterations 20
```

Ejecutar primero sobre un worktree de la base y luego sobre la implementación. Nunca contra una base de producción. El harness crea y destruye su test DB. La extensión BEFORE de 50 líneas y barcode/Enter replica los nuevos prepares, sin incorporar cambios de aplicación. Se publica `tpv-phase7-9-before-harness.patch`: aplicarlo al worktree de la base con `git apply --unidiff-zero`, ejecutar collectstatic y después los comandos anteriores reproduce la extensión exacta. El campo declarativo harness_extension de los JSON publicados describe conjuntamente las extensiones server/UI; no modifica muestras ni estadísticas.
## Comparación con el baseline histórico solicitado

BEFORE histórico: `tpv-baseline-server.json` y `tpv-baseline-browser.json`, SHA `ecf4e43e5e9cbfc3561e4f088453bfeffae7cba2`. AFTER: `tpv-phase7-9-server.json` y `tpv-phase7-9-browser.json`, SHA `95eb203d3c5c399107ebd1ee000837d759a1a3f0`.

Los tiempos wall-clock históricos no son estrictamente comparables entre máquinas. Las tablas anteriores utilizan la repetición BEFORE en el mismo host; esta tabla histórica prioriza queries y bytes. Δ % = ((AFTER − BEFORE) / BEFORE) × 100; negativo significa reducción. Los escenarios ausentes del baseline son NUEVOS; la extensión BEFORE anterior es una referencia adicional, no una modificación del histórico.

| Escenario | Queries BEFORE | AFTER | Δ | Bytes BEFORE | AFTER | Δ % (máximo) | p50 BEFORE | AFTER | Δ % | p95 BEFORE | AFTER | Δ % | Clasificación estructural |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| `grid_50_all` | 13 | 11 | -2 | 19609 | 19764 | +0.79 % | 28.31 | 14.16 | -49.96 % | 32.66 | 15.50 | -52.54 % | MEJORA |
| `grid_50_search` | 13 | 11 | -2 | 19635 | 19790 | +0.79 % | 27.19 | 15.03 | -44.71 % | 30.58 | 17.10 | -44.09 % | MEJORA |
| `grid_50_search_exact` | 12 | 10 | -2 | 1491 | 1496 | +0.34 % | 23.70 | 9.41 | -60.28 % | 33.19 | 10.67 | -67.84 % | MEJORA |
| `grid_50_category` | 14 | 12 | -2 | 13937 | 14022 | +0.61 % | 27.05 | 13.88 | -48.67 % | 31.35 | 15.14 | -51.69 % | MEJORA |
| `grid_50_category_search` | 14 | 12 | -2 | 13937 | 14022 | +0.61 % | 27.19 | 14.20 | -47.78 % | 30.35 | 15.87 | -47.72 % | MEJORA |
| `grid_50_page_2` | 13 | 11 | -2 | 19737 | 19927 | +0.96 % | 27.44 | 14.06 | -48.74 % | 31.17 | 15.12 | -51.49 % | MEJORA |
| `grid_250_all` | 13 | 11 | -2 | 19610 | 19765 | +0.79 % | 31.69 | 15.24 | -51.91 % | 37.50 | 17.92 | -52.20 % | MEJORA |
| `grid_250_search` | 13 | 11 | -2 | 19635 | 19790 | +0.79 % | 29.65 | 15.26 | -48.54 % | 39.44 | 17.07 | -56.72 % | MEJORA |
| `grid_250_search_exact` | 12 | 10 | -2 | 1491 | 1496 | +0.34 % | 24.91 | 10.53 | -57.73 % | 26.42 | 12.77 | -51.68 % | MEJORA |
| `grid_250_category` | 14 | 12 | -2 | 19618 | 19773 | +0.79 % | 29.33 | 16.08 | -45.18 % | 32.31 | 18.49 | -42.78 % | MEJORA |
| `grid_250_category_search` | 14 | 12 | -2 | 19644 | 19799 | +0.79 % | 34.54 | 18.52 | -46.39 % | 41.63 | 25.00 | -39.94 % | MEJORA |
| `grid_250_page_2` | 13 | 11 | -2 | 19738 | 19928 | +0.96 % | 32.49 | 14.68 | -54.83 % | 39.60 | 18.35 | -53.68 % | MEJORA |
| `grid_1000_all` | 13 | 11 | -2 | 19610 | 19765 | +0.79 % | 35.94 | 16.16 | -55.04 % | 41.41 | 17.93 | -56.69 % | MEJORA |
| `grid_1000_search` | 13 | 11 | -2 | 19635 | 19790 | +0.79 % | 34.23 | 16.18 | -52.73 % | 40.03 | 17.73 | -55.70 % | MEJORA |
| `grid_1000_search_exact` | 12 | 10 | -2 | 1491 | 1496 | +0.34 % | 25.11 | 11.44 | -54.46 % | 29.30 | 11.91 | -59.35 % | MEJORA |
| `grid_1000_category` | 14 | 12 | -2 | 19619 | 19774 | +0.79 % | 27.67 | 14.77 | -46.62 % | 32.31 | 16.45 | -49.09 % | MEJORA |
| `grid_1000_category_search` | 14 | 12 | -2 | 19644 | 19799 | +0.79 % | 28.25 | 16.18 | -42.71 % | 32.72 | 19.17 | -41.42 % | MEJORA |
| `grid_1000_page_2` | 13 | 11 | -2 | 19738 | 19928 | +0.96 % | 32.22 | 18.15 | -43.67 % | 56.32 | 20.69 | -63.26 % | MEJORA |
| `workspace_0_lines` | 14 | 14 | +0 | 48770 | 49641 | +1.79 % | 36.20 | 34.76 | -3.99 % | 49.61 | 51.53 | +3.88 % | REGRESIÓN payload |
| `workspace_1_lines` | 14 | 14 | +0 | 50844 | 51783 | +1.85 % | 39.34 | 35.98 | -8.54 % | 88.50 | 44.71 | -49.48 % | REGRESIÓN payload |
| `cart_read_1_lines` | 2 | 2 | +0 | 2823 | 2911 | +3.12 % | 2.38 | 2.34 | -1.89 % | 3.15 | 2.56 | -18.86 % | ESTABLE |
| `workspace_5_lines` | 14 | 14 | +0 | 58917 | 60054 | +1.93 % | 40.66 | 37.96 | -6.64 % | 53.80 | 43.59 | -18.97 % | REGRESIÓN payload |
| `cart_read_5_lines` | 2 | 2 | +0 | 9928 | 10214 | +2.88 % | 3.79 | 3.99 | +5.28 % | 4.67 | 9.73 | +108.20 % | REGRESIÓN payload |
| `workspace_20_lines` | 14 | 14 | +0 | 89299 | 91210 | +2.14 % | 42.96 | 50.91 | +18.50 % | 48.85 | 67.51 | +38.19 % | REGRESIÓN payload |
| `cart_read_20_lines` | 2 | 2 | +0 | 36678 | 37738 | +2.89 % | 8.08 | 10.59 | +31.01 % | 9.22 | 20.12 | +118.28 % | REGRESIÓN payload |
| `workspace_50_lines` | 14 | 14 | +0 | 149989 | 153430 | +2.29 % | 54.77 | 65.46 | +19.52 % | 66.17 | 92.75 | +40.17 % | REGRESIÓN payload |
| `cart_read_50_lines` | 2 | 2 | +0 | 90108 | 92698 | +2.87 % | 17.11 | 19.24 | +12.41 % | 20.90 | 21.38 | +2.30 % | REGRESIÓN payload |
| `checkout_get_1_lines` | 18 | 10 | -8 | 7287 | 7720 | +5.94 % | 35.28 | 25.79 | -26.89 % | 39.84 | 33.74 | -15.31 % | MEJORA |
| `checkout_get_20_lines` | 18 | 10 | -8 | 7292 | 7725 | +5.94 % | 38.20 | 23.68 | -38.00 % | 43.17 | 31.77 | -26.39 % | MEJORA |
| `header_ticket_to_invoice` | 38 | 38 | +0 | 1862 | 1862 | +0.00 % | 28.95 | 32.91 | +13.70 % | 30.75 | 36.52 | +18.79 % | ESTABLE |
| `header_invoice_to_ticket` | 38 | 38 | +0 | 1723 | 1723 | +0.00 % | 29.59 | 30.96 | +4.62 % | 31.64 | 33.98 | +7.40 % | ESTABLE |
| `header_customer_none_to_customer` | 40 | 40 | +0 | 1723 | 1723 | +0.00 % | 30.61 | 33.78 | +10.33 % | 35.93 | 214.61 | +497.31 % | ESTABLE |
| `header_customer_to_other` | 40 | 40 | +0 | 1723–1726 | 1723–1726 | +0.00 % | 30.49 | 32.77 | +7.46 % | 33.91 | 38.11 | +12.37 % | ESTABLE |
| `add_product_1_lines` | 68 | 65 | -3 | 5161 | 5309 | +2.87 % | 54.89 | 43.80 | -20.19 % | 60.05 | 48.46 | -19.31 % | MEJORA |
| `delete_line_1_lines` | 48 | 46 | -2 | 998 | 1018 | +2.00 % | 45.39 | 34.67 | -23.62 % | 46.73 | 36.65 | -21.57 % | MEJORA |
| `add_product_20_lines` | 68 | 65 | -3 | 44097–44307 | 45271–45544 | +2.79 % | 62.00 | 49.89 | -19.53 % | 64.58 | 55.25 | -14.45 % | MEJORA |
| `delete_line_20_lines` | 48 | 46 | -2 | 40189 | 41312 | +2.79 % | 54.62 | 43.36 | -20.62 % | 57.95 | 47.93 | -17.29 % | MEJORA |
| `quantity_1_to_2` | 66 | 64 | -2 | 11359 | 2741 | -75.87 % | 45.28 | 42.85 | -5.37 % | 52.29 | 44.58 | -14.76 % | MEJORA |
| `quantity_2_to_1` | 66 | 64 | -2 | 11361 | 2743 | -75.86 % | 44.10 | 43.08 | -2.32 % | 45.76 | 46.33 | +1.26 % | MEJORA |
| `quantity_1_to_1.5` | 66 | 64 | -2 | 11361 | 2743 | -75.86 % | 41.77 | 43.55 | +4.27 % | 45.32 | 52.15 | +15.07 % | MEJORA |
| `editor_discount_get` | 8 | 8 | +0 | 1596 | 1621 | +1.57 % | 7.90 | 9.14 | +15.73 % | 10.16 | 12.54 | +23.47 % | ESTABLE |
| `editor_discount_post` | 67 | 65 | -2 | 11476 | 2857 | -75.10 % | 43.02 | 41.28 | -4.03 % | 44.72 | 44.63 | -0.19 % | MEJORA |
| `editor_price_get` | 8 | 8 | +0 | 1532 | 1557 | +1.63 % | 8.09 | 8.83 | +9.19 % | 8.61 | 9.28 | +7.74 % | ESTABLE |
| `editor_price_post` | 67 | 65 | -2 | 11383 | 2764 | -75.72 % | 43.74 | 39.54 | -9.59 % | 49.21 | 45.46 | -7.62 % | MEJORA |

### Browser histórico y desglose AFTER

Todas las parejas siguientes son p50/p95 en ms. Las diferencias de UI históricas describen mediciones, no un porcentaje causal de velocidad.

| Escenario | UI BEFORE | UI AFTER | Δ p50/p95 ms | event→request AFTER | request→response AFTER | response→settle AFTER | settle→visible AFTER | click→dialog AFTER |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| `search` | 354.80/377.10 | 243.25/256.80 | -111.55/-120.30 | 178.40/179.90 | 35.20/45.80 | 21.20/22.40 | 6.50/11.70 | N/A |
| `barcode_enter` | NEW | 81.60/93.80 | NEW | 3.60/5.70 | 44.85/63.80 | 21.20/25.20 | 6.20/14.60 | N/A |
| `add` | 171.65/220.30 | 134.70/159.80 | -36.95/-60.50 | 4.60/6.30 | 97.95/121.70 | 22.80/24.00 | 7.75/14.70 | N/A |
| `quantity_plus` | 116.95/143.80 | 119.20/157.00 | 2.25/13.20 | 4.85/9.40 | 82.05/111.50 | 21.50/21.80 | 6.75/16.50 | N/A |
| `quantity_enter` | 130.10/161.10 | 119.75/143.30 | -10.35/-17.80 | 3.90/7.90 | 87.00/107.50 | 21.45/23.50 | 5.55/15.80 | N/A |
| `header` | 112.05/143.50 | 116.20/153.50 | 4.15/10.00 | 2.75/4.20 | 81.70/105.90 | 20.85/34.20 | 10.25/17.00 | N/A |
| `checkout_1` | 101.45/134.00 | 91.20/110.10 | -10.25/-23.90 | 2.50/5.20 | 61.70/77.80 | 22.00/30.90 | 4.95/9.70 | 13.90/19.30 |
| `checkout_20` | 106.75/126.10 | 92.15/120.10 | -14.60/-6.00 | 2.45/3.30 | 63.90/84.90 | 21.80/30.30 | 3.80/9.90 | 16.55/25.20 |
| `checkout_post_card` | NEW | 365.05/401.10 | NEW | 3.25/4.30 | 328.90/371.50 | 21.20/23.50 | 8.75/14.90 | N/A |
| `checkout_post_cash_exact` | NEW | 397.65/437.10 | NEW | 3.55/4.30 | 363.10/403.50 | 21.25/24.30 | 9.95/12.70 | N/A |
| `checkout_post_cash_change` | NEW | 354.55/392.40 | NEW | 3.25/3.70 | 322.05/356.20 | 21.15/24.40 | 4.80/12.90 | N/A |
| `checkout_post_split` | NEW | 393.65/428.80 | NEW | 3.40/4.00 | 362.35/389.30 | 21.20/23.10 | 6.45/15.00 | N/A |

Search event→request histórico 277.70/278.40 → AFTER 178.40/179.90 ms. Debounce 275 → 175 ms. Barcode Enter es NEW respecto al histórico y no se equipara a búsqueda humana.

### Nuevos escenarios respecto al histórico

| Escenario nuevo | Queries | Bytes | SQL p50/p95 ms | Server p50/p95 ms | UI p50/p95 ms |
|---|---:|---:|---:|---:|---:|
| `barcode_enter` — NEW IN PHASE 7-9 BENCHMARK | N/A | N/A | N/A | N/A | 81.60/93.80 |
| `checkout_post_card` — NEW IN PHASE 7-9 BENCHMARK | 293 | 2330–2332 | 87.05/92.80 | 191.72/197.99 | 365.05/401.10 |
| `checkout_post_cash_exact` — NEW IN PHASE 7-9 BENCHMARK | 339 | 2432 | 105.18/112.56 | 220.70/249.94 | 397.65/437.10 |
| `checkout_post_cash_change` — NEW IN PHASE 7-9 BENCHMARK | 339 | 2432 | 95.37/102.14 | 206.81/218.25 | 354.55/392.40 |
| `checkout_post_split` — NEW IN PHASE 7-9 BENCHMARK | 411 | 2455–2457 | 120.62/139.66 | 257.26/287.20 | 393.65/428.80 |
| `quantity_50_lines` — NEW IN PHASE 7-9 BENCHMARK | 64 | 2746 | 19.57/21.51 | 40.60/43.09 | N/A |
| `discount_50_lines` — NEW IN PHASE 7-9 BENCHMARK | 65 | 2861 | 20.07/24.45 | 41.79/48.56 | N/A |
| `price_50_lines` — NEW IN PHASE 7-9 BENCHMARK | 65 | 2768 | 20.85/23.64 | 43.72/48.49 | N/A |

### Investigación de regresiones

Se revisan las 20 muestras y los perfiles SQL, no se repite la ejecución para mejorar resultados. El header none→customer conserva exactamente 40 queries y 1723 bytes en el BEFORE del mismo host, pero su p95 AFTER es 214,606 ms frente a 34,451 ms; SQL p95 AFTER es 18,291 ms. El pico está fuera del SQL y su causa concreta no queda demostrada por estas capturas. No se atribuye a una nueva consulta ni se elimina. Se mantiene como REGRESIÓN de latencia observada, con causa no resuelta, y no se realiza un cambio productivo especulativo.

Cart read 5/20 líneas y workspace 20/50 presentan regresiones de p95 en el mismo host. Sus queries permanecen constantes (2/14); el payload aumenta por atributos y controles de interacción necesarios para las nuevas garantías. La respuesta completa de add/delete también crece; no se afirma que toda interacción mejore. Los editores GET conservan 8 queries y añaden 25 bytes. Quantity fraccionaria p95 y quantity_plus UI p95 empeoran mientras el payload parcial cae. El benchmark demuestra ahorro de payload y separación de contexto, no una mejora uniforme de latencia.

Quantity 50 líneas AFTER: 2746 bytes. Frente al cart_read_50_lines histórico completo (90108 bytes), Δ = -96.95 %; son endpoints diferentes. La comparación del mismo endpoint con BEFORE extendido figura arriba.

### Trazabilidad del commit de documentación

Measured runtime SHA: `95eb203d3c5c399107ebd1ee000837d759a1a3f0`. Primer commit que versiona resultados: `89e922e` (SHA completo en el historial). Final documentation commit: el HEAD final de PR #227, identificado con SHA completo en su body y en la entrega. No se introduce ningún cambio de runtime posterior al SHA medido; se evita una referencia circular al SHA del propio archivo.
