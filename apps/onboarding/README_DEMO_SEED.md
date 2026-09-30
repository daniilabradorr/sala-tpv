# Dataset demo de comercio

Este seeder operativo añade un dataset pequeño a un `Business` **existente y
correctamente provisionado**. Es independiente del onboarding: no crea ni
modifica negocios, perfiles, configuración POS, tiendas, usuarios, cajas,
métodos de pago ni series fiscales. Tampoco crea ventas, cobros, sesiones de
caja o documentos de facturación.

## Ejecución y smoke test

1. Localiza el slug de un negocio provisionado, por ejemplo desde
   `python manage.py shell`.
2. Ejecuta:

   ```console
   uv run python manage.py seed_demo_business --business-slug=<slug>
   ```

3. Inicia sesión como un Owner existente y abre Catálogo. Deben aparecer las
   categorías Bebidas, Alimentación y Servicios, con seis productos: Agua
   mineral 500 ml, Refresco cola 330 ml, Patatas chips, Barrita de chocolate,
   Bolsa reutilizable y Envoltorio para regalo.
4. En Inventario deben aparecer únicamente las cinco fichas físicas, en la
   Store predeterminada activa, con stocks 48, 36, 24, 30 y 50. Envoltorio para
   regalo no debe tener ficha de inventario.
5. En Clientes deben aparecer Cliente Mostrador DEMO y Empresa Demo Netxodo
   SL. `B12345678` es exclusivamente un identificador ficticio para probar el
   contrato interno; no se presenta como un NIF válido para envíos a AEAT.
6. Ejecuta el comando de nuevo. No debe aparecer ningún duplicado, movimiento
   INITIAL adicional ni cambio en el stock existente.

El comando exige exactamente una Store predeterminada activa y resuelve el Tax
predeterminado activo mediante el contrato canónico de catálogo. Las claves
`demo-*`, `DEMO-*` y las identidades deterministas de clientes permiten
reutilizar datos compatibles. Una coincidencia incompatible provoca un error y
revierte atómicamente todo lo creado por esa ejecución, sin sobrescribir ni
borrar datos anteriores.
