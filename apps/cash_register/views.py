from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.core import signing
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.cache import patch_vary_headers

from apps.cash_register.forms import (
    CashAdjustmentForm,
    CashCountReviewForm,
    CashInForm,
    CashOutForm,
    CashSessionCloseConfirmForm,
    CashSessionHistoryFilterForm,
    CashSessionOpenForm,
)
from apps.cash_register.models import CashRegister, CashSession
from apps.cash_register.selectors import (
    get_cash_register,
    get_cash_registers_for_store,
    get_cash_session_counts,
    get_cash_session_detail,
    get_cash_session_movements,
    get_cash_session_payment_summary,
    get_cash_session_physical_summary,
    get_cash_sessions_for_history,
    get_sales_for_cash_session,
)
from apps.cash_register.services import CashRegisterService
from apps.business_config.models import POSSettings
from apps.stores.models import Store
from apps.users.helpers import can_access_store


def _store(request, store_id):
    store = get_object_or_404(Store, pk=store_id, business=request.user.business)
    if not can_access_store(request.user, store):
        from django.core.exceptions import PermissionDenied

        raise PermissionDenied
    return store


@login_required
def register_list(request, store_id):
    store = _store(request, store_id)
    return render(
        request,
        "cash_register/register_list.html",
        {
            "store": store,
            "cash_registers": get_cash_registers_for_store(
                business=request.user.business, store=store
            ),
        },
    )


@login_required
def session_detail(request, store_id, session_id):
    store = _store(request, store_id)
    try:
        session = get_cash_session_detail(
            business=request.user.business, store=store, cash_session_id=session_id
        )
    except CashSession.DoesNotExist as exc:
        raise Http404("La sesión de caja no existe.") from exc
    tab = request.GET.get("tab", "summary")
    if tab not in {"summary", "sales", "movements", "counts"}:
        tab = "summary"
    context = {
        "store": store,
        "session": session,
        "active_tab": tab,
        "movements": get_cash_session_movements(
            business=request.user.business, store=store, cash_session=session
        ),
        "counts": get_cash_session_counts(
            business=request.user.business, store=store, cash_session=session
        ),
        "payment_summary": get_cash_session_payment_summary(
            business=request.user.business, store=store, cash_session=session
        ),
        "physical_summary": get_cash_session_physical_summary(
            business=request.user.business, store=store, cash_session=session
        ),
        "sales": get_sales_for_cash_session(
            business=request.user.business, store=store, cash_session=session
        ),
    }
    template = (
        "cash_register/partials/_session_tab.html"
        if request.headers.get("HX-Request") == "true"
        else "cash_register/session_detail.html"
    )
    response = render(
        request,
        template,
        context,
    )
    patch_vary_headers(response, ("HX-Request",))
    return response


@login_required
def open_session(request, store_id, cash_register_id=None):
    store = _store(request, store_id)
    register = None
    if cash_register_id is not None:
        try:
            register = get_cash_register(
                business=request.user.business,
                store=store,
                cash_register_id=cash_register_id,
            )
        except CashRegister.DoesNotExist as exc:
            raise Http404("La caja no existe.") from exc
    form = CashSessionOpenForm(
        request.POST or None,
        business=request.user.business,
        store=store,
        cash_register=register,
    )
    if request.method == "POST" and form.is_valid():
        selected_register = register or form.cleaned_data["cash_register"]
        try:
            session = CashRegisterService().open_cash_session(
                business=request.user.business,
                store_id=store.pk,
                cash_register_id=selected_register.pk,
                user=request.user,
                opening_amount=form.cleaned_data["opening_amount"],
            )
        except ValidationError as exc:
            for message in exc.messages:
                form.add_error(None, message)
        else:
            messages.success(request, "Caja abierta correctamente.")
            return redirect(
                "cash_register:session_detail",
                store_id=store.pk,
                session_id=session.pk,
            )
    template = (
        "cash_register/partials/_operation_form.html"
        if request.headers.get("HX-Request") == "true"
        else "cash_register/form.html"
    )
    response = render(
        request,
        template,
        {
            "form": form,
            "title": "Abrir caja",
            "description": "Inicia un nuevo turno indicando el efectivo físico inicial.",
            "submit_label": "Abrir caja",
            "operation_kind": "open",
            "cash_register": register,
            "store": store,
            "cancel_url": reverse("cash_register:register_list", args=[store.pk]),
        },
        status=422
        if request.method == "POST"
        and form.errors
        and request.headers.get("HX-Request") == "true"
        else 200,
    )
    patch_vary_headers(response, ("HX-Request",))
    return response


def _session_action(
    request,
    store_id,
    session_id,
    form_class,
    method,
    *,
    title,
    description,
    submit_label,
    operation_kind,
    success_message,
):
    store = _store(request, store_id)
    try:
        session = get_cash_session_detail(
            business=request.user.business, store=store, cash_session_id=session_id
        )
    except CashSession.DoesNotExist as exc:
        raise Http404("La sesión de caja no existe.") from exc
    form = form_class(request.POST or None)
    if request.method == "POST" and form.is_valid():
        data = form.cleaned_data
        common = dict(
            business=request.user.business,
            store_id=store.pk,
            cash_register_id=session.cash_register_id,
            cash_session_id=session.pk,
            user=request.user,
        )
        try:
            method(common, data)
        except ValidationError as exc:
            for message in exc.messages:
                form.add_error(None, message)
        else:
            messages.success(request, success_message)
            return redirect("cash_register:session_detail", store.pk, session.pk)
    template = (
        "cash_register/partials/_operation_form.html"
        if request.headers.get("HX-Request") == "true"
        else "cash_register/form.html"
    )
    response = render(
        request,
        template,
        {
            "form": form,
            "store": store,
            "session": session,
            "title": title,
            "description": description,
            "submit_label": submit_label,
            "operation_kind": operation_kind,
            "cancel_url": reverse(
                "cash_register:session_detail", args=[store.pk, session.pk]
            ),
        },
        status=422
        if request.method == "POST"
        and form.errors
        and request.headers.get("HX-Request") == "true"
        else 200,
    )
    patch_vary_headers(response, ("HX-Request",))
    return response


@login_required
def cash_in(request, store_id, session_id):
    return _session_action(
        request,
        store_id,
        session_id,
        CashInForm,
        lambda common, data: CashRegisterService().register_cash_in(**common, **data),
        title="Entrada de efectivo",
        description="Registra dinero que entra físicamente en la caja.",
        submit_label="Registrar entrada",
        operation_kind="cash-in",
        success_message="Entrada de efectivo registrada.",
    )


@login_required
def cash_out(request, store_id, session_id):
    return _session_action(
        request,
        store_id,
        session_id,
        CashOutForm,
        lambda common, data: CashRegisterService().register_cash_out(**common, **data),
        title="Salida de efectivo",
        description="Registra una retirada física de efectivo.",
        submit_label="Registrar salida",
        operation_kind="cash-out",
        success_message="Salida de efectivo registrada.",
    )


@login_required
def adjustment(request, store_id, session_id):
    return _session_action(
        request,
        store_id,
        session_id,
        CashAdjustmentForm,
        lambda common, data: CashRegisterService().register_adjustment(
            **common, **data
        ),
        title="Ajuste de caja",
        description="Corrige el saldo esperado con trazabilidad. Indica si el efectivo entra o sale.",
        submit_label="Registrar ajuste",
        operation_kind="adjustment",
        success_message="Ajuste de caja registrado.",
    )


@login_required
def review(request, store_id, session_id):
    return _session_action(
        request,
        store_id,
        session_id,
        CashCountReviewForm,
        lambda common, data: CashRegisterService().review_cash_count(**common, **data),
        title="Arqueo de control",
        description="Cuenta el efectivo actual sin cerrar la sesión. La caja permanecerá abierta.",
        submit_label="Guardar arqueo",
        operation_kind="review",
        success_message="Arqueo guardado. La caja sigue abierta.",
    )


@login_required
def close(request, store_id, session_id):
    store = _store(request, store_id)
    try:
        session = get_cash_session_detail(
            business=request.user.business, store=store, cash_session_id=session_id
        )
    except CashSession.DoesNotExist as exc:
        raise Http404("La sesión de caja no existe.") from exc
    cancel_url = reverse("cash_register:session_detail", args=[store.pk, session.pk])
    if request.method == "POST" and request.POST.get("confirm") == "yes":
        settings = POSSettings.objects.filter(business=request.user.business).first()
        form = CashSessionCloseConfirmForm(
            request.POST,
            require_pin=bool(settings and settings.require_pin_for_sensitive_actions),
        )
        if form.is_valid():
            try:
                payload = signing.loads(
                    form.cleaned_data["payload"], salt="cash-close", max_age=1800
                )
                CashRegisterService().close_cash_session(
                    business=request.user.business,
                    store_id=store.pk,
                    cash_register_id=session.cash_register_id,
                    cash_session_id=session.pk,
                    user=request.user,
                    counted_cash_amount=payload["counted_amount"],
                    notes=payload["notes"],
                    pin=form.cleaned_data["pin"],
                )
            except (ValidationError, signing.BadSignature) as exc:
                session.refresh_from_db()
                if session.status == CashSession.Status.CLOSED:
                    return render(
                        request,
                        "cash_register/close_conflict.html",
                        {"store": store, "session": session},
                        status=409,
                    )
                for message in getattr(exc, "messages", [str(exc)]):
                    form.add_error(None, message)
            else:
                messages.success(request, "Caja cerrada correctamente.")
                return redirect("cash_register:session_detail", store.pk, session.pk)
        return render(
            request,
            "cash_register/close_confirm.html",
            {"store": store, "session": session, "form": form},
            status=422 if request.headers.get("HX-Request") == "true" else 200,
        )
    form = CashCountReviewForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        payload = signing.dumps(
            {
                "counted_amount": str(form.cleaned_data["counted_amount"]),
                "notes": form.cleaned_data["notes"],
            },
            salt="cash-close",
        )
        settings = POSSettings.objects.filter(business=request.user.business).first()
        confirm_form = CashSessionCloseConfirmForm(
            require_pin=bool(settings and settings.require_pin_for_sensitive_actions),
            initial={"payload": payload},
        )
        return render(
            request,
            "cash_register/close_confirm.html",
            {
                "store": store,
                "session": session,
                "form": confirm_form,
                "counted_amount": form.cleaned_data["counted_amount"],
                "difference": form.cleaned_data["counted_amount"]
                - session.expected_cash_amount,
            },
        )
    return render(
        request,
        "cash_register/form.html",
        {
            "form": form,
            "store": store,
            "session": session,
            "title": "Cerrar caja",
            "description": "Cuenta el efectivo final antes de revisar el cierre.",
            "submit_label": "Continuar",
            "operation_kind": "close",
            "cancel_url": cancel_url,
        },
    )


@login_required
def history(request, store_id):
    store = _store(request, store_id)
    form = CashSessionHistoryFilterForm(
        request.GET or None, business=request.user.business, store=store
    )
    filters = form.cleaned_data if form.is_valid() else {}
    queryset = get_cash_sessions_for_history(
        business=request.user.business, store=store, filters=filters
    )
    page_obj = Paginator(queryset, 25).get_page(request.GET.get("page"))
    return render(
        request,
        "cash_register/history.html",
        {
            "store": store,
            "form": form,
            "sessions": page_obj,
            "page_obj": page_obj,
        },
    )
