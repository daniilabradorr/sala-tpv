# Componentes de presentación

El Design System usa HTML semántico y las clases documentadas en
`docs/frontend/design-system.md`. Botones, formularios, cards, badges, tablas,
tabs y skeletons se escriben directamente: no requieren un include Django.

Usa un include solo cuando reduzca duplicación real. El helper disponible es el
icono SVG local:

```django
{% include "components/icon.html" with name="search" size="20" %}
```

El SVG es decorativo (`aria-hidden`). Un botón que solo contenga un icono debe
llevar un `aria-label` descriptivo en el propio botón. No se incluyen aquí
modales, drawers ni toasts; corresponden a FE-04.
