# DEMOMENTO LO DEJAMOS SIN IMPLEMENTAR

"""from django.db import models

from .isolation import get_customUser_id

class CustomUserQuerySet(models.QuerySet):
    def for_customUser(self, customUser):
        customUser_id = get_customUser_id(customUser)
        return self.filter(business_id=customUser_id)

    def active_customUsers(self):
        return self.filter(business__is_active=True)

    def active_customUsers_for_customUser(self, customUser):
        customUser_id = get_customUser_id(customUser)
        return self.filter(business_id=customUser_id, business__is_active=True)

    def inactive_customUsers(self):
        return self.filter(business__is_active=False)

    def inactive_customUsers_for_customUser(self, customUser):
        customUser_id = get_customUser_id(customUser)
        return self.filter(business_id=customUser_id, business__is_active=False)

CustomUserManager = models.Manager.from_queryset(CustomUserQuerySet)"""
