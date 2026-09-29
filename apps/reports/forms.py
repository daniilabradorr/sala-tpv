from datetime import timedelta

from django import forms
from django.core.exceptions import ValidationError
from django.utils import timezone

from apps.reports.periods import report_period_from_dates
from apps.stores.models import Store
from apps.stores.selectors import get_stores_available_for_user
from apps.users.models import RoleChoices


class ReportFilterForm(forms.Form):
    PERIOD_CHOICES = (
        ("today", "Hoy"),
        ("7d", "7 días"),
        ("30d", "30 días"),
        ("month", "Este mes"),
        ("custom", "Personalizado"),
    )

    period = forms.ChoiceField(choices=PERIOD_CHOICES)
    date_from = forms.DateField(
        required=False, widget=forms.DateInput(attrs={"type": "date"})
    )
    date_to = forms.DateField(
        required=False, widget=forms.DateInput(attrs={"type": "date"})
    )
    store = forms.ChoiceField(label="Tienda")

    def __init__(self, *args, business, user, active_store=None, **kwargs):
        self.business = business
        self.user = user
        self.active_store = active_store
        super().__init__(*args, **kwargs)
        available = list(get_stores_available_for_user(user=user, only_active=True))
        if user.is_superuser:
            available = list(
                Store.objects.filter(business=business, is_active=True).order_by(
                    "name", "pk"
                )
            )
        self.allowed_stores = available
        all_business_ids = set(
            Store.objects.filter(business=business).values_list("pk", flat=True)
        )
        allowed_ids = {store.pk for store in available}
        self.can_select_all = (
            user.is_superuser
            or user.role == RoleChoices.OWNER
            or allowed_ids == all_business_ids
        )
        choices = [(str(store.pk), store.name) for store in available]
        if self.can_select_all:
            choices.insert(0, ("all", "Todas las tiendas"))
        self.fields["store"].choices = choices

    def clean(self):
        cleaned = super().clean()
        period_key = cleaned.get("period")
        date_from = cleaned.get("date_from")
        date_to = cleaned.get("date_to")
        today = timezone.localdate()
        if period_key == "today":
            date_from = date_to = today
        elif period_key == "7d":
            date_from, date_to = today - timedelta(days=6), today
        elif period_key == "30d":
            date_from, date_to = today - timedelta(days=29), today
        elif period_key == "month":
            date_from, date_to = today.replace(day=1), today
        elif period_key == "custom":
            if not date_from:
                self.add_error("date_from", "Indica la fecha inicial.")
            if not date_to:
                self.add_error("date_to", "Indica la fecha final.")
        if date_from and date_to and date_from > date_to:
            self.add_error(
                "date_to", "La fecha final debe ser igual o posterior a la inicial."
            )
        cleaned["date_from"] = date_from
        cleaned["date_to"] = date_to
        if date_from and date_to and not self.errors:
            cleaned["report_period"] = report_period_from_dates(
                date_from=date_from, date_to=date_to
            )
        value = cleaned.get("store")
        if value == "all":
            if not self.can_select_all:
                raise ValidationError("No tienes acceso a todas las tiendas.")
            cleaned["selected_store"] = None
        elif value:
            cleaned["selected_store"] = next(
                (store for store in self.allowed_stores if str(store.pk) == value), None
            )
            if cleaned["selected_store"] is None:
                self.add_error("store", "Selecciona una tienda autorizada.")
        return cleaned
