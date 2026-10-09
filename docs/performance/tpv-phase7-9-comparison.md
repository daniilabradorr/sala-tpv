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

Ejecutar primero sobre un worktree de la base y luego sobre la implementación. Nunca contra una base de producción. El harness crea y destruye su test DB. La extensión BEFORE de 50 líneas y barcode/Enter replica los nuevos prepares, sin incorporar cambios de aplicación. Se publica `tpv-phase7-9-before-harness.patch`: aplicarlo al worktree de la base, ejecutar collectstatic y después los comandos anteriores reproduce la extensión exacta. El campo declarativo harness_extension de los JSON publicados describe conjuntamente las extensiones server/UI; no modifica muestras ni estadísticas.
