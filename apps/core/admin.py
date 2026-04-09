from django.contrib import admin

from apps.core.models import Business


@admin.register(Business)
class BusinessAdmin(admin.ModelAdmin):
    list_display = ("name", "slug", "is_active", "created_at", "updated_at")
    list_filter = ("is_active", "created_at")
    search_fields = ("name", "slug")
    ordering = ("name",)
    list_editable = ("is_active",)
    readonly_fields = ("created_at", "updated_at")
    prepopulated_fields = {"slug": ("name",)}
    actions = ("activate_businesses", "deactivate_businesses")

    @admin.action(description="Activar empresas seleccionadas")
    def activate_businesses(self, request, queryset):
        queryset.update(is_active=True)

    @admin.action(description="Desactivar empresas seleccionadas")
    def deactivate_businesses(self, request, queryset):
        queryset.update(is_active=False)