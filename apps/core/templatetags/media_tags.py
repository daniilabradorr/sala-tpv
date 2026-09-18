from django import template

from apps.core.media.naming import variant_key

register = template.Library()


@register.simple_tag
def media_variant_url(field, variant="master"):
    if not field:
        return ""
    return field.storage.url(variant_key(field.name, variant))
