"""Este archivo lo qyue hace es cuand se crea una business
se lanza la señal para crear automáticamente el perfil de la empresa y la configuración del TPV, con valores por defecto. Esto asegura que cada vez que se cree una nueva empresa, tenga su configuración inicial lista para usar sin necesidad de configurarla manualmente cada vez.
"""

from django.db.models.signals import post_save
from django.dispatch import receiver

from apps.business_config.services import bootstrap_business_configuration
from apps.core.models import Business


@receiver(post_save, sender=Business)
def create_business_configuration(sender, instance, created, **kwargs):
    if created:
        bootstrap_business_configuration(instance)
