# NETXODO — Fase 3: revisión global A–E

30/10/2026 (Europe/Madrid). Rama `fix/tpv-checkout-audit-phase3`, base actual publicada `ad110fe46b777bf7522444ed72353fdba5177128`, más la entrega E y E-P01, incorporada a un commit local por autorización posterior; sin push. La auditoría A–E queda documentada y ejecutada dentro de su alcance. La aprobación de beta con negocios reales o producción **no se deduce de ese cierre**: quedan decisiones y correcciones de dominio enumeradas abajo.

## Continuidad y resultados por bloque

| Bloque | Trabajo y resultado acreditado | Estado actual |
|---|---|---|
| A | Auditoría de flujo, permisos, T1/T2/T3, Billing/impresión;99 casos aislados SQLite; identificación H01/timeout/recuperación y límites de medición | Completado como análisis inicial. No prueba locks PostgreSQL ni causa de20s |
| B | PostgreSQL/Gunicorn/Chromium,84 muestras warm/12 celdas; costes por línea, full_clean, locks controlados, estados parciales y render poscommit | Diagnóstico completado; sin optimizaciones Inventory/Billing ni causalidad productiva demostrada |
| C | Integridad concurrente/identidad/38 snapshots, fronteras T1/T2/T3, journal/GET antes de retry, errores visibles, casos de pérdida/500 | Correcciones frontend e integridad validadas. Sus propuestas P01/P02 entonces pendientes fueron autorizadas después |
| P01 | Recuperación solo emisión por estado y saldo persistidos; método histórico inactivo no genera nueva intención Payment; identidad documental y fiscalidad revalidadas | Implementada y publicada; E vuelve a probarla, incluyendo error fiscal visible, reparación e impresión |
| P02 | Recuperación explícita de partes pendientes en sesión válida, sin mover pagos/historia ni reabrir caja; saldo persistido e identidad de cada parte | Implementada y publicada; E repite12 variantes de navegador, concurrencia/cierres y flujo hasta imprimir/nueva venta |
| D | Propiedad del panel HTMX, respuestas obsoletas/solicitudes incompatibles, foco/ARIA, cambio P02, login HTML y cierre nativo tardío;85 métodos E2E validados | Publicado en ad110fe. Sus seis fallos previos de pytest fueron correctamente documentados, y E los resuelve dentro de autorización de tests |
| E | Billing/F1/F2/series/numeración/snapshots, redondeos independientes, PostgreSQL/fallos/terminación propia, impresión/PDF, rendimiento y clasificación de tests | Auditoría completada;752 financieras,35 E2E únicos y1604 pytest PASS. Moneda no EUR y límites de BD quedan explícitos, sin cambios fiscales no autorizados |
| E-P01 | Restricción autoritativa a EUR en configuración y escrituras monetarias; bloqueo del legado no EUR, avisos de lectura/reimpresión y recuperación documentada | Implementada y validada localmente:1619 pytest/533 subtests,1133 regresión/sondas y37 E2E PASS; contadores solapados. Recuperaciones no EUR pendientes. [Informe E-P01](tpv-phase3-e-p01-report.md); sin publicación |

Los contadores pertenecen a runners/bases y fases diferentes, con solapamientos. No se suman como una cantidad de pruebas únicas de la aplicación. Los informes históricos se conservan; sus estados pendientes no sustituyen implementaciones posteriores. No se mezclan muestras de Gunicorn B, frontend D y T3 directa E para fabricar una comparación de velocidad.

## Completado y validado

- Checkout ordinario cash/card/split, F1/F2, estado autoritativo y acciones de impresión/nueva venta en los escenarios ejecutados.
- P01 y P02 preservan Payment confirmado, stock e historia de caja; la emisión sigue siendo una etapa separada con validaciones fiscales.
- Recuperación tras pérdida de respuesta, timeout/abort y error de render poscommit mediante consulta antes de replay; sin cobros automáticos repetidos.
- Carrera de misma venta/claves iguales/distintas, dos usuarios, dos ventas/serie y última unidad de inventario en los lotes documentados. No se demuestra sobrepago ni doble efecto por esas rutas.
- Numeración por servicio con Sale→Series lock y unicidad real de serie/número; rollback de T3 devuelve contador/filas/auditoría, incluso ante55P03 o cierre de la conexión emisora propia.
- Datos fiscales de líneas/grupos/totales y snapshots después de emitir, reimpresión con lectura sin efectos nuevos y separación de branding mutable.
- Los38 snapshots económicos comparados C/P01/P02/D/E coinciden tras normalizar orden y excluir HTTP/tiempos. Los importes y estados no se reemplazan para lograr coincidencia.
- En E se repararon seis tests/fixtures de catálogo, con dos pruebas adicionales de guards; su pytest completo pasó1604 pruebas y525 subtests. E-P01 conserva esos archivos y añade las comprobaciones monetarias autorizadas.
- La repetición E-P01 confirma38/38 escenarios y54/54 registros EUR iguales a E; mantiene importes, estados, Payments, caja, stock y numeración.
- E-P01 bloquea configuración nueva no EUR y nuevas escrituras económicas de perfiles históricos no EUR. No convierte importes ni cambia monedas, documentos o claves históricas; la recuperación de pendientes no EUR requiere una propuesta adicional.

## Corregido dentro de las autorizaciones

A/B aportaron auditoría/diagnóstico. C/D corrigieron presentación, recuperación y coordinación de navegador. P01/P02 corrigieron el comportamiento funcional bajo su autorización posterior. E corrige únicamente fixtures/tests obsoletos y el selector opcional del Chromium de prueba; añade evidencia y documentación. No cambia fórmulas, numeración, snapshots, modelos, locks ni transacciones.

La autorización posterior E-P01 sí añade guards monetarios en modelos/servicios, validación del perfil y avisos en consultas, impresión y exportación. Mantiene fórmulas, fiscalidad, numeración, hashes, UUID y fronteras transaccionales. No optimiza Billing/Inventory ni introduce migraciones. [Implementación y recorrido de entradas](tpv-phase3-e-p01-implementation.md).

## Confirmado y pendiente de decisión/autorización

| Tema | Evidencia | Decisión requerida |
|---|---|---|
| Legado no EUR y moneda documental no verificable | E-P01 rechaza nuevas configuraciones no EUR y escrituras incompatibles; documentos anteriores siguen sin snapshot de moneda | Propuestas concretas de recuperación de ventas parciales/documentos pendientes, sin relabel ni conversión. Cualquier transformación histórica requiere autorización adicional; multimoneda sigue fuera de alcance |
| Inmutabilidad/exclusión inicial fuera del servicio | bulk/SQL pueden alterar issued/hijos e insertar otro F2 con número distinto; guards y unique serie/número sí funcionan en su ámbito | E-P02: política de writers/roles y posible defensa DB. Respetar F3 y rectificativas legítimas; requiere aprobación de modelos/migraciones si se elige |
| Emisión independiente antes de pago | Comando Billing acepta completed/unpaid; checkout exige paid; una Sale puede tener documento y seguir unpaid | Aceptar/definir política de facturación independiente/crédito. Cambiar el gate del servicio no está autorizado en E |
| Cobertura fiscal de producto | IVA/régimen01/S1; exenciones/recargos/otros tratamientos rechazados | Definir negocios y operaciones admisibles; ampliaciones requieren especificación y autorización fiscal |
| VeriFactu/proveedor/registro externo | No hay integración, envío/ACK/huella fiscal/cancelación; ISSUED solo interno | Determinar requisitos legales aplicables y diseñar integración si procede. No usar fingerprint como huella ni QR ficticio |
| Coste por línea y validaciones | E vuelve a medir crecimiento de full_clean/hijos; B ofrece descomposición histórica | E-P04 y anteriores P03/P04 de rendimiento: equivalencia antes de optimizar, sin omitir validaciones ni cambiar límites transaccionales por rapidez |

No se demuestra que una vista pública permita saltarse guards mediante bulk/SQL. El hallazgo de BD es un límite frente a writers fuera de los servicios y privilegios, que debe evaluarse con un modelo de amenaza y rol definido; no una afirmación de compromiso remoto. El defecto de moneda se alcanzaba mediante formulario/servicio ordinarios en E; E-P01 cierra esas escrituras de aplicación. El límite frente a SQL/bulk y los documentos históricos ambiguos permanecen explícitos.

## Hipótesis no demostradas y riesgos productivos

La causa del incidente original de unos20s sigue sin traza productiva correlacionada. La pausa artificial de B es una inyección conocida, no prueba de locks/cola/cold-start concretos del comercio. No se atribuye a Inventory, Billing, PostgreSQL, Render o HTMX sin esa evidencia. Las mediciones locales pequeñas no establecen p95, capacidad bajo carga ni comportamiento de WAN/pooler/workers efectivos.

T1/T2/T3 separados admiten estados parciales por diseño. La UI ya tiene recuperación; sigue siendo necesario un procedimiento operativo de consulta/reparación y formación del cajero. El journal por pestaña no sustituye la autoridad del servidor; memoria de respaldo no sobrevive recarga con storage bloqueado. Permisos/configuración/caja pueden cambiar y rechazar un replay.

No se ha verificado impresora térmica o convencional física, drivers/cortes, navegador distinto de Chromium, hardware móvil real ni toda combinación de accesibilidad. E verifica PDF A4/80mm virtual, texto completo, logotipo local y su fallo; no envío fiscal externo ni cancelación física del diálogo.

## Matriz de preparación

| Destino / criterio | Evidencia actual | Estado recomendado |
|---|---|---|
| Auditoría técnica Fase3 | A–E documentados y pruebas descritas, con fallos/limitaciones explícitos | Completada como auditoría con reservas |
| Revisión de integración de rama a main | Rama revisable, pytest/lint verdes, P01/P02/D publicados; E y E-P01 locales | Preparada para revisión humana del diff y propuestas. Sin autorización automática de merge/PR |
| Beta interna con datos ficticios | Flujos probados, sin cobros/envíos reales | Base técnica disponible dentro del entorno de prueba |
| Beta con negocios reales EUR y fiscalidad soportada | Gate EUR implementado en E-P01; siguen pendientes revisión del legado, aceptación fiscal/política independiente y staging representativo | Condicionada; no aprobar por defecto |
| Negocios multidivisa | E-P01 bloquea configuración nueva no EUR y nuevas operaciones de perfiles no EUR, sin convertir historia | Bloqueados para nuevas operaciones; soporte multimoneda y recuperación histórica requieren diseño/autorización adicionales |
| Operaciones con impuestos no soportados | Billing rechaza esos tratamientos, puede quedar paid/documento pendiente | No habilitar esos casos como soportados sin especificación/cambio autorizado |
| Negocios que requieran integración fiscal externa | Funcionalidad no implementada ni verificada legalmente | Bloqueada para ese modo hasta satisfacer requisitos aplicables |
| Producción | Faltan aceptación de hallazgos, requisitos fiscales, staging representativo y hardware/procedimientos de operación | No aprobada en esta auditoría |

Esta matriz separa revisión de código de autorización para operar con dinero/datos reales. La exigencia jurídica concreta corresponde a una revisión competente por negocio y calendario; no se inventa certificación oficial.

## Acciones siguientes propuestas

1. Revisar el diff autorizado E-P01 y sus pruebas. Antes de habilitar negocios reales, inventariar perfiles/pendientes en un entorno expresamente autorizado y presentar propuestas individuales de recuperación no EUR, sin cambiar monedas ni documentos históricos.
2. Decidir política de emisión independiente y nivel de defensa frente a writers SQL; aceptar explícitamente el riesgo actual o autorizar E-P02 con diseño F3/rectificaciones.
3. Definir alcance fiscal y dependencias externas con asesoría; autorizar únicamente cambios concretos derivados de esa especificación.
4. Validar en staging autorizado configuración efectiva, tiempos correlacionados, procedimientos de recuperación y dispositivos de impresión reales antes de habilitar negocios.
5. Revisar el diff completo y decidir publicación/PR/merge en una autorización posterior. No se ejecuta ninguna de esas acciones por este cierre.

Los artefactos E y comandos están en [informe E](tpv-phase3-block-e-report.md) y [mediciones](tpv-phase3-block-e-measurements.json). La entrega E-P01 se documenta por separado en su [informe](tpv-phase3-e-p01-report.md). La base de validación permanece ad110fe; E/E-P01 se incorporan a un commit local autorizado posteriormente. No se incorpora main ni se realiza push. PostgreSQL de pruebas se retira tras comprobar cero clientes ajenos/cero bases de test; los logs sintéticos se conservan en scratch.
