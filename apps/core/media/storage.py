from django.core.exceptions import ImproperlyConfigured

REQUIRED_MEDIA_STORAGE_KEYS = (
    "MEDIA_STORAGE_ENDPOINT_URL",
    "MEDIA_STORAGE_ACCESS_KEY",
    "MEDIA_STORAGE_SECRET_KEY",
    "MEDIA_STORAGE_BUCKET_NAME",
)


def build_media_storage_config(env):
    missing = [key for key in REQUIRED_MEDIA_STORAGE_KEYS if not env.get(key)]
    if missing:
        raise ImproperlyConfigured(
            "Configuración de media incompleta; faltan: " + ", ".join(missing)
        )

    public_read = env.get("MEDIA_STORAGE_PUBLIC_READ", "1") == "1"
    cache_scope = "public" if public_read else "private"
    return {
        "BACKEND": "storages.backends.s3.S3Storage",
        "OPTIONS": {
            "endpoint_url": env["MEDIA_STORAGE_ENDPOINT_URL"],
            "access_key": env["MEDIA_STORAGE_ACCESS_KEY"],
            "secret_key": env["MEDIA_STORAGE_SECRET_KEY"],
            "bucket_name": env["MEDIA_STORAGE_BUCKET_NAME"],
            "region_name": env.get("MEDIA_STORAGE_REGION") or None,
            "custom_domain": env.get("MEDIA_STORAGE_CUSTOM_DOMAIN") or None,
            "default_acl": "public-read" if public_read else None,
            "querystring_auth": not public_read,
            "file_overwrite": False,
            "object_parameters": {
                "CacheControl": f"{cache_scope}, max-age=31536000, immutable"
            },
        },
    }
