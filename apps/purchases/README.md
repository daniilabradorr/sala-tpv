# Purchases

`purchases` gestiona proveedores, pedidos de compra y la recepción real de mercancía. No gestiona devoluciones a proveedor, facturas recibidas, cuentas a pagar, pagos, valoración FIFO/LIFO/media, actualización automática de `Product.cost_price`, auditoría, informes, VeriFactu ni integraciones externas.

## Dominio

- `Supplier`: proveedor del `Business`; es global al negocio.
- `Purchase`: pedido asociado a una única `Store` y proveedor.
- `PurchaseLine`: snapshot comercial de producto, SKU, unidad, cantidad, coste e impuesto.
- `PurchaseReceipt`: evento inmutable de recepción real.
- `PurchaseReceiptLine`: verdad histórica de cuánto se recibió de una línea concreta.

Los estados de una compra son `draft`, `ordered`, `partially_received`, `received` y `cancelled`. Crear, editar u ordenar una compra es neutral para el stock. `register_purchase_receipt()` registra recepciones parciales o completas y, cuando `POSSettings.enable_stock_control=True` y `Product.track_stock=True`, delega la entrada física a Inventory.

## Recepción e Inventory

Cada recepción exige una clave UUID idempotente. El fingerprint SHA-256 canónico permite devolver el mismo evento ante un retry idéntico y rechazar la reutilización conflictiva de la clave. `Purchase` es el mutex transaccional y todas sus líneas se bloquean para impedir sobre-recepción concurrente.

Un producto o proveedor desactivado después de `order` puede recibirse. Un `InventoryItem` inactivo bloquea la recepción física y revierte toda la operación. Sin stock global o sin `track_stock`, se conserva la recepción comercial pero no se crea movimiento.

Los `StockMovement` de compra guardan FKs fuertes a `Purchase`, `PurchaseLine`, `PurchaseReceipt` y `PurchaseReceiptLine`; usan el coste histórico de la línea y la fecha del receipt. Inventory sigue siendo la única autoridad que modifica stock y `Product.cost_price` no cambia.

## Seguridad y arquitectura

Todo acceso se limita al `Business`. Owner accede a todas sus Stores; manager solo a Stores con `UserStoreAccess` activo; cashier no accede a la interfaz. Purchases no requiere PIN.

La arquitectura es `Form -> Selector -> Service -> View`: selectors solo leen, forms validan entrada, views coordinan HTTP y toda mutación pasa por `services.py`. Nunca se debe escribir stock, estados, líneas, receipts o movimientos directamente desde forms, views o admin.
