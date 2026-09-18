# FE-03 — App Shell y navegación

El shell autenticado usa un único catálogo en `apps/core/navigation.py`. El
context processor construye una vez por request los grupos **Operación**,
**Gestión** y **Administración**, y entrega el mismo resultado al sidebar y a
la Command Palette. Las entradas se filtran con los helpers existentes de
`apps.users.helpers`; ocultarlas mejora la interfaz, pero los mixins y checks
de cada endpoint siguen siendo la autoridad de seguridad.

## Tienda activa

La resolución compartida vive en `apps/core/shell.py`. La tienda activa es
estado de interfaz almacenado en la sesión bajo
`netxodo_active_store_id`. Se resuelve exclusivamente dentro de las tiendas
activas autorizadas por el resolver compartido: se conserva la sesión válida y,
si no, se usa la tienda predeterminada accesible o la primera tienda operativa.
Las rutas autorizadas con `store_id` sincronizan el contexto. Un
superusuario sin negocio explícito permanece sin contexto y uno con Business
solo puede resolver Stores de ese Business.

El selector realiza un POST con CSRF a `stores:store_set_active`. Valida de
nuevo acceso, actividad y tenant, y limita la redirección a destinos locales;
las rutas con Store de Ventas, Caja o Facturación se reconstruyen para la nueva
tienda; Payments vuelve al listado seguro de Ventas. Cambiar esta preferencia
**no** llama a `set_default_store`, no cambia
`Store.is_default` y no modifica relaciones de acceso ni datos de dominio.

## Superficies y responsive

- Desktop (`>=1200px`): sidebar fija de 248 px y topbar completa.
- Tablet (`768–1199px`) y móvil (`<768px`): el mismo sidebar funciona como
  drawer con overlay, `inert`, trampa/restauración de foco y Escape.
- La topbar contiene selector, acceso a Command Palette, CTA de venta solo con
  `can_sell_in_store`, y menú de usuario con logout POST.
- Command Palette es un catálogo local de navegación y acciones autorizadas;
  abre con Ctrl/Cmd+K y filtra texto y palabras clave sin requests.

Informes y Actividad pertenecen al mapa futuro, pero no se enlazan porque
Reports y Audit todavía no tienen rutas frontend. FE-03 tampoco introduce el
sistema global de modales/drawers/toasts/HTMX previsto para FE-04: sus dos
`dialog` son comportamientos específicos del shell.
