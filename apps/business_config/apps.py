from django.apps import AppConfig


class BusinessConfigConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.business_config"

    def ready(self):
        # Importamos las señales para que se registren
        import apps.business_config.signals  # noqa: F401
