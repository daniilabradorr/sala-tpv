# NETXODO — Fase 3, Bloque E: auditoría fiscal y documental

Trabajo iniciado el29/10/2026 y reanudado el30/10/2026 (Europe/Madrid). Base `ad110fe46b777bf7522444ed72353fdba5177128`, rama `fix/tpv-checkout-audit-phase3`, inicialmente limpia. HEAD local/remoto comprobados; main observado `cdbf88c7df6b5c9d75ccdeda84c8ac8b67b03983`, sin incorporarlo. P01/P02 están implementadas y D publicado. No se reimplementan ni se reinterpretan como pendientes.

Se consultan A, B diagnóstico/hallazgos, C integridad/escenarios, implementaciones P01/P02, su informe conjunto y D auditoría/E2E/informe, junto con `apps/billing/README.md`. Los resultados previos conservan su SHA y procedencia; no se cuentan como ejecuciones nuevas de E. No se localizaron documentos maestros DOCX de backend/frontend ni se inventa su contenido.

Fuentes inspeccionadas: modelos/servicios/selectores/vistas/formularios/URLs y tests de Billing; `apps/sales/{checkout,forms,views,models,services}.py`; Payments y CashRegister; configuración fiscal/moneda y formularios de BusinessProfile; Catálogo, Customer y Audit; plantillas Billing de detalle/comandos/impresión y sus partials; `static/css/pages/billing-print.css` y `static/js/pages/billing-print.js`. Se contrastan F1/F2/F3, rectificativas, fechas, permisos, snapshots y fronteras reales. La [matriz](tpv-phase3-block-e-scenarios.md), los [hallazgos](tpv-phase3-block-e-findings.md) y las [mediciones](tpv-phase3-block-e-measurements.json) aportan pruebas y límites.

## Modelo y contrato real

| Área | Implementación | Garantía y alcance |
|---|---|---|
| Documento | `BillingDocument`, tipos F1/F2/F3/R1–R5; estados draft/issued | Emitido requiere forma documental/fecha/número/identidad; no hay estado interno «enviado a AEAT», «accepted» ni «cancel». |
| Relaciones | Business/Store obligatorios; Sale/Return/Customer/caja/sesión según ruta | `clean()` valida coherencia tenant/tienda/caja; servicios y selectores vuelven a filtrar ámbitos. No equivale a FK compuesta de tenant en BD. |
| Serie | Business, tipo, prefijo, año, tienda/caja opcionales, padding, contador | Única Business/prefix/year. Counter≥0 y padding>0 en BD; identidad de serie usada inmutable por save/servicio. Nombre y actividad administrativos permanecen editables. |
| Selección | `active_billing_series`, `IssueSaleDocumentForm`, candidato y lock autoritativo | Empresa, tipo, año local, tienda y caja compatibles. Serie global puede aplicar; una de otra tienda/caja no. Una candidata se presenta oculta; varias exigen elegir. No reserva número al GET. |
| Emisión | `issue_sale_document`, atomic T3, Sale lock antes de serie | Estado completed, permiso actual, cliente F1, validaciones/snapshots, exclusión inicial y número bajo locks. El servicio Billing directo admite completed no necesariamente pagada; los tests históricos lo usan para facturación independiente. Checkout/P01 exigen saldo confirmado cero antes de emitir. Son entradas distintas, no un cambio realizado por E. |
| Permisos | Usuario activo/autenticado, Business y `can_sell_in_store`; lectura con StoreAccess | Emisión exige vender; imprimir solo lectura autorizada. Un UUID conocido no evita revalidar permiso. Objetos ajenos se rechazan. |
| Idempotencia | UUID por Business y fingerprint canónico SHA256 | Intención incluye operación/Sale/tipo/serie; F3 y rectificación tienen payload propio. Misma intención retorna documento; misma clave incompatible da conflicto. Claves distintas no autorizan dos iniciales en el servicio. |
| Constraints | UUID Business/key y serie/número únicos, forma draft/issued, número positivo | Protección real de colisión; no hay unique universal de documento inicial por Sale ni trigger de inmutabilidad. F3/rectificaciones legítimas impiden imponer sin diseño un único documento de cualquier tipo por Sale. |
| Snapshots | Campos emisor/receptor, líneas y desglose, importes, fechas, serie_text/number | Product/Tax se congelan primero en SaleLine; Billing copia esa historia. Emisor/receptor se toman al emitir por primera vez. Modificarlos antes de emitir no reconstruye una identidad fiscal anterior que Sale no guarda. Tras emisión se reimprimen snapshots. |
| Inmutabilidad | Guards save/delete de documento, hijos, relaciones y serie usada | No son triggers PostgreSQL. QuerySet.update, bulk y SQL pueden saltarlos; las pruebas aisladas lo demuestran y revierten esos cambios. Se documenta el límite, sin modificar historia real ni modelos. |
| Auditoría | `log_event` después de asignar número, dentro de T3 | Error de auditoría revierte documento/hijos/contador/evento de T3. Payment/Inventory anteriores permanecen. Replay compatible no añade otro evento de emisión. |
| Impresión | GET issued con documento tenant/store y relaciones precargadas | Lee snapshots, no llama emisión. Vista rechaza borrador, ID inexistente/ajeno y métodos mutantes. Branding/logo/pie actuales son presentación; identidad fiscal viene del documento. |

`full_number` usa series_text y number históricos, con padding de la serie precargada. El selector de impresión la carga; la identidad/padding no puede cambiar por save después de emitir. Las escrituras bulk ajenas al contrato también pueden vulnerar esa protección. La consulta de detalle precarga líneas/desgloses/relaciones; tests comprueban cero consultas adicionales al iterar/renderizar esas colecciones precargadas.

## Fiscalidad y redondeo

Sales normaliza quantity a tres decimales y precio/descuento/tipo monetario a dos, con Decimal y ROUND_HALF_UP. La fórmula por línea implementada es:

```
bruto = round2(precio_base × cantidad)
base = round2(bruto − descuento_absoluto)
cuota = round2(base × tipo / 100)
total = round2(base + cuota)
```

Billing vuelve a comprobar los importes históricos de cada línea y sus sumas contra Sale. No acepta coherencia solo por tener un total igual. Su grupo fiscal utiliza toda la clasificación: impuesto/tipo, régimen, calificación, exención y recargo. El desglose **suma bases/cuotas por línea**; no vuelve a gravar la base agregada. Dos bases0,05 al10% generan0,01+0,01 de cuota por el contrato actual, aunque gravar0,10 agregado produjese0,01. La prueba añade precio1,01×0,500, cantidad1,125, descuentos0,03/0,01/0,25 y tipos0/4/10/21%; oráculo explícito: bruto16,25, descuento0,29, base15,96, cuota2,74, total18,70. Se comparan líneas y los cuatro grupos, no solo total.

El alcance de emisión soportado se limita a IVA, régimen01 o vacío compatible, S1 o vacío, sin exención ni recargo. El catálogo puede describir tratamientos más amplios; Billing los rechaza mediante `BillingUnsupportedFiscalCase`. Esto puede suceder después de Payment, dejando emisión pendiente. No se elimina esa validación para evitar el estado parcial. Deben delimitarse los casos fiscales admitidos antes de operar con negocios reales.

La resolución previa de impuesto usa específico activo → predeterminado activo del mismo Business → error controlado. No usa el `default_tax_rate` legado del perfil como fallback. El impuesto específico desactivado provoca error al resolver una operación nueva; desactivarlo después de vender no reescribe SaleLine/BillingDocumentLine. E corrige fixtures que impedían llegar a esas aserciones, sin alterar el resolver.

Las comprobaciones de identidad fiscal son las del código: emisor con campos no vacíos y receptor nacional con identificador o extranjero con tipo/número. No se prueba validez legal del NIF ficticio, toda obligación por operación ni conformidad normativa española. La moneda se analiza separadamente en hallazgos; no se asume soporte multidivisa por existir `BusinessProfile.currency_code`.

## Numeración, atomicidad y recuperación

El orden normal es Sale lock → decidir/revalidar → borrador y líneas → lock BillingSeries → current_number+1 → issued → Audit → commit T3. No se usa secuencia PostgreSQL independiente para el número fiscal. Un rollback de esta transacción revierte su incremento. Esto no promete consecutividad universal ante escritores fuera del servicio, mantenimiento o reglas legales no evaluadas.

N01–N12 cubren misma serie/diferentes ventas, misma venta/dos usuarios, claves iguales/distintas/incompatibles, fallos antes/después del número, respuesta perdida, serie inactiva, dos empresas, cambio de año y serie ajena a tienda/empresa/caja. Las carreras nuevas repiten tres planificaciones con barrera; no agotan todas las posibles. Se verifica contador/documentos/eventos y los efectos previos, no solamente códigos HTTP.

Se inyectan fallos de emisor, líneas ya creadas, clasificación fiscal, adquisición de serie, número ya asignado y auditoría ya escrita. Se añade lock_timeout real PostgreSQL con SQLSTATE55P03 al alcanzar `_lock_series`, y terminación **del PID de la conexión emisora propia** después de asignar número antes de commit. Todas las operaciones son sintéticas y test-only. La prueba exige current_database con prefijo test_tpv_diag_; no termina otra conexión. La transacción T3 se revierte, mientras Payment1/stock previo sobreviven; después se recupera explícitamente con la identidad prevista.

P01 se ensaya con método histórico inactivo y errores de serie/perfil/cliente. El error fiscal no autoriza otro Payment. El procedimiento es consultar estado, corregir configuración/identidad con permiso, releer checkout y reintentar emisión; se conserva UUID, Payment e Inventory. Cuando ya existe documento, replay compatible también lo encuentra con serie histórica inactiva o en otro año; un documento pendiente exige serie válida del año real de emisión. No se cambia de serie/fecha silenciosamente.

P02 se vuelve a ejecutar hasta impresión y nueva venta con las variantes autorizadas: parte histórica confirmada, cierre, selección explícita de sesión válida, cash/card, pérdida de respuesta parcial y cierre tras T1. Sale y documento conservan sesión histórica; solo el nuevo Payment/CashMovement permitido se asocia al destino. Se recalcula saldo persistido y no se repite lo confirmado.

Un HTTP500 por render posterior a T3, timeout o pérdida de respuesta no niega el documento. La UI conserva intención/resultado desconocido y consulta por GET. Si T3 está confirmada, el GET muestra éxito y se imprime el mismo documento sin otro POST. Los escenarios de recuperación C y P01/P02 se ejecutan nuevamente en E.

## F3, rectificativas y anulación

F3 sustituye una F2 existente mediante relación SUBSTITUTES, receptor fiscal válido y snapshots de líneas originales. No forma parte de la primera emisión F1/F2 del checkout ni es un «segundo inicial» accidental. El servicio impide sustituir dos veces la misma F2 bajo lock de Sale. Una devolución completada genera R1 para F1 o R5 para F2, método I/diferencias y relación RECTIFIES; conserva fuente SaleLine/Return y fecha de operación del original. En historia F2→F3 puede requerirse una F3 complementaria de la R5, con clave derivada UUID5 y validación de relación/receptor.

La asignación parcial fiscal reconstruye devoluciones históricas en orden y busca céntimos que satisfagan importe/base/cuota, sin superar residuos. La última parte consume el residuo consistente; casos no representables/ambiguos se rechazan, no se redondean arbitrariamente para forzar éxito. Estas ramas y sus carreras/fallos están en los tests Billing ejecutados. R2/R3/R4 son choices reconocidos, sin flujo automático/manual completo definido. La devolución comercial no borra número/documento original ni equivale a anular un registro fiscal externo.

## Impresión y límites externos

F2 implementa contenido74mm para rollo80mm con márgenes3mm; CSS usa @page size:auto porque `80mm auto` no es válido. El driver debe configurar papel. F1 declara A4 portrait y márgenes14mm, cabecera de tabla repetible y break-inside:avoid para bloques. Se comprueban reglas/comportamiento Chromium, textos de todas las líneas y PDF: F2 virtual80×500mm en2 páginas; F1 de70 líneas en3 páginas A4. El número de páginas depende del documento/papel; no se promete un rollo continuo ni corte físico.

`window.print()` se solicita explícitamente con botón o autoprint=1 y espera load de CSS/imágenes. Se prueban reapertura, reimpresión tras cambios actuales y retorno de stub sin papel. La prueba de bloqueo deshabilita la excepción de popup de Playwright y espera que expire la activación de usuario: Chromium niega una apertura automática, sin GET de impresión ni mutación. Un enlace pulsado por usuario normalmente se permite. No se simula un bloqueo cambiando esa expectativa a «se abrió otra pestaña».

No existe módulo implementado `integrations/verifacti`, registro/submission, huella/encadenamiento fiscal, firma, QR fiscal, envío, respuesta, cancelación o retry externo. El SHA256 de Billing es fingerprint de idempotencia. ISSUED es emisión **interna**. No se envía nada a AEAT/proveedor ni se inventa certificación. La especificación externa, identidad del software, obligaciones aplicables y revisión legal son dependencias de comercialización, no resultados de un pytest verde.

La prueba adicional de logotipo local retiene su respuesta y comprueba autoprint=0 antes de completarla. Tanto al servir el SVG sintético como al abortar su carga, load termina y autoprint=1, sin cambiar estado económico/documental. No se prueba una descarga real desde S3/proveedores ni una impresora física.

## Hallazgo monetario reproducido

`E02-currency-mismatch-observed` envía `currency_code=USD` por `BusinessProfileForm` y el servicio autorizado de configuración. Ambos lo aceptan. Se completa/paga una venta F1 de12,10 y se emite/imprime: el documento no tiene campo de moneda y el HTML contiene12,10€. No es una conversión ni una discrepancia de redondeo: se pierde el contexto monetario configurable. No se cambia formulario/servicio/modelo para ocultarlo. El soporte actual ensayado es EUR; admitir otra moneda requiere definir contrato y snapshots. La propuesta inmediata de acotar EUR y revisar perfiles legados queda separada en hallazgos y requiere autorización del usuario.
