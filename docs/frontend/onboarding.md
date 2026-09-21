# FE-07 — Onboarding

El alta pública vive en `/onboarding/` y reutiliza el layout público. Es un único
formulario Django con cuatro `fieldset`: negocio, primera tienda, Owner y revisión.
JavaScript solo cambia la presentación entre pasos, aplica validación HTML, actualiza
el resumen no sensible y muestra el estado de procesamiento. Sin JavaScript, todos
los bloques siguen disponibles y hay un único submit final.

## Mutación y seguridad

No existen drafts ni modelos temporales. Los pasos visuales no hacen requests y la
única mutación ocurre tras validar el POST final, mediante una única llamada a
`OnboardingService.create_business()`. Su transacción sigue siendo la autoridad para
crear Business, Profile, POSSettings, IVA 21 %, Store, Owner, caja principal, cuatro
métodos de pago y las series F1/F2/F3/R1/R5.

La contraseña y el PIN permanecen únicamente en sus inputs hasta ese POST. No se
copian a campos ocultos, logs, revisión ni sesión. Tras el éxito, la sesión solo
conserva IDs, nombres y el nombre del Owner necesarios para success/welcome. Django
valida la contraseña y el PIN se limita a 4–6 dígitos.

## Contrato actual

País y moneda son fijos: España (`ES`) y EUR. Si se elige la dirección del negocio,
los overrides de Store llegan como `None`; también se normalizan a `None` los campos
personalizados vacíos, preservando el fallback del servicio. Una identidad fiscal
duplicada vuelve al primer paso con un error humano y sin creación parcial.

Después de provisionar se autentica al Owner con `django.contrib.auth.login` y se
aplica Post/Redirect/Get. Success mantiene el layout público. Welcome enlaza catálogo,
inventario y equipo; la acción de venta lleva primero a la apertura real de caja y no
abre una sesión ni crea una venta automáticamente.
