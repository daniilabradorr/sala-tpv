Sí. Te dejo el **README.md de raíz listo para copiar** y debajo el `.env.example` mejor documentado. También he revisado los comandos contra tu repo: usas `uv`, `poethepoet`, `ruff`, `pytest-django`, `gunicorn`, `dj-database-url`, `psycopg` y `whitenoise` en `pyproject.toml`. 

---

# 1. Crear `README.md` en la raíz

Crea este archivo:

```bash
README.md
```

Y pega esto:

````md
# Sala TPV

TPV para negocio local desarrollado con **Django 5.2**, siguiendo una arquitectura de monolito modular.

El objetivo del proyecto es construir una base sólida para gestionar ventas, tickets, facturas, clientes, productos, stock, caja, pagos, compras, reportes y auditoría.

---

## Stack técnico

- Python 3.12
- Django 5.2
- PostgreSQL
- SQLite para desarrollo rápido si no se configura `DATABASE_URL`
- Docker y Docker Compose
- uv para gestión de dependencias
- Ruff para lint y formato
- GitHub Actions para CI
- Render para despliegue
- WhiteNoise para servir estáticos en producción
- Gunicorn como servidor WSGI en producción

---

## Requisitos previos

Antes de levantar el proyecto necesitas tener instalado:

- Python 3.12
- uv
- Git
- Docker y Docker Compose, opcional pero recomendado
- PostgreSQL, solo si no vas a usar Docker

Comprobar versiones:

```bash
python --version
uv --version
docker --version
docker compose version
````

---

## Instalación local desde cero

Clona el repositorio:

```bash
git clone <URL_DEL_REPOSITORIO>
cd sala-tpv
```

Copia el archivo de variables de entorno:

```bash
cp .env.example .env
```

En Windows PowerShell:

```powershell
Copy-Item .env.example .env
```

Instala dependencias:

```bash
uv sync --dev
```

Ejecuta migraciones:

```bash
uv run python manage.py migrate
```

Crea un superusuario:

```bash
uv run python manage.py createsuperuser
```

Levanta el servidor local:

```bash
uv run python manage.py runserver
```

Abre en el navegador:

```text
http://127.0.0.1:8000/
```

Endpoint de salud:

```text
http://127.0.0.1:8000/health/
```

Admin de Django:

```text
http://127.0.0.1:8000/admin/
```

---

## Variables de entorno

El proyecto usa un archivo `.env` basado en `.env.example`.

Variables principales:

```env
DEBUG=1
SECRET_KEY=django-insecure-cambia-esto
ALLOWED_HOSTS=127.0.0.1,localhost
CSRF_TRUSTED_ORIGINS=
DJANGO_SETTINGS_MODULE=config.settings.local

POSTGRES_DB=sala_tpv
POSTGRES_USER=sala_tpv_user
POSTGRES_PASSWORD=sala_tpv_password
POSTGRES_HOST=db
POSTGRES_PORT=5432

DATABASE_URL=
LOG_LEVEL=INFO
```

### `SECRET_KEY`

Clave secreta de Django.

En local puede ser una clave sencilla de desarrollo.

En producción debe ser una clave segura y privada.

### `DEBUG`

En local:

```env
DEBUG=1
```

En producción:

```env
DEBUG=0
```

### `ALLOWED_HOSTS`

En local:

```env
ALLOWED_HOSTS=127.0.0.1,localhost
```

En Render:

```env
ALLOWED_HOSTS=tu-servicio.onrender.com
```

Si hay varios hosts, se separan por comas:

```env
ALLOWED_HOSTS=127.0.0.1,localhost,tu-servicio.onrender.com
```

### `CSRF_TRUSTED_ORIGINS`

En local puede quedar vacío.

En Render debe incluir el dominio completo con `https://`:

```env
CSRF_TRUSTED_ORIGINS=https://tu-servicio.onrender.com
```

### `DJANGO_SETTINGS_MODULE`

Para desarrollo local:

```env
DJANGO_SETTINGS_MODULE=config.settings.local
```

Para tests:

```env
DJANGO_SETTINGS_MODULE=config.settings.test
```

Para producción:

```env
DJANGO_SETTINGS_MODULE=config.settings.production
```

### `DATABASE_URL`

Si `DATABASE_URL` está vacío, Django usará SQLite.

Para usar PostgreSQL con Docker Compose:

```env
DATABASE_URL=postgresql://sala_tpv_user:sala_tpv_password@db:5432/sala_tpv
```

Para Render debes copiar la **Internal Database URL** de PostgreSQL:

```env
DATABASE_URL=postgresql://usuario:password@host/base_datos
```

---

## Ejecución local con SQLite

Para desarrollo rápido, puedes dejar `DATABASE_URL` vacío:

```env
DATABASE_URL=
```

Después ejecuta:

```bash
uv run python manage.py migrate
uv run python manage.py runserver
```

---

## Ejecución local con PostgreSQL y Docker

Configura tu `.env` así:

```env
POSTGRES_DB=sala_tpv
POSTGRES_USER=sala_tpv_user
POSTGRES_PASSWORD=sala_tpv_password
POSTGRES_HOST=db
POSTGRES_PORT=5432
DATABASE_URL=postgresql://sala_tpv_user:sala_tpv_password@db:5432/sala_tpv
```

Levanta los contenedores:

```bash
docker compose up --build
```

En otra terminal, ejecuta migraciones dentro del contenedor:

```bash
docker compose exec web uv run python manage.py migrate
```

Crear superusuario:

```bash
docker compose exec web uv run python manage.py createsuperuser
```

Comprobar el endpoint de salud:

```text
http://127.0.0.1:8000/health/
```

Parar contenedores:

```bash
docker compose down
```

Parar contenedores y borrar volumen de PostgreSQL:

```bash
docker compose down -v
```

---

## Tests

El proyecto tiene configuración de tests con `config.settings.test`.

Ejecutar tests en Linux, macOS o Git Bash:

```bash
DJANGO_SETTINGS_MODULE=config.settings.test uv run python manage.py test
```

En Windows PowerShell:

```powershell
$env:DJANGO_SETTINGS_MODULE="config.settings.test"
uv run python manage.py test
```

También se puede ejecutar:

```bash
uv run python manage.py test
```

pero se recomienda fijar explícitamente `DJANGO_SETTINGS_MODULE=config.settings.test` para evitar que use configuración local.

---

## Lint y formato

El proyecto usa Ruff.

Ejecutar lint:

```bash
uv run ruff check .
```

Comprobar formato:

```bash
uv run ruff format --check .
```

Aplicar formato automáticamente:

```bash
uv run ruff format .
```

---

## Checks completos antes de subir cambios

Antes de hacer commit, ejecutar:

```bash
uv run ruff check .
uv run ruff format --check .
DJANGO_SETTINGS_MODULE=config.settings.test uv run python manage.py check
DJANGO_SETTINGS_MODULE=config.settings.test uv run python manage.py makemigrations --check --dry-run
DJANGO_SETTINGS_MODULE=config.settings.test uv run python manage.py test
```

En Windows PowerShell:

```powershell
$env:DJANGO_SETTINGS_MODULE="config.settings.test"

uv run ruff check .
uv run ruff format --check .
uv run python manage.py check
uv run python manage.py makemigrations --check --dry-run
uv run python manage.py test
```

También existe la tarea:

```bash
uv run poe verify
```

pero antes conviene exportar `DJANGO_SETTINGS_MODULE=config.settings.test` para que los comandos de Django usen settings de test.

---

## Comandos útiles

Levantar servidor:

```bash
uv run python manage.py runserver
```

Crear migraciones:

```bash
uv run python manage.py makemigrations
```

Aplicar migraciones:

```bash
uv run python manage.py migrate
```

Comprobar migraciones pendientes:

```bash
uv run python manage.py makemigrations --check --dry-run
```

Crear superusuario:

```bash
uv run python manage.py createsuperuser
```

Recoger estáticos:

```bash
uv run python manage.py collectstatic --noinput
```

Comprobar configuración Django:

```bash
uv run python manage.py check
```

---

## Despliegue en Render

### 1. Crear PostgreSQL

En Render:

```text
New → PostgreSQL
```

Crear una base de datos PostgreSQL en la misma región que el Web Service.

Después copiar la **Internal Database URL**.

### 2. Crear Web Service

Conectar el repositorio a Render.

Configurar:

```text
Environment: Python
Branch: main
```

### 3. Variables de entorno en Render

Añadir estas variables:

```env
DEBUG=0
SECRET_KEY=clave-segura-de-produccion
DJANGO_SETTINGS_MODULE=config.settings.production
ALLOWED_HOSTS=tu-servicio.onrender.com
CSRF_TRUSTED_ORIGINS=https://tu-servicio.onrender.com
DATABASE_URL=postgresql://usuario:password@host/base_datos
LOG_LEVEL=INFO
SESSION_COOKIE_SECURE=1
CSRF_COOKIE_SECURE=1
SECURE_SSL_REDIRECT=1
```

### 4. Build Command

Usar:

```bash
uv sync --frozen && uv run python manage.py collectstatic --noinput && uv run python manage.py migrate
```

### 5. Start Command

Usar Gunicorn:

```bash
uv run gunicorn config.wsgi:application --bind 0.0.0.0:$PORT
```

No usar en producción:

```bash
python manage.py runserver
```

`runserver` solo debe usarse en local/desarrollo.

---

## Endpoint de salud

El proyecto incluye un endpoint de health check:

```text
/health/
```

Respuesta esperada:

```json
{
  "status": "ok"
}
```

Este endpoint debe devolver HTTP 200 y se usa para comprobar que la aplicación está levantada correctamente.

---

## Flujo recomendado de trabajo

Crear rama desde `develop`:

```bash
git checkout develop
git pull
git checkout -b TPV-XXX-feat-nombre-corto
```

Antes de subir:

```bash
uv run ruff check .
uv run ruff format --check .
DJANGO_SETTINGS_MODULE=config.settings.test uv run python manage.py test
```

Commit:

```bash
git add .
git commit -m "TPV-XXX docs: actualizar README de instalación"
git push origin TPV-XXX-feat-nombre-corto
```

Abrir Pull Request hacia `develop`.

---

## Estado del proyecto

Actualmente el proyecto está en fase de construcción de base técnica.

La prioridad actual es dejar preparada una base estable con:

* configuración por entornos
* PostgreSQL
* Docker
* CI/CD
* tests mínimos
* lint y formato
* despliegue inicial en Render

````

---

# 2. Mejorar `.env.example`

Tu `.env.example` existe, pero ahora está muy básico. Actualmente contiene variables como `DEBUG`, `SECRET_KEY`, `ALLOWED_HOSTS`, `DATABASE_URL` y datos de PostgreSQL. :contentReference[oaicite:1]{index=1}

Yo lo dejaría así:

```env
# ============================================================
# Django base
# ============================================================

# 1 en local/desarrollo, 0 en producción
DEBUG=1

# Clave secreta de Django.
# En producción debe ser una clave segura y privada.
SECRET_KEY=django-insecure-cambia-esto

# Hosts permitidos separados por comas.
# Local:
# ALLOWED_HOSTS=127.0.0.1,localhost
# Render:
# ALLOWED_HOSTS=tu-servicio.onrender.com
ALLOWED_HOSTS=127.0.0.1,localhost

# Orígenes seguros para CSRF separados por comas.
# En local puede estar vacío.
# En Render:
# CSRF_TRUSTED_ORIGINS=https://tu-servicio.onrender.com
CSRF_TRUSTED_ORIGINS=

# Settings activo.
# Local:
# DJANGO_SETTINGS_MODULE=config.settings.local
# Tests:
# DJANGO_SETTINGS_MODULE=config.settings.test
# Producción:
# DJANGO_SETTINGS_MODULE=config.settings.production
DJANGO_SETTINGS_MODULE=config.settings.local


# ============================================================
# Base de datos PostgreSQL
# ============================================================

# Variables usadas por Docker Compose para crear PostgreSQL.
POSTGRES_DB=sala_tpv
POSTGRES_USER=sala_tpv_user
POSTGRES_PASSWORD=sala_tpv_password
POSTGRES_HOST=db
POSTGRES_PORT=5432

# URL completa de conexión a base de datos.
# Si se deja vacía, Django usará SQLite.
#
# Local con Docker Compose:
# DATABASE_URL=postgresql://sala_tpv_user:sala_tpv_password@db:5432/sala_tpv
#
# Render:
# DATABASE_URL=postgresql://usuario:password@host/base_datos
DATABASE_URL=


# ============================================================
# Logging
# ============================================================

LOG_LEVEL=INFO


# ============================================================
# Seguridad producción
# ============================================================

# En local pueden quedarse a 0.
# En Render/producción deberían estar a 1.
SESSION_COOKIE_SECURE=0
CSRF_COOKIE_SECURE=0
SECURE_SSL_REDIRECT=0


# ============================================================
# Integraciones futuras
# ============================================================

# El día de mañana se añadirán aquí credenciales de integraciones
# como Verifacti / VeriFactu u otros proveedores externos.
````

---

# 3. Comandos revisados

Los comandos son coherentes con tu repo.

En `pyproject.toml` tienes:

```toml
lint = "ruff check ."
format = "ruff format ."
format-check = "ruff format --check ."
test = "python manage.py test"
django-check = "python manage.py check"
migrations-check = "python manage.py makemigrations --check --dry-run"
```



Y Docker Compose levanta el servicio web en el puerto `8000` con:

```yaml
command: uv run python manage.py runserver 0.0.0.0:8000
ports:
  - "8000:8000"
```



El único detalle importante es este: tu Django usa PostgreSQL solo si `DATABASE_URL` existe; si no, cae a SQLite. 

Por eso en el README he dejado claro que para Docker necesitas:

```env
DATABASE_URL=postgresql://sala_tpv_user:sala_tpv_password@db:5432/sala_tpv
```

Con esto, la tarea queda bien cubierta: **instalación, `.env`, ejecución local, Docker, tests, lint y Render**.
