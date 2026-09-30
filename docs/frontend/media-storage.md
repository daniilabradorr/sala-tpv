# Media y almacenamiento

`static` contiene assets versionados de la aplicación y WhiteNoise puede servirlos; `media` contiene contenido de usuario y nunca se sirve con WhiteNoise en producción. Local y test usan `FileSystemStorage`; producción falla al arrancar sin configuración y usa el backend S3-compatible de `django-storages`, sin contrato específico de proveedor.

## Configuración

Producción requiere `MEDIA_STORAGE_ENDPOINT_URL`, `MEDIA_STORAGE_ACCESS_KEY`, `MEDIA_STORAGE_SECRET_KEY` y `MEDIA_STORAGE_BUCKET_NAME`. `MEDIA_STORAGE_REGION`, `MEDIA_STORAGE_CUSTOM_DOMAIN` y `MEDIA_STORAGE_PUBLIC_READ` son opcionales. Cambiar de proveedor solo requiere otro servicio compatible y estas variables; nunca se guardan secretos en el repositorio.

## Política y pipeline

Se admiten JPEG, PNG y WebP de hasta 5 MiB, 6000×6000 y 36 millones de píxeles. Pillow decodifica el contenido, comprueba que formato y extensión coincidan, rechaza animación y bombas de descompresión, aplica orientación EXIF y re-encodea sin metadata. Se producen WebP `master` (2400 px), `detail` (800 px) y `thumb` (320 px), sin ampliar imágenes pequeñas y conservando transparencia.

Las claves inmutables tienen forma `businesses/<business-id>/<kind>/<entity-id>/<asset-uuid>/<variant>.webp`; no contienen filename ni datos comerciales. Cada mutación valida explícitamente Business y entidad. Replace guarda los tres objetos nuevos antes de bloquear/actualizar la referencia; remove limpia primero la referencia. La limpieza del asset anterior se ejecuta idempotentemente tras commit. Un fallo al guardar conserva la referencia anterior y limpia parciales best-effort.

Los nombres versionados permiten `Cache-Control: public, max-age=31536000, immutable` y cache bust natural. Las variantes se derivan del master sin `exists()` ni lectura en render.

`BusinessProfile.logo_url` permanece solo como fallback histórico. Una carga o eliminación explícita del logo gestionado limpia esa URL para que no reaparezca. En una futura regeneración, un comando deberá recorrer masters, escribir un UUID nuevo y cambiar la referencia mediante el mismo servicio; no debe sobrescribir paths cacheados.
