from django.db import models

from django.utils.text import slugify
from apps.core.querysets import BusinessManager, BusinessScopedManager

#modelo/clase para el timestamp de created_at y updated_at, que se hereda en los modelos que lo necesiten
class TimeStampedModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True
        
#hacemos la entidad del negocio/empresa (business)
class Business(TimeStampedModel):
    name = models.CharField("nombre", max_length=255)
    slug = models.SlugField("slug", max_length=255, unique=True)
    is_active = models.BooleanField("activo", default=True)
    
    objects = BusinessManager()
    
    class Meta:
        verbose_name = "Empresa"
        verbose_name_plural = "Empresas"
        ordering = ("name",)
        indexes = [
            models.Index(fields=["is_active", "name"], name="core_biz_active_name_idx"),
        ]
        
    def clean(self):
        super().clean()
        base_slug = self.slug or self.name
        self.slug = slugify(base_slug)

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        self.full_clean()
        return super().save(*args, **kwargs)

    def __str__(self) -> str:
        return self.name
    
    
#Modelo para la herencia de la relacion con Business y el created_at y updated_at
class BusinessOwnedModel(TimeStampedModel):
    business = models.ForeignKey(
        "core.Business",
        on_delete=models.PROTECT,
        related_name="%(app_label)s_%(class)s_set",
        related_query_name="%(app_label)s_%(class)s",
    )

    objects = BusinessScopedManager()

    class Meta:
        abstract = True