# NETXODO — Bloque E: informe final

Cierre30/10/2026 (Europe/Madrid), con ejecuciones29–30/10. Rama `fix/tpv-checkout-audit-phase3`; SHA inicial/final **`ad110fe46b777bf7522444ed72353fdba5177128`**, más el diff local de E. Árbol inicialmente limpio. HEAD remoto de la rama y main se verifican de nuevo el30/10: ad110fe y `cdbf88c7df6b5c9d75ccdeda84c8ac8b67b03983`. Sin merge, nueva rama, commit, push, PR o despliegue.

La auditoría y las pruebas autorizadas quedan realizadas. Pytest completo pasa tras corregir los seis tests/fixtures obsoletos; los servicios fiscales/económicos permanecen intactos. Queda **un defecto monetario confirmado**: se acepta configurar USD pero Billing no guarda moneda y muestra euros. También se confirma el límite de inmutabilidad/exclusión inicial frente a bulk/SQL fuera de los servicios. Se presentan propuestas sujetas a autorización; los tests verdes no certifican aptitud fiscal o productiva.

Entregables: [auditoría](tpv-phase3-block-e-audit.md), [escenarios E01–E22/N01–N12](tpv-phase3-block-e-scenarios.md), [hallazgos/propuestas](tpv-phase3-block-e-findings.md), [mediciones y estados](tpv-phase3-block-e-measurements.json), este informe y [revisión global A–E](tpv-phase3-final-review.md).

## Dieciséis respuestas

1. **F1/F2 frente a Sale:** coinciden líneas, bases, descuentos, cuotas y totales en las fixtures EUR ensayadas, con tipos/series y snapshots correctos. Hay una discrepancia de moneda configurable: el perfil USD se acepta y se imprime€. El comando independiente Billing también puede emitir completed/unpaid; se comprueba por HTTP y la Sale sigue unpaid. Checkout conserva su gate paid. La política comercial independiente/crédito debe aceptarse explícitamente, no se presupone por estos tests.
2. **Impuestos y redondeos:** correctos en los vectores del contrato implementado: Decimal, redondeo por línea HALF_UP y suma de cuotas ya redondeadas por clasificación. Se prueban1/20/50 líneas,0/4/10/21%, cantidades fraccionarias y descuentos. No se acredita toda fiscalidad española; regímenes/exenciones/recargos no soportados se rechazan.
3. **Duplicación inicial concurrente:** no ocurre por los servicios/HTTP ensayados, incluyendo dos usuarios y claves iguales/distintas. La protección depende de Sale lock y exclusión del servicio; una inserción bulk/SQL fuera de él puede crear otro inicial con número distinto. No se oculta esa diferencia ni se aplica unique universal de Sale que rompería F3/rectificativas.
4. **Numeración:** sin colisiones en carreras y con rollback de contador/hijos/documento/auditoría ante los fallos probados. La unicidad serie/número sí es constraint PostgreSQL. Se prueba lock_timeout real55P03 y terminación de la conexión emisora propia. No se promete consecutividad universal ni inmunidad ante escritores privilegiados externos.
5. **Snapshots:** conservados tras cambios de producto/precio/impuesto y emisor/receptor actuales después de emitir. Product/Tax se congelan en SaleLine; emisor/receptor al primer issue. La moneda no tiene snapshot documental. Logo/marca/pie actuales pueden cambiar como branding, sin sustituir identidad fiscal histórica.
6. **Billing falla después del pago:** Payment y stock previos permanecen; T3 fallida revierte documento, hijos y número. P01 informa que el cobro existe, mantiene identidad y recupera emisión cuando se repara la causa fiscal. No hay reembolso ni recobro automático.
7. **P01/P02 hasta imprimir:** validados de nuevo. P01 incluye método histórico inactivo, errores fiscales visibles y reparación antes de imprimir. P02 ejecuta sus12 variantes de cash/card/parcial/respuesta perdida/cierre en1440/820/390, conserva sesión histórica, imprime y crea otra venta en sesión válida. No se reimplementan.
8. **Impresión/reimpresión:** lecturas del documento issued; no avanzan número, emiten otro documento ni crean pago/stock/caja. Se comparan filas/digests/estados antes/después. F2 virtual80mm y F1 A4 se renderizan a PDF con todas las líneas; cancelación es stub sin papel, no diálogo ni impresora física. Se prueban imagen local retenida/fallida y popup automático realmente bloqueado.
9. **Timeout/pérdida posT3:** la respuesta no determina rollback. Se conserva resultado desconocido y se consulta; si existe documento, GET muestra éxito con el mismo número, sin otro POST económico. Se vuelve a ejecutar pérdida trasT1/T2/T3, timeout/abort y500 de render posterior a commit.
10. **VeriFactu:** no hay integración externa ejecutable en el repositorio. Billing ISSUED es interno y SHA256 es fingerprint de idempotencia. No se generan/enlazan huellas fiscales ni se envían registros; no hay QR/ACK/cancelación oficial implementados. Es una dependencia de especificación/legalidad del producto según los negocios y obligaciones aplicables.
11. **Latencia/SQL:** mediana T3 F2 de1/20/50 líneas: **51,73/150,59/316,87ms**,85/221/431 operaciones SQL. F1:53,93/136,64/266,44ms y87/223/433. Predominan validaciones/FK/unique por hijo y savepoints. Render de impresión warm: aproximadamente0,98–3,88ms; GET Client completo y selectores se miden aparte. No se optimiza ni se atribuyen los20s originales.
12. **Seis fallos de catálogo:** reproducidos antes (6 FAIL,7,41s) y corregidos solo en tests/fixtures. Los tres módulos pasan44 pruebas; pytest completo pasa **1604 pruebas y525 subtests**, con un warning Django60. Se conservan/refuerzan rechazo de impuesto inactivo, aislamiento, unicidad del default, acciones de ciclo de vida y limpieza de medios.
13. **Correcciones:** slugs sintéticos únicos, fixture de desactivación posterior a relación válida, ruta real de helper de imagen y expectativa del formulario actual; dos tests nuevos impiden debilitar sus guards. El E2E Billing admite Chromium instalado mediante variable opcional. No se encontró un defecto de impresión que exigiese editar sus plantillas/CSS/JS en este bloque.
14. **Requieren autorización:** E-P01 para límite EUR y tratamiento del legado monetario; E-P02 para endurecimiento de historia/exclusión inicial en BD; E-P03 para ampliaciones/integración fiscal; E-P04 si una optimización cambia validaciones/servicios. Cualquier cambio de política de emisión antes del pago debe definirse aparte.
15. **Riesgos para beta/producción:** configuración monetaria incoherente; cobertura fiscal limitada e integración externa ausente cuando sea necesaria; garantías de modelo frente a SQL privilegiado; política independiente/crédito por aceptar; falta de staging representativo, hardware/driver físico y evidencia del incidente productivo. La matriz global distingue beta sintética, beta de negocios y producción, sin aprobarlas por defecto.
16. **Cierre Fase3:** la auditoría técnica A–E queda completada con resultados y reservas explícitos. El cierre funcional para habilitar negocios reales debe resolver o aceptar formalmente las propuestas y dependencias relevantes. El merge y cualquier publicación siguen siendo decisiones/autorizaciones posteriores.

## Archivos del incremento E

Modificados, exclusivamente tests:

- `apps/catalog/tests/test_tax_resolution.py`.
- `apps/catalog/tests/unit/test_forms.py`.
- `apps/catalog/tests/unit/test_services.py`.
- `e2e/browser_billing.py`.

Nuevos: `tests/performance/phase3_billing_audit.py`, `e2e/browser_billing_phase3_e.py` y los seis entregables listados arriba. No se modifican modelos, servicios, formularios o vistas de aplicación, selectores, snapshots, impuestos, locks, numeración, idempotencia, transacciones, migraciones, dependencias, configuración productiva ni VeriFactu. Las tres excepciones del manifiesto inicial de422 archivos son los tests de catálogo autorizados; los otros419 permanecen idénticos. B/C/P01/P02/D se conservan sin cambios.

## Pruebas realizadas

| Ejecución | Resultado |
|---|---|
| Seis casos originales antes de editar |6 FAIL,7,41s; errores de fixture/expectativa/import, no se presumen solo por D |
| Tres módulos de catálogo tras corregir |44 PASS,8,03s; incluye dos aserciones de seguridad nuevas |
| Billing+Sales+Payments+CashRegister+Inventory completos |**752 PASS,165,665s**, PostgreSQL real; incluye concurrencia, F3/rectificación/series/impresión y P01/P02 |
| Matriz nueva integridad final |9 métodos PASS,17,061s;32 registros de subcasos, con carreras×3 y fallos durables |
| Refuerzo del oráculo de grupos fiscales |1 método ya incluido en matriz, repetido con más aserciones; PASS,4,720s |
| Sonda moneda no EUR |1 PASS,0,796s como reproducción; **defecto confirmado**, no corrección del comportamiento |
| Sonda HTTP emisión independiente unpaid |1 PASS,0,748s; comportamiento confirmado, política pendiente de aceptación |
| Medición T3 final aislada |1 método PASS,26,260s;6 celdas×5 muestras+warmup, lectura previa de selección fuera del temporizador |
| Medición lectura/render de impresión |1 método PASS,6,164s;6 celdas×5 GET warm+warmup,10 SQL por GET en cada celda |
| Total métodos nuevos explícitos de auditoría |13 métodos únicos validados; no suman repeticiones ni confunden muestras con métodos |
| E2E Billing/checkout/recuperación, lote inicial |34 métodos,309,634s:33 PASS y1 FAIL de suposición del arnés sobre popup; no se declara ese lote verde |
| Popup con bloqueo real sin activación |1 PASS,10,905s; el nuevo escenario conserva una pestaña/cero GET y comprueba window.open=null |
| Logo local retenido y abortado |1 PASS,7,546s; autoprint0 antes y1 después, sin mutación |
| Total E2E actual validado |**35 métodos únicos** =33+1+1. Incluye5 de Billing visual,26 de checkout/UX/recuperación y4 nuevos E |
| Comparación económica con D |**38/38 coinciden**, sin cambiar estados/importes; se normaliza orden de listas y se excluyen HTTP/duraciones |
| Pytest completo |**1604 PASS,525 subtests PASS,151,37s**,1 warning sobre cambio futuro de URLField/Django60;0 FAIL |
| Ruff check / format |PASS;471 archivos formateados |
| Django check / makemigrations --check --dry-run |PASS; sin incidencias/sin cambios de esquema |
| Sintaxis JS de impresión y diff whitespace |PASS |

Los13 métodos nuevos se ejecutaron por clases/casos explícitos en los lotes indicados. El archivo `phase3_billing_audit.py` no coincide con el patrón automático test_*.py de pytest; su cobertura nueva se acredita por esos comandos, sin atribuírsela al contador1604. Los descubrimientos Django/pytest se solapan y no se suman.

Los primeros intentos se conservan separados: PG todavía no listo antes de readiness; dos errores del helper de fixture por elegir una serie sin desambiguar al crear alternativas; el flag de popup que no bloqueó una apertura con gesto de usuario. No eran regresiones fiscales. La selección final de la serie BASE-* del fixture y el bloqueo real se comprueban sin debilitar aserciones. Un primer recolector incluía la lectura auxiliar de serie antes de la T3; se reubicó fuera del intervalo y se volvió a medir. Solo el recolector final alimenta la tabla siguiente.

## Mediciones finales

Una sesión por matriz, datos sintéticos y runners propios secuenciales sobre PostgreSQL16.15, sin tracing de B ni producción. Cada celda usa un warmup y cinco medidas. Setup, completar/pagar, elegir la serie y generar UUID quedan fuera de T3. La llamada real a `issue_sale_document` incluye salida de atomic/commit. Los wrappers de etapas/full_clean son opt-in y se restauran tras cada muestra; no se midió overhead ON/OFF, por lo que no se supone nulo. No se calcula p95 con n5 ni cold start.

| Tipo/líneas | T3 mediana [mín–máx] ms | SQL total mediano | Primer GET Client tras emitir ms |
|---|---:|---:|---:|
| F2/1 |51,73 [49,77–53,94] |85 |50,69 |
| F2/20 |150,59 [128,34–313,13] |221 |51,84 |
| F2/50 |316,87 [244,67–455,28] |431 |58,99 |
| F1/1 |53,93 [51,32–56,89] |87 |51,82 |
| F1/20 |136,64 [131,47–145,11] |223 |53,32 |
| F1/50 |266,44 [252,72–305,80] |433 |50,35 |

La sonda separada de reimpresión warm sobre el mismo documento:

| Tipo/líneas | GET Client completo mediano ms | Render del view mediano ms | SQL/GET |
|---|---:|---:|---:|
| F2/1 |29,23 |1,03 |10 |
| F2/20 |26,31 |1,83 |10 |
| F2/50 |35,37 |3,88 |10 |
| F1/1 |25,77 |0,98 |10 |
| F1/20 |25,67 |1,82 |10 |
| F1/50 |32,02 |3,48 |10 |

Client GET incluye middleware/permisos/selectores/render; no es tráfico de navegador ni tiempo de impresora. El render medido envuelve el render real del view. En F2/50, spans inclusivos medianos: snapshots de líneas2,22ms; full_clean de líneas216,17ms; creación de hijos261,83ms; lock de serie0,92ms; auditoría4,03ms. No se suman spans superpuestos. Top SQL:64 SAVEPOINT y64 RELEASE,59 SELECT documento,56 SELECT Business,51 SELECT SaleLine,50 INSERT y50 SELECT de línea fiscal. Agrupar por primer identificador no sustituye EXPLAIN ni identifica todos los joins.

Las referencias B54/139/289ms son históricas y usan otro arnés. No se presenta este rango variable como una mejora/regresión causal. Sigue sin demostrarse la causa de los20s productivos. No se eliminan validaciones para reducir contador SQL.

## Reproducción

Utilizar un PostgreSQL nuevo desechable, sin datos reales. Aquí: `tpv-phase3-e-postgres`, etiqueta `codex.task=tpv-phase3-e`, --rm, puerto solo127.0.0.1:55441, base sintética `tpv_diag_phase3e`. Nunca DATABASE_URL de producción. Se verificó readiness real antes de los lotes finales. El runner crea/destruye `test_tpv_diag_phase3e`.

```bash
export SECRET_KEY=phase3-e-synthetic
export TPV_TEST_DATABASE_URL=postgresql://postgres@127.0.0.1:55441/tpv_diag_phase3e
export DJANGO_SETTINGS_MODULE=config.settings.diagnostic_postgres
export TPV_DIAGNOSTICS=0
export TPV_CHROMIUM=/usr/bin/chromium
export TPV_BILLING_E_OUTPUT=/tmp/billing-e-integrity.json
.venv/bin/python manage.py test tests.performance.phase3_billing_audit --noinput
.venv/bin/python manage.py test apps.billing apps.sales apps.payments apps.cash_register apps.inventory --noinput
.venv/bin/python manage.py test e2e.browser_billing_phase3_e e2e.browser_billing e2e.browser_checkout_authorized e2e.browser_checkout_recovery e2e.browser_checkout e2e.browser_htmx_global_ux --noinput
.venv/bin/python -m pytest --ds=config.settings.diagnostic_postgres -q
.venv/bin/ruff check .
.venv/bin/ruff format --check .
.venv/bin/python manage.py check
.venv/bin/python manage.py makemigrations --check --dry-run
```

Los comandos completos actuales incluyen los suplementos añadidos durante E; los lotes efectivamente ejecutados se desglosan en la tabla/JSON, sin afirmar una única ejecución conjunta verde inexistente. Usar salidas distintas por runner. `TPV_INTEGRITY_OUTPUT` recoge evidencia de recuperación existente; `TPV_BILLING_E_ARTIFACTS` permite dirigir PDFs a scratch. No se instala ninguna dependencia. Los PDF usan pdfinfo/pdftotext disponibles y Chromium del sistema.

## Limitaciones, limpieza y Git

No se valida impresora/driver/papel físico ni diálogo nativo de cancelación; se usan print CSS, PDF y stub. No se prueba Safari/Firefox, hardware móvil real, AEAT/proveedor externo, carga productiva, cola/locks del incidente original, caída física del servidor o resistencia a un administrador DB. Se termina una conexión propia de una BD de test, no un worker/servidor real de producción. Los casos de impuestos se limitan al contrato vigente; no son dictamen legal. El fallback de journal en memoria no sobrevive recarga con storage bloqueado.

Al reanudar tras reinicio del entorno, el contenedor inicial --rm ya no estaba. Se conservaron logs/artefactos y se crearon instancias desechables nuevas para lo pendiente. No se repiten como nuevas las752 pruebas ya terminadas. En la limpieza final se comprueban cero clientes ajenos al lector y cero bases test pendientes, etiqueta/auto-remove, stop del contenedor propio y desaparición posterior. Los servidores de prueba y contextos del navegador de estas ejecuciones se cierran. Scratch conserva evidencia, sin versionar PDFs o logs.

Estado final:4 archivos existentes de tests modificados y8 nuevos (dos módulos de pruebas y seis entregables). Nada staged ni publicado. Se comprueban paths previstos, diff, manifiesto protegido, secretos y ausencia de migraciones nuevas. El SHA permanece ad110fe. La corrección monetaria y el endurecimiento de BD requieren autorización posterior conforme al apartado16 del encargo E.
