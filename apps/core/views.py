from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied
from django.http import JsonResponse
from django.shortcuts import render
from django.views.generic import TemplateView

from apps.core.dashboard import build_dashboard_context, resolve_dashboard_period
from apps.core.selectors import get_home_operational_stores
from apps.core.shell import resolve_active_store


class HomeView(LoginRequiredMixin, TemplateView):
    template_name = "core/home.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user = self.request.user
        business = getattr(user, "business", None)
        if business is None and not user.is_superuser:
            raise PermissionDenied("El usuario debe pertenecer a un negocio.")

        administrative_mode = user.is_superuser and business is None
        operational_stores = get_home_operational_stores(user=user)
        context.update(
            {
                "business": business,
                "operational_stores": operational_stores,
                "administrative_mode": administrative_mode,
                "can_manage_users": user.is_superuser
                or user.role in {"owner", "manager"},
                "can_manage_business": bool(business)
                and (user.is_superuser or user.role == "owner"),
            }
        )
        if not administrative_mode:
            stores, active_store = resolve_active_store(self.request, user=user)
            requested_period, _period = resolve_dashboard_period(
                self.request.GET.get("period")
            )
            context.update(
                {
                    "active_store": active_store,
                    "has_operational_stores": bool(stores),
                    "period_key": requested_period,
                }
            )
            if active_store is not None:
                context.update(
                    build_dashboard_context(
                        business=business,
                        store=active_store,
                        user=user,
                        period_key=requested_period,
                    )
                )
        return context

    def get_template_names(self):
        if getattr(self.request, "htmx", False):
            return ["core/partials/_dashboard_content.html"]
        return [self.template_name]


def health_check(request):
    return JsonResponse({"status": "ok"}, status=200)


def csrf_failure(request, reason=""):
    """Render the generic forbidden page without exposing CSRF details."""

    return render(request, "403.html", status=403)
