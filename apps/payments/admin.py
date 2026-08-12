from django.contrib import admin

from apps.payments.models import Payment, PaymentMethod


@admin.register(PaymentMethod)
class PaymentMethodAdmin(admin.ModelAdmin):
    list_display = ("name", "code", "business", "is_active", "allows_refund")
    readonly_fields = ("affects_cash_register",)


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = ("id", "business", "sale", "payment_type", "amount", "status")
    readonly_fields = tuple(field.name for field in Payment._meta.fields)

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
