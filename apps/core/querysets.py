from django.db import models

from apps.core.isolation import get_business_id


class BusinessQuerySet(models.QuerySet):
    def active(self):
        return self.filter(is_active=True)

    def inactive(self):
        return self.filter(is_active=False)


class BusinessScopedQuerySet(models.QuerySet):
    def for_business(self, business):
        business_id = get_business_id(business)
        return self.filter(business_id=business_id)

    def active_businesses(self):
        return self.filter(business__is_active=True)


BusinessManager = models.Manager.from_queryset(BusinessQuerySet)
BusinessScopedManager = models.Manager.from_queryset(BusinessScopedQuerySet)
