from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied
from django.http import JsonResponse
from django.shortcuts import render
from django.views.generic import TemplateView

from apps.core.selectors import get_home_operational_stores


class HomeView(LoginRequiredMixin, TemplateView):
    template_name = "core/home.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user = self.request.user
        business = getattr(user, "business", None)
        if business is None and not user.is_superuser:
            raise PermissionDenied("El usuario debe pertenecer a un negocio.")

        context.update(
            {
                "business": business,
                "operational_stores": get_home_operational_stores(user=user),
                "administrative_mode": user.is_superuser and business is None,
                "can_manage_users": user.is_superuser
                or user.role in {"owner", "manager"},
                "can_manage_business": bool(business)
                and (user.is_superuser or user.role == "owner"),
            }
        )
        return context


def health_check(request):
    return JsonResponse({"status": "ok"}, status=200)


def csrf_failure(request, reason=""):
    """Render the generic forbidden page without exposing CSRF details."""

    return render(request, "403.html", status=403)
