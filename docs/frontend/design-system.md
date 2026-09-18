# Design System de Netxodo

## Fuente de verdad

`static/css/tokens.css` es la única fuente de valores visuales compartidos. La
especificación frontend gobierna la UI y el manual de identidad los valores de
marca. La jerarquía es **marca → semántica → componente**.

## Tokens

La marca conserva `#020C18`, `#07182B`, `#F1B902`, `#0061C1`, `#0794F2`,
`#F7F8FA` y `#9AA7B7`. Los tokens semánticos separan workspace, superficie,
superficie atenuada, texto, borde, acción primaria azul, acento amarillo y los
estados success/warning/danger/info/neutral. Los neutrales auxiliares solo
resuelven texto, borde, disabled y superficies claras.

La escala de espacio es 4, 8, 12, 16, 20, 24, 32 y 40 px. Los radios son 6, 8,
12 px y pill; las sombras son discretas. Inter usa fallback del sistema, tamaños
xs/sm/body/H2/H1, pesos 400/500/700/800/900 y line-heights centralizados.

Breakpoints canónicos: mobile 0–767 px, tablet 768–1199 px y desktop ≥1200 px.
Los `@media` deben usar valores literales (custom properties no funcionan ahí).
El shell conserva temporalmente su breakpoint FE-01 de 900 px hasta FE-03.

## Componentes

- **Buttons:** `.button` primaria azul; `.button-secondary`, `.button-danger` y
  `.button-ghost`, con hover, active, focus y disabled.
- **Forms:** `.form-field`, `.form-field-error`, `.help-text`, `.form-errors` y
  `.field-errors`; labels reales y `aria-invalid`/`aria-describedby` cuando
  corresponda.
- **Cards:** `.card`, `.card-narrow` y `.card-form` para agrupaciones reales.
- **Badges:** `.badge-{success,warning,danger,info,neutral}`. Los aliases
  `badge-active`, `badge-inactive`, `badge-default` y estados existentes siguen
  vigentes. El texto debe expresar el estado; el color no basta.
- **Tables:** HTML `table` nativo dentro de `.table-scroll`; `.number-cell`,
  `.actions-cell`, `.table-actions` y `.pagination` complementan el contrato.
- **Tabs:** `.tabs` y `.tab`; active admite `.is-active`, `aria-current` o
  `aria-selected`. Links cambian URL; buttons controlan una región real.
- **Skeletons:** `.skeleton` con variantes `-line`, `-block`, `-kpi` y `-row`.
  Son solo presentación y respetan `prefers-reduced-motion`.

## SVG y accesibilidad

`static/icons/netxodo-ui.svg` es un sprite lineal local con `currentColor`. Usa
`{% include "components/icon.html" with name="search" %}`. El helper es
puramente decorativo; un control icon-only necesita `aria-label` en el control.
Se priorizan HTML nativo, foco visible, contraste AA, targets de 44 px, labels y
disabled legible. No se elimina el outline sin sustitución.

Las clases legacy compartidas se mantienen como API compatible; su implementación
vive ahora en `components/`. `base.css` conserva base, tipografía, helpers y shell,
y `erp_admin.css` solo lenguaje de páginas/layout administrativo. FE-03 hará el
nuevo shell y navegación. FE-04 hará modales, drawers, toasts y UX HTMX global.
