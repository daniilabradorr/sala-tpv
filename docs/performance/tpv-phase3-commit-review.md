# Preparación de commits B, C, P01 y P02 — 29/10/2026

Rama revisada: `fix/tpv-checkout-audit-phase3`. Base anterior a esta agrupación: `453e9c61de9c2a61b0c628c8e966b1c4983b03fc`. Se crean cuatro commits locales, sin push, merge, PR ni despliegue.

## Alcance y preservación

Los38 archivos pendientes corresponden a los bloques solicitados:11 de B,14 del estado inicial de C, y el incremento P01/P02 que extiende parte de C. No se han encontrado archivos ajenos entre los candidatos. Se guardaron manifiesto SHA256, copia de los38 archivos y diff inicial en `/workspace/work/phase3-commits`.

La separación se realiza en el índice de Git mediante blobs intermedios; no se restaura, descarta ni sobrescribe el contenido final del directorio de trabajo. El árbol completo coincide byte a byte con la copia validada al cerrar P01/P02, reconstruida desde la base, los archivos iniciales B/C y el diff autorizado. Al terminar, los38 archivos deben mantener los SHA256 registrados antes de preparar commits.

B conserva el diagnóstico opt-in, sus pruebas y las84 muestras. C conserva la auditoría, matrices, evidencia y frontend anteriores a la autorización funcional. P01 incluye exclusivamente la recuperación de Billing desde estado persistido y sus pruebas; P02 añade la recuperación explícita del saldo en otra sesión válida y completa pruebas/evidencia de ambos. Las partes compartidas se reparten por comportamiento, no por archivo completo. El acceso de detalle a «Recuperar checkout» y la retención de identidad tras un fallo conocido de Billing se incluyen con P01; la selección de sesión y confirmación de una parte pendiente, con P02.

Los servicios económicos de Sales, Payments, Inventory, CashRegister y Billing, los modelos, migraciones y configuración de producción no cambian. Los informes y JSON de evidencia anteriores conservan sus SHA y estados Git históricos (incluido el HEAD453e9c6 y la mención «sin commit» al tomar esas medidas); no describen el estado de Git posterior a esta preparación.

## Archivos sensibles y cambios accidentales

Se revisaron el diff completo, el inventario de archivos, los JSON y los puntos de activación de instrumentación. El rastreo local de los38 archivos buscó claves privadas, patrones de tokens GitHub/AWS/API/JWT, URLs con contraseña y asignaciones literales de credenciales. No detectó secretos de esos tipos. Las dos asignaciones de contraseña son fixtures E2E sintéticos ya presentes en HEAD; no son credenciales de producción. El campo JSON `authorization_date_madrid` es una fecha, no un header ni un token.

`.env` y `.venv` están ignorados y no se leen ni incluyen. Tampoco se incluyen logs, copias temporales, archivos de BD ni archivos del directorio de trabajo externo. Las mediciones conservan contadores, tiempos y hashes; no aparecen campos de cookies, CSRF, contraseñas o SQL crudo en los JSON revisados. Esta es una revisión de los cambios candidatos, no una auditoría universal de todos los secretos posibles del repositorio histórico.

## Verificación económica

Se contrastan los38 snapshots guardados en `tpv-phase3-block-c-evidence.json` con los correspondientes de `tpv-phase3-p01-p02-evidence.json`: **38/38 idénticos económicamente**, normalizando únicamente el orden de ventas y sesiones. Además se comprueban por programa saldos no negativos, confirmado+pendiente igual al total sintético12,10 €, como máximo un documento inicial por venta, numeración sin duplicados, contadores de serie, una salida por línea del fixture, balance de stock y balance esperado/movimientos de caja. El estado HTTP se compara por separado y no se utiliza como prueba suficiente de corrección.

Esta operación revalida la evidencia PostgreSQL ya ejecutada y la correspondencia de sus fuentes; no repite una nueva campaña de38 carreras HTTP. Se conservan las validaciones anteriores:751 pruebas financieras,26 E2E Chromium y el suplemento14 tests, además de1596 pases de pytest. Sus comandos, resultados y limitaciones siguen en `tpv-phase3-p01-p02-report.md` y el JSON asociado.

La separación intermedia de P01 se valida adicionalmente en un árbol temporal sin P02: **53 tests PASS,8,416s**, incluyendo checkout, efectivo, presentación, recuperación de Billing y diagnóstico. Esta nueva ejecución usa SQLite solo para regresión no concurrente; no se presenta como prueba de locks. Las pruebas concurrentes de PostgreSQL y la impresión/nueva venta de Chromium son las ya conservadas en la evidencia original. Ruff y sintaxis JS de la versión intermedia también son correctos.

## Seis fallos preexistentes de pytest

Pytest completo:1596 PASS,6 FAIL,525 subtests PASS. Los mismos seis IDs fallan sobre el HEAD original exportado con datos sintéticos; no se han modificado catálogo, impuestos ni medios en estos commits.

- `apps/catalog/tests/test_tax_resolution.py::ProductTaxResolutionTests::test_inactive_specific_tax_is_an_error`
- `apps/catalog/tests/test_tax_resolution.py::ProductTaxResolutionTests::test_one_default_per_business_and_defaults_for_two_businesses`
- `apps/catalog/tests/test_tax_resolution.py::ProductTaxResolutionTests::test_other_business_default_is_never_used`
- `apps/catalog/tests/unit/test_forms.py::TaxFormTests::test_tax_update_form_exposes_is_active_but_not_business_or_is_default`
- `apps/catalog/tests/unit/test_services.py::CatalogMediaDeleteTests::test_protected_delete_keeps_media`
- `apps/catalog/tests/unit/test_services.py::CatalogMediaDeleteTests::test_successful_product_delete_cleans_media_after_commit`

Causas observadas: fixture que asigna un impuesto inactivo, dos fixtures con slug de empresa duplicado, expectativa antigua del campo `is_active` y dos imports de `apps.core.tests.test_media` que no existe como paquete. No se marcan como corregidos ni se declara pytest completamente verde.

## Commits locales

Los tres primeros commits preparados son:

```text
00d68e2 fix(checkout): recover pending Billing independently of historical payment methods
e568de8 fix(checkout): add block C integrity audit and unknown-result recovery
cbdb14e test(performance): add phase 3 block B checkout diagnostics
```

El cuarto commit, P02, incorpora este informe y el estado final completo. Su SHA se obtiene con `git log -4 --oneline`; no se incrusta su propio SHA en el contenido que lo determina. Las cuatro etapas mantienen sus pruebas y documentación. El resultado final debe dejar `git status --porcelain` vacío, conservando todos los bytes originales revisados más este informe.
