from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.http import require_http_methods

from apps.onboarding.forms import OnboardingForm
from apps.onboarding.services import (
    OnboardingDuplicateBusinessError,
    OnboardingError,
    OnboardingService,
)
from apps.stores.models import Store

RESULT_SESSION_KEY = "onboarding_result"


@require_http_methods(["GET", "POST"])
def start(request):
    if request.user.is_authenticated:
        return redirect("core:home")
    request.netxodo_skip_app_shell = True

    form = OnboardingForm(request.POST or None)
    initial_step = 1
    if request.method == "POST" and form.is_valid():
        try:
            result = OnboardingService.create_business(**form.service_data())
        except OnboardingDuplicateBusinessError:
            form.add_accessible_error(
                "tax_identifier", "Ya existe un negocio con esta identidad fiscal."
            )
        except OnboardingError as exc:
            form.add_error(None, str(exc))
        except ValidationError:
            # Model full_clean() remains a final domain safety net. Do not leak
            # its field map, constraint names, or values on this public form.
            form.add_error(
                None,
                "No hemos podido validar los datos. Revisa el formulario e inténtalo de nuevo.",
            )
        else:
            login(
                request,
                result.owner,
                backend="django.contrib.auth.backends.ModelBackend",
            )
            request.session[RESULT_SESSION_KEY] = {
                "business_id": result.business.pk,
                "business_name": result.business.name,
                "store_id": result.store.pk,
                "store_name": result.store.name,
                "owner_first_name": result.owner.first_name,
            }
            return redirect("onboarding:success")

    if form.is_bound and form.errors:
        initial_step = _first_error_step(form)
    return render(
        request,
        "onboarding/start.html",
        {"form": form, "initial_step": initial_step},
    )


def _first_error_step(form):
    step_two = {name for name in form.fields if name.startswith("store_")} | {
        "same_business_address"
    }
    step_three = {name for name in form.fields if name.startswith("owner_")}
    error_names = set(form.errors)
    if error_names & (set(form.fields) - step_two - step_three):
        return 1
    if error_names & step_two:
        return 2
    if error_names & step_three:
        return 3
    return 1


@login_required
def success(request):
    metadata = request.session.get(RESULT_SESSION_KEY)
    if not metadata or metadata.get("business_id") != request.user.business_id:
        return redirect("core:home")
    request.netxodo_skip_app_shell = True
    return render(request, "onboarding/success.html", {"onboarding": metadata})


@login_required
def welcome(request):
    metadata = request.session.get(RESULT_SESSION_KEY)
    if not metadata or metadata.get("business_id") != request.user.business_id:
        return redirect("core:home")
    store_id = metadata.get("store_id")
    if (
        not store_id
        or not Store.objects.filter(
            pk=store_id, business_id=request.user.business_id
        ).exists()
    ):
        return redirect("core:home")
    request.netxodo_skip_app_shell = True
    cash_url = reverse("cash_register:open", kwargs={"store_id": store_id})
    return render(request, "onboarding/welcome.html", {"cash_url": cash_url})
