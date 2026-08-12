# Sales

`SaleLine` conserva el snapshot fiscal histórico resuelto al crear la línea; los cambios posteriores de `Product` o `Tax` no reescriben esa fotografía. Las guardas de tratamientos fiscales no soportados siguen activas.

Al completar ventas y devoluciones, los `StockMovement` mantienen tanto sus FKs reales a los documentos y líneas de Sales como `reference_type`/`reference_id` por compatibilidad. Las devoluciones completadas persisten en `approved_by` el usuario que las autorizó y conservan la idempotencia del servicio.
