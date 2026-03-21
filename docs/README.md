# sala-tpv

Proyecto base de un TPV desarrollado con **Django**, siguiendo una arquitectura de **monolito modular** y orientado a la gestión de un negocio local.

## Objetivo del proyecto

`sala-tpv` nace como una aplicación TPV para cubrir necesidades de gestión como:

- ventas
- tickets
- facturas
- clientes
- productos
- stock
- caja
- reportes básicos

El enfoque inicial del proyecto será **realista, progresivo y bien estructurado**, priorizando una base sólida antes de entrar en lógica de negocio compleja.

## Stack tecnológico

La base técnica definida actualmente es:

- **Backend:** Django 5.2 LTS
- **Base de datos:** PostgreSQL
- **Frontend inicial:** Django Templates + HTML + CSS + JavaScript
- **Interactividad progresiva:** HTMX
- **Contenedorización local:** Docker + Docker Compose
- **CI/CD:** GitHub Actions
- **Despliegue inicial:** Render

## Enfoque arquitectónico

El proyecto seguirá un enfoque de **monolito modular**, separando el sistema por dominios o apps internas.

Módulos previstos:

- `core`
- `users`
- `customers`
- `catalog`
- `inventory`
- `sales`
- `billing`
- `cash_register`
- `payments`
- `reports`
- `settings`
- `audit`

## Estrategia de ramas

Ramas principales:

- `main` → producción
- `develop` → integración y desarrollo intermedio

Flujo de trabajo:

1. Las ramas de trabajo salen desde `develop`
2. Cada cambio entra mediante Pull Request hacia `develop`
3. Cuando un conjunto de cambios esté listo para release, se hace Pull Request de `develop` a `main`
4. En `main` volverán a ejecutarse las validaciones y, posteriormente, el despliegue y versionado

## Convención de nombres de ramas

Formato:

```text
[CODIGO]-feat-nombre-corto
[CODIGO]-fix-nombre-corto
[CODIGO]-docs-nombre-corto
[CODIGO]-chore-nombre-corto

[TPV-001]-feat-configuracion-inicial
[TPV-002]-fix-error-docker
[TPV-003]-docs-documento-base

Convención de commits

Formato:

[CODIGO] feat: descripcion
[CODIGO] fix: descripcion
[CODIGO] docs: descripcion
[CODIGO] chore: descripcion

Ejemplos:

[TPV-001] feat: configurar estructura inicial del proyecto
[TPV-002] fix: corregir docker compose
[TPV-003] docs: actualizar documento base
Labels de release

Labels principales definidas para la estrategia de release:

release-type/current
release-type/hold
Entornos

El proyecto trabajará con estos entornos:

local
develop
production
Próximos pasos

Los siguientes pasos previstos antes de comenzar con la lógica de negocio son:

crear el repositorio y configurar ramas principales
preparar la estructura base del proyecto Django
crear Dockerfile
crear docker-compose.yml
preparar .env.example
configurar settings por entorno
preparar workflows de GitHub Actions
dejar preparado el despliegue inicial en Render
Estado actual

Actualmente el proyecto está en fase de preparación de base técnica y organizativa.

Todavía no se han definido en detalle:

relaciones de base de datos
modelos finales
reglas de negocio completas
flujos funcionales detallados

Eso se abordará en una siguiente fase, una vez esté preparada toda la base del entorno de desarrollo.

Licencia

Por ahora, este proyecto se mantiene sin licencia open source y con enfoque privado.