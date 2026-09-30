from django.contrib import admin

from apps.audit.models import AuditEvent
from apps.core.models import Business
from apps.stores.models import Store
from apps.users.models import CustomUser


class TenantRelatedFilter(admin.SimpleListFilter):
    related_model = None
    field_name = None

    def lookups(self, request, model_admin):
        queryset = self.related_model.objects.all()
        if not request.user.is_superuser:
            if not request.user.business_id:
                return ()
            if self.related_model is Business:
                queryset = queryset.filter(pk=request.user.business_id)
            else:
                queryset = queryset.filter(business_id=request.user.business_id)
        return tuple((str(obj.pk), str(obj)) for obj in queryset.order_by("pk"))

    def queryset(self, request, queryset):
        if self.value():
            return queryset.filter(**{f"{self.field_name}_id": self.value()})
        return queryset


class BusinessFilter(TenantRelatedFilter):
    title = "business"
    parameter_name = "business"
    related_model = Business
    field_name = "business"


class StoreFilter(TenantRelatedFilter):
    title = "store"
    parameter_name = "store"
    related_model = Store
    field_name = "store"


class UserFilter(TenantRelatedFilter):
    title = "user"
    parameter_name = "user"
    related_model = CustomUser
    field_name = "user"


@admin.register(AuditEvent)
class AuditEventAdmin(admin.ModelAdmin):
    list_display = (
        "created_at",
        "business",
        "store",
        "user",
        "module",
        "event_type",
        "entity_type",
        "entity_id",
        "message",
    )
    list_filter = (
        BusinessFilter,
        StoreFilter,
        UserFilter,
        "module",
        "event_type",
        "entity_type",
        "created_at",
    )
    search_fields = (
        "entity_id",
        "message",
        "user__email",
        "user__first_name",
        "user__last_name",
    )
    list_select_related = ("business", "store", "user")
    date_hierarchy = "created_at"
    ordering = ("-created_at", "-pk")

    def get_queryset(self, request):
        queryset = super().get_queryset(request)
        if request.user.is_superuser:
            return queryset
        if not request.user.business_id:
            return queryset.none()
        return queryset.for_business(request.user.business_id)

    def get_readonly_fields(self, request, obj=None):
        return tuple(field.name for field in self.model._meta.fields)

    def has_view_permission(self, request, obj=None):
        return request.user.is_superuser or request.user.has_perm(
            "audit.view_auditevent"
        )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def save_model(self, request, obj, form, change):
        raise PermissionError("Audit events are read-only.")
