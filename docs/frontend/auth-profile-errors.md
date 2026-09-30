# Acceso, perfil y errores HTTP

El login utiliza un layout público independiente del App Shell y mantiene el flujo de autenticación y la validación segura de `next` de Django. Las peticiones HTMX originadas en el App Shell llevan un hint exclusivamente visual; si después se pierde la sesión, el middleware añade `expired=1`. El hint no autentica ni autoriza y un visitante anónimo no recibe el mensaje de sesión caducada.

Mi perfil separa mediante navegación server-rendered los datos de perfil y la seguridad. Solo nombre, apellidos y teléfono son editables; correo y rol son informativos. Los cambios de contraseña usan el flujo de Django. El PIN se entrega a `set_pin()` y la interfaz muestra únicamente si está configurado, nunca su valor ni su hash.

Las páginas 400, 403, 404 y 500 son documentos standalone sin navegación autenticada ni contexto de negocio. Un visitante anónimo se autentica mediante login; un usuario autenticado sin autorización recibe 403, sin sugerir que vuelva a iniciar sesión.
