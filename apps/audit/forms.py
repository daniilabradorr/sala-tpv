from datetime import timedelta

from django import forms
from django.utils import timezone

from apps.audit.constants import AUDIT_EVENT_TYPES, EVENT_MODULES
from apps.audit.presentation import EVENT_LABELS, MODULE_LABELS
from apps.reports.periods import report_period_for_day, report_period_from_dates
from apps.stores.models import Store
from apps.stores.selectors import get_stores_available_for_user
from apps.users.models import CustomUser, RoleChoices


class ActivityFilterForm(forms.Form):
    PERIOD_CHOICES = (
        ("today", "Hoy"),
        ("yesterday", "Ayer"),
        ("7d", "7 días"),
        ("30d", "30 días"),
        ("custom", "Personalizado"),
    )
    q = forms.CharField(required=False, label="Buscar", max_length=200)
    period = forms.ChoiceField(choices=PERIOD_CHOICES, label="Periodo")
    date_from = forms.DateField(
        required=False, label="Desde", widget=forms.DateInput(attrs={"type": "date"})
    )
    date_to = forms.DateField(
        required=False, label="Hasta", widget=forms.DateInput(attrs={"type": "date"})
    )
    store = forms.ChoiceField(label="Tienda", required=False)
    user = forms.ChoiceField(label="Actor", required=False)
    module = forms.ChoiceField(label="Módulo", required=False)
    event_type = forms.ChoiceField(label="Evento", required=False)

    def __init__(self, *args, business, user, **kwargs):
        self.business = business
        self.request_user = user
        super().__init__(*args, **kwargs)
        available = get_stores_available_for_user(user=user, only_active=False)
        if user.is_superuser:
            available = Store.objects.filter(business=business).order_by("name", "pk")
        self.allowed_stores = list(available)
        all_label = (
            "Todas las tiendas"
            if user.is_superuser or user.role == RoleChoices.OWNER
            else "Todas mis tiendas"
        )
        self.fields["store"].choices = [("", all_label)] + [
            (str(item.pk), item.name) for item in self.allowed_stores
        ]
        users = CustomUser.objects.filter(business=business).order_by(
            "first_name", "last_name", "email"
        )
        self.allowed_users = list(users)
        self.fields["user"].choices = [("", "Todos"), ("system", "Sistema")] + [
            (str(item.pk), str(item)) for item in self.allowed_users
        ]
        self.fields["module"].choices = [("", "Todos los módulos")] + [
            (key, MODULE_LABELS[key]) for key in MODULE_LABELS
        ]
        selected_module = self.data.get("module") if self.is_bound else None
        events = (
            [key for key, module in EVENT_MODULES.items() if module == selected_module]
            if selected_module in MODULE_LABELS
            else sorted(AUDIT_EVENT_TYPES)
        )
        self.fields["event_type"].choices = [("", "Todos los eventos")] + [
            (key, EVENT_LABELS[key]) for key in events
        ]
        for field in self.fields.values():
            field.widget.attrs.setdefault("class", "form-control")

    def full_clean(self):
        super().full_clean()
        for name, errors in self.errors.items():
            if name in self.fields and errors:
                self.fields[name].widget.attrs.update(
                    {
                        "aria-invalid": "true",
                        "aria-describedby": f"id_{name}-errors",
                    }
                )

    def clean_store(self):
        value = self.cleaned_data["store"]
        if not value:
            return None
        store = next(
            (item for item in self.allowed_stores if str(item.pk) == value), None
        )
        if store is None:
            raise forms.ValidationError("Selecciona una tienda autorizada.")
        return store

    def clean_user(self):
        value = self.cleaned_data["user"]
        if not value:
            return None
        if value == "system":
            return "system"
        selected = next(
            (item for item in self.allowed_users if str(item.pk) == value), None
        )
        if selected is None:
            raise forms.ValidationError("Selecciona un usuario del negocio.")
        return selected

    def clean(self):
        cleaned = super().clean()
        period_key = cleaned.get("period")
        today = timezone.localdate()
        date_from, date_to = cleaned.get("date_from"), cleaned.get("date_to")
        if period_key == "today":
            date_from = date_to = today
        elif period_key == "yesterday":
            date_from = date_to = today - timedelta(days=1)
        elif period_key == "7d":
            date_from, date_to = today - timedelta(days=6), today
        elif period_key == "30d":
            date_from, date_to = today - timedelta(days=29), today
        elif period_key == "custom":
            if not date_from:
                self.add_error("date_from", "Indica la fecha inicial.")
            if not date_to:
                self.add_error("date_to", "Indica la fecha final.")
        if date_from and date_to and date_from > date_to:
            self.add_error(
                "date_to", "La fecha final debe ser igual o posterior a la inicial."
            )
        cleaned["date_from"], cleaned["date_to"] = date_from, date_to
        if date_from and date_to and not self.errors:
            cleaned["period_range"] = (
                report_period_for_day(day=date_from)
                if date_from == date_to
                else report_period_from_dates(date_from=date_from, date_to=date_to)
            )
        module, event_type = cleaned.get("module"), cleaned.get("event_type")
        if event_type and EVENT_MODULES.get(event_type) != module and module:
            self.add_error("event_type", "El evento no pertenece al módulo elegido.")
        return cleaned
