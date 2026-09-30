# Convenciones de templates y HTMX

- Una página completa vive en `templates/<modulo>/<pantalla>.html`, extiende el
  layout aplicable e incluye el shell. Los nombres existentes se conservan.
- Una respuesta parcial vive junto a su módulo en
  `templates/<modulo>/partials/_<region>.html`. Contiene solo la región que se
  sustituye: nunca duplica `html`, `head`, sidebar o topbar, ni incluye scripts.
- Las views seleccionan página o partial mediante `request.htmx`; Django sigue
  siendo la fuente de verdad y los partials solo presentan el contexto recibido.
- Cada interacción HTMX declara un target estable y semántico. HTMX se limita a
  regiones internas; la navegación entre módulos continúa siendo una request
  normal y no se habilita `hx-boost` global.
- El JavaScript global vive en `static/js/core/`; el específico de futuras
  pantallas vivirá en `static/js/pages/`. Los listeners globales se inicializan
  una sola vez y deben seguir funcionando tras swaps.

`templates/layouts/` y `templates/components/` quedan reservados para la
evolución progresiva del frontend. FE-01 no mueve templates existentes ni crea
componentes visuales.
