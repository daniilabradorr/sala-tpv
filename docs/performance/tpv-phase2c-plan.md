# Fase 2C — plan y límites

Base verificada: a356003, rama de trabajo hardening/tpv-phase2c. El usuario
ordena publicar el resultado en feat/tpv-optimistic-cart; no merge ni despliegue.

1. Añadir un transporte opcional de hasta 50 operaciones al protocolo existente.
   Transacción única y bloqueo de Sale, recibos individuales y servicios actuales,
   sin fusionar SaleLine, sin migraciones ni cambios de contratos económicos.
   Un lote nuevo exige revisión inicial; el reintento completo verifica cada
   fingerprint antes de devolver estado actual. Un prefijo de recibos tras una
   limpieza local interrumpida se puede reproducir; no se admite añadir un sufijo
   nuevo a un lote parcialmente confirmado. Referencias a añadidos anteriores
   se resuelven por UUID dentro del mismo ámbito. Mantener transporte individual.
2. Diario atómico de la petición en vuelo en sessionStorage; conservar contenido
   exacto hasta reconciliar. Validación y bloqueo explícito si hay corrupción;
   no degradar silenciosamente a formularios que puedan duplicar operaciones.
   Mantener aislamiento por pestaña e identidad, advertir al abandonar. No añadir
   almacenamiento compartido persistente: requeriría gestión de sesiones/propiedad
   y recuperación entre pestañas en terminales compartidos. Documentar cierre
   definitivo como límite, sin prometer durabilidad que el navegador no garantiza.
3. Sustituir polling de flush por eventos/Promises con plazo y cancelación local.
   Acotar también GET y GET de checkout. Cabeceras fallidas/desconocidas bloquean
   checkout hasta revalidación explícita; no inferir rollback ni reenviar cambios
   de cliente de resultado desconocido. Cerrar modal invalida su continuación.
4. Observabilidad de recibos mediante comando de solo lectura, sin TTL ni borrados.
5. Procedimientos de staging/rollback y clientes antiguos; no configuración real.
6. Tests PostgreSQL, navegador y matriz A/B con JS baseline a356003 sobre el mismo
   backend y datos sintéticos. Separar visual, persistencia, peticiones y checkout.

Este transporte no cambia contratos entre Sales y otros módulos: invoca los
mismos servicios por operación. Una compactación comercial, una retención distinta
o almacenamiento durable compartido con nuevos contratos quedan como propuesta.
