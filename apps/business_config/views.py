from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, redirect, render
from django.views import View

from apps.business_config.forms import BusinessProfileForm, POSSettingsForm
from apps.business_config.models import BusinessProfile, POSSettings
from apps.business_config.services import update_business_profile, update_pos_settings
from apps.users.mixins import CanManageBusinessSettingsMixin


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
        form = BusinessProfileForm(instance=self.get_profile())
        return render(request, self.template_name, {"form": form})

    def post(self, request):
        business = self.get_business()
        profile = get_object_or_404(BusinessProfile, business=business)
        form = BusinessProfileForm(data=request.POST, instance=profile)
        if form.is_valid():
            update_business_profile(business=business, **form.cleaned_data)
            messages.success(request, "Datos de empresa actualizados correctamente.")
            return redirect("business_config:profile")
        return render(request, self.template_name, {"form": form})


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
        form = POSSettingsForm(instance=self.get_settings())
        return render(request, self.template_name, {"form": form})

    def post(self, request):
        business = self.get_business()
        settings = get_object_or_404(POSSettings, business=business)
        form = POSSettingsForm(data=request.POST, instance=settings)
        if form.is_valid():
            update_pos_settings(business=business, **form.cleaned_data)
            messages.success(
                request, "Configuración del TPV actualizada correctamente."
            )
            return redirect("business_config:pos")
        return render(request, self.template_name, {"form": form})
