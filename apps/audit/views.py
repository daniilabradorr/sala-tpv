from collections import OrderedDict
from datetime import timedelta

from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from django.utils import formats, timezone
from django.views import View

from apps.audit.forms import ActivityFilterForm
from apps.audit.presentation import EVENT_LABELS, MODULE_LABELS, present_event
from apps.audit.selectors import get_audit_events
from apps.stores.selectors import get_stores_available_for_user
from apps.users.mixins import CanViewActivityMixin
from apps.users.models import RoleChoices


class ActivityContextMixin(CanViewActivityMixin):
    def get_business(self):
        business = getattr(self.request.user, "business", None)
        if business is None:
            raise PermissionDenied("Actividad requiere un contexto de negocio.")
        return business

    def get_scope_stores(self):
        if self.request.user.role == RoleChoices.OWNER:
            return None
        return get_stores_available_for_user(user=self.request.user, only_active=False)

    def get_base_queryset(self):
        return get_audit_events(
            business=self.get_business(), stores=self.get_scope_stores()
        )


class ActivityView(ActivityContextMixin, View):
    http_method_names = ["get"]
    page_size = 25

    def get(self, request):
        data = request.GET.copy()
        data.setdefault("period", "30d")
        form = ActivityFilterForm(data, business=self.get_business(), user=request.user)
        if not form.is_valid():
            context = {"form": form}
            if request.headers.get("HX-Request") == "true":
                response = render(
                    request,
                    "audit/partials/_filters.html",
                    context,
                    status=422,
                )
                response["HX-Retarget"] = "#activity-filters"
                response["HX-Reswap"] = "outerHTML"
                return response
            return render(request, "audit/activity.html", context, status=422)

        cleaned = form.cleaned_data
        queryset = get_audit_events(
            business=self.get_business(),
            stores=self.get_scope_stores(),
            store=cleaned["store"],
            user=cleaned["user"],
            module=cleaned["module"],
            event_type=cleaned["event_type"],
            period=cleaned["period_range"],
            query=cleaned["q"],
        )
        page = Paginator(queryset, self.page_size).get_page(request.GET.get("page"))
        presented = [present_event(event, user=request.user) for event in page]
        groups = self._groups(presented)
        context = {
            "form": form,
            "page_obj": page,
            "activity_groups": groups,
            "chips": self._chips(cleaned),
            "pagination_query": self._query_without("page"),
        }
        if request.headers.get("HX-Request") == "true":
            return render(request, "audit/partials/_results.html", context)
        return render(request, "audit/activity.html", context)

    def _groups(self, presented):
        today = timezone.localdate()
        groups = OrderedDict()
        for item in presented:
            day = item["created_at"].date()
            if day == today:
                label = "Hoy"
            elif day == today - timedelta(days=1):
                label = "Ayer"
            else:
                label = formats.date_format(day, "j F Y")
            groups.setdefault((day, label), []).append(item)
        return [
            {"day": day, "label": label, "items": items}
            for (day, label), items in groups.items()
        ]

    def _query_without(self, *keys):
        query = self.request.GET.copy()
        for key in keys:
            query.pop(key, None)
        return query.urlencode()

    def _chip_url(self, *keys):
        query = self.request.GET.copy()
        query.pop("page", None)
        for key in keys:
            query.pop(key, None)
        query.setdefault("period", "30d")
        base = reverse("audit:activity")
        return f"{base}?{query.urlencode()}" if query else base

    def _chips(self, cleaned):
        chips = []
        raw = self.request.GET
        specs = (
            ("q", f"“{cleaned['q']}”" if cleaned["q"] else "", ("q",)),
            ("store", cleaned["store"].name if cleaned["store"] else "", ("store",)),
            (
                "user",
                "Sistema"
                if cleaned["user"] == "system"
                else str(cleaned["user"] or ""),
                ("user",),
            ),
            (
                "module",
                MODULE_LABELS.get(cleaned["module"], ""),
                ("module", "event_type"),
            ),
            (
                "event_type",
                EVENT_LABELS.get(cleaned["event_type"], ""),
                ("event_type",),
            ),
            (
                "period",
                dict(ActivityFilterForm.PERIOD_CHOICES).get(cleaned["period"], ""),
                ("period", "date_from", "date_to"),
            ),
        )
        for key, label, removals in specs:
            if label and (key != "period" or raw.get("period", "30d") != "30d"):
                chips.append({"label": label, "url": self._chip_url(*removals)})
        return chips


class ActivityDetailView(ActivityContextMixin, View):
    http_method_names = ["get"]

    def get(self, request, pk):
        event = get_object_or_404(self.get_base_queryset(), pk=pk)
        context = {
            "activity": present_event(event, user=request.user, detail=True),
            "show_private_technical": request.user.role == RoleChoices.OWNER,
        }
        return render(request, "audit/partials/_event_detail.html", context)
