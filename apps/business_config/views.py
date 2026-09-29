from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.views import View

from apps.business_config.forms import BusinessProfileForm, POSSettingsForm
from apps.business_config.models import BusinessProfile, POSSettings
from apps.business_config.services import (
    remove_business_logo,
    replace_business_logo,
    update_business_profile,
    update_pos_settings,
)
from apps.users.mixins import CanManageBusinessSettingsMixin
from apps.payments.forms import PaymentMethodAdminForm
from apps.payments.selectors import (
    get_mvp_payment_method_for_admin,
    get_mvp_payment_methods_for_business,
)
from apps.payments.services import update_payment_method_configuration


class BusinessProfileUpdateView(CanManageBusinessSettingsMixin, View):
    template_name = "business_config/profile_form.html"

    def get_business(self):
        business = getattr(self.request.user, "business", None)
        if business is None:
            raise PermissionDenied("Se necesita un negocio para gestionar su perfil.")
        return business

    def get_profile(self):
        return get_object_or_404(BusinessProfile, business=self.get_business())

    def get(self, request):
        profile = self.get_profile()
        form = BusinessProfileForm(instance=profile)
        return render(request, self.template_name, self.get_context(form, profile))

    def get_context(self, form, profile):
        return {
            "form": form,
            "persisted_config": {
                field: str(getattr(profile, field) or "")
                for field in BusinessProfileForm.Meta.fields
            },
        }

    def post(self, request):
        business = self.get_business()
        profile = get_object_or_404(BusinessProfile, business=business)
        persisted_profile = BusinessProfile.objects.get(pk=profile.pk)
        form = BusinessProfileForm(
            data=request.POST, files=request.FILES, instance=profile
        )
        if form.is_valid():
            logo_upload = form.cleaned_data.pop("logo_upload")
            remove_logo = form.cleaned_data.pop("remove_logo")
            with transaction.atomic():
                update_business_profile(
                    business=business, updated_by=request.user, **form.cleaned_data
                )
                if logo_upload:
                    replace_business_logo(
                        business=business, profile=profile, upload=logo_upload
                    )
                elif remove_logo:
                    remove_business_logo(business=business, profile=profile)
            messages.success(request, "Datos de empresa actualizados correctamente.")
            return redirect("business_config:profile")
        return render(
            request, self.template_name, self.get_context(form, persisted_profile)
        )


class POSSettingsUpdateView(CanManageBusinessSettingsMixin, View):
    template_name = "business_config/pos_settings_form.html"

    def get_business(self):
        business = getattr(self.request.user, "business", None)
        if business is None:
            raise PermissionDenied(
                "Se necesita un negocio para gestionar la configuración del TPV."
            )
        return business

    def get_settings(self):
        return get_object_or_404(POSSettings, business=self.get_business())

    def get(self, request):
        settings = self.get_settings()
        form = POSSettingsForm(instance=settings)
        return render(request, self.template_name, self.get_context(form, settings))

    def get_context(self, form, persisted_settings):
        return {
            "form": form,
            "current_settings": persisted_settings,
            "persisted_config": {
                field: str(getattr(persisted_settings, field))
                for field in POSSettingsForm.Meta.fields
            },
            "payment_methods": get_mvp_payment_methods_for_business(
                business=self.get_business()
            ),
        }

    def post(self, request):
        business = self.get_business()
        settings = get_object_or_404(POSSettings, business=business)
        persisted_settings = POSSettings.objects.get(pk=settings.pk)
        form = POSSettingsForm(data=request.POST, instance=settings)
        if form.is_valid():
            update_pos_settings(
                business=business, updated_by=request.user, **form.cleaned_data
            )
            messages.success(
                request, "Configuración del TPV actualizada correctamente."
            )
            return redirect("business_config:pos")
        return render(
            request, self.template_name, self.get_context(form, persisted_settings)
        )


class PaymentMethodUpdateView(CanManageBusinessSettingsMixin, View):
    template_name = "business_config/payment_method_form.html"

    def get_business(self):
        business = getattr(self.request.user, "business", None)
        if business is None:
            raise PermissionDenied("Se necesita un negocio para gestionar sus pagos.")
        return business

    def get_method(self):
        return get_mvp_payment_method_for_admin(
            business=self.get_business(), pk=self.kwargs["pk"]
        )

    def get(self, request, pk):
        method = self.get_method()
        return render(
            request,
            self.template_name,
            {"form": PaymentMethodAdminForm(instance=method), "method": method},
        )

    def post(self, request, pk):
        method = self.get_method()
        form = PaymentMethodAdminForm(request.POST, instance=method)
        if form.is_valid():
            update_payment_method_configuration(
                actor=request.user,
                business=self.get_business(),
                payment_method=method,
                **form.cleaned_data,
            )
            messages.success(request, "Método de pago actualizado correctamente.")
            return redirect("business_config:pos")
        return render(request, self.template_name, {"form": form, "method": method})
