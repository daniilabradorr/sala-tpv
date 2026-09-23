from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core import signing
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.vary import vary_on_headers

from apps.business_config.models import POSSettings
from apps.cash_register.forms import (
    CashAdjustmentForm,
    CashCountReviewForm,
    CashHistoryFilterForm,
    CashInForm,
    CashOutForm,
    CashSessionCloseForm,
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
from apps.core.htmx import add_hx_trigger
from apps.stores.models import Store
from apps.users.helpers import (
    can_access_store,
    can_close_cash_register,
    can_open_cash_register,
)


def _hx(request):
    return request.headers.get("HX-Request") == "true"


def _store(request, store_id):
    store = get_object_or_404(Store, pk=store_id, business=request.user.business)
    if not can_access_store(request.user, store):
        raise PermissionDenied
    return store


def _session(request, store, session_id):
    try:
        return get_cash_session_detail(
            business=request.user.business, store=store, cash_session_id=session_id
        )
    except CashSession.DoesNotExist as exc:
        raise Http404("La sesión de caja no existe.") from exc


def _service_errors(form, exc, mapping=None):
    mapping = mapping or {}
    if hasattr(exc, "message_dict"):
        for key, values in exc.message_dict.items():
            field = mapping.get(key, key if key in form.fields else None)
            for value in values:
                form.add_error(field, value)
    else:
        for value in exc.messages:
            form.add_error(None, value)


def _form_response(request, context, status=200, template="cash_register/form.html"):
    if _hx(request):
        template = "cash_register/partials/_operation_dialog.html"
    return render(request, template, context, status=status)


def _hx_redirect(request, url):
    if not _hx(request):
        return redirect(url)
    response = HttpResponse(status=204)
    response["HX-Redirect"] = url
    return response


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
            "can_open": can_open_cash_register(request.user, store),
        },
    )


@login_required
@vary_on_headers("HX-Request")
def session_detail(request, store_id, session_id):
    store = _store(request, store_id)
    session = _session(request, store, session_id)
    tab = request.GET.get("tab", "summary")
    if tab not in {"summary", "sales", "movements", "counts"}:
        tab = "summary"
    context = {"store": store, "session": session, "tab": tab}
    if tab == "summary":
        context["payment_summary"] = get_cash_session_payment_summary(
            business=request.user.business, store=store, cash_session=session
        )
        context["physical_summary"] = get_cash_session_physical_summary(
            business=request.user.business, store=store, cash_session=session
        )
    elif tab == "sales":
        context["sales"] = get_sales_for_cash_session(
            business=request.user.business, store=store, cash_session=session
        )
    elif tab == "movements":
        context["movements"] = get_cash_session_movements(
            business=request.user.business, store=store, cash_session=session
        )
    else:
        context["counts"] = get_cash_session_counts(
            business=request.user.business, store=store, cash_session=session
        )
    context["can_close"] = can_close_cash_register(request.user, store)
    return render(
        request,
        "cash_register/partials/_session_tab.html"
        if _hx(request)
        else "cash_register/session_detail.html",
        context,
    )


@login_required
@vary_on_headers("HX-Request")
def open_session(request, store_id, cash_register_id=None):
    store = _store(request, store_id)
    if not can_open_cash_register(request.user, store):
        raise PermissionDenied
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
        try:
            session = CashRegisterService().open_cash_session(
                business=request.user.business,
                store_id=store.pk,
                cash_register_id=(register or form.cleaned_data["cash_register"]).pk,
                user=request.user,
                opening_amount=form.cleaned_data["opening_amount"],
            )
        except ValidationError as exc:
            _service_errors(form, exc, {"cash_session": None})
        else:
            messages.success(request, "Caja abierta correctamente.")
            return _hx_redirect(
                request,
                reverse("cash_register:session_detail", args=[store.pk, session.pk]),
            )
    context = {
        "form": form,
        "title": "Abrir caja",
        "description": "Introduce el efectivo físico que hay actualmente en el cajón.",
        "submit_label": "Abrir caja",
        "operation_kind": "open",
        "cash_register": register,
        "store": store,
        "cancel_url": reverse("cash_register:register_list", args=[store.pk]),
    }
    return _form_response(
        request, context, 422 if _hx(request) and request.method == "POST" else 200
    )


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
    session = _session(request, store, session_id)
    form = form_class(request.POST or None)
    if request.method == "POST" and form.is_valid():
        common = dict(
            business=request.user.business,
            store_id=store.pk,
            cash_register_id=session.cash_register_id,
            cash_session_id=session.pk,
            user=request.user,
        )
        try:
            method(common, form.cleaned_data)
        except ValidationError as exc:
            _service_errors(
                form,
                exc,
                {"counted_cash_amount": "counted_amount", "cash_session": None},
            )
        else:
            messages.success(request, success_message)
            if not _hx(request):
                return redirect("cash_register:session_detail", store.pk, session.pk)
            response = HttpResponse(status=204)
            return add_hx_trigger(
                response,
                {
                    "nx:close-modal": {"id": "cash-operation-dialog"},
                    "nx:refresh-region": {"selector": "#cash-tab-panel"},
                },
            )
    context = {
        "form": form,
        "store": store,
        "session": session,
        "title": title,
        "description": description,
        "submit_label": submit_label,
        "operation_kind": operation_kind,
        "expected_cents": int(session.expected_cash_amount * 100),
        "cancel_url": reverse(
            "cash_register:session_detail", args=[store.pk, session.pk]
        ),
    }
    return _form_response(
        request, context, 422 if _hx(request) and request.method == "POST" else 200
    )


@login_required
@vary_on_headers("HX-Request")
def cash_in(request, store_id, session_id):
    return _session_action(
        request,
        store_id,
        session_id,
        CashInForm,
        lambda c, d: CashRegisterService().register_cash_in(**c, **d),
        title="Entrada de efectivo",
        description="Registra dinero que entra físicamente en la caja.",
        submit_label="Registrar entrada",
        operation_kind="cash-in",
        success_message="Entrada de efectivo registrada.",
    )


@login_required
@vary_on_headers("HX-Request")
def cash_out(request, store_id, session_id):
    return _session_action(
        request,
        store_id,
        session_id,
        CashOutForm,
        lambda c, d: CashRegisterService().register_cash_out(**c, **d),
        title="Salida de efectivo",
        description="Registra una retirada física de efectivo.",
        submit_label="Registrar salida",
        operation_kind="cash-out",
        success_message="Salida de efectivo registrada.",
    )


@login_required
@vary_on_headers("HX-Request")
def adjustment(request, store_id, session_id):
    return _session_action(
        request,
        store_id,
        session_id,
        CashAdjustmentForm,
        lambda c, d: CashRegisterService().register_adjustment(**c, **d),
        title="Ajuste de caja",
        description="Los ajustes quedan registrados en el historial.",
        submit_label="Registrar ajuste",
        operation_kind="adjustment",
        success_message="Ajuste de caja registrado.",
    )


@login_required
@vary_on_headers("HX-Request")
def review(request, store_id, session_id):
    return _session_action(
        request,
        store_id,
        session_id,
        CashCountReviewForm,
        lambda c, d: CashRegisterService().review_cash_count(**c, **d),
        title="Arqueo de control",
        description="La caja seguirá abierta.",
        submit_label="Guardar arqueo",
        operation_kind="review",
        success_message="Arqueo guardado. La caja sigue abierta.",
    )


@login_required
@vary_on_headers("HX-Request")
def close(request, store_id, session_id):
    store = _store(request, store_id)
    session = _session(request, store, session_id)
    if not can_close_cash_register(request.user, store):
        raise PermissionDenied
    require_pin = (
        POSSettings.objects.filter(business=request.user.business)
        .values_list("require_pin_for_sensitive_actions", flat=True)
        .first()
        or False
    )
    confirm = request.method == "POST" and request.POST.get("step") == "confirm"
    if confirm:
        payload_error = None
        try:
            payload = signing.loads(
                request.POST.get("close_payload", ""), salt="cash-close", max_age=1800
            )
        except signing.BadSignature:
            payload = {}
            payload_error = (
                "La revisión de cierre ha caducado o no es válida. Vuelve a prepararla."
            )
        expected_binding = {
            "business_id": request.user.business_id,
            "store_id": store.pk,
            "cash_session_id": session.pk,
            "user_id": request.user.pk,
        }
        if not payload_error and any(
            payload.get(key) != value for key, value in expected_binding.items()
        ):
            payload_error = "Esta revisión pertenece a otra caja, sesión o usuario. Vuelve a prepararla."
        if payload_error:
            form = CashSessionCloseForm()
            form.fields.pop("pin")
            context = {
                "form": form,
                "close_payload_error": payload_error,
                "store": store,
                "session": session,
                "title": "Cerrar caja",
                "description": "Cuenta el efectivo final. Continuar todavía no cierra el turno.",
                "submit_label": "Continuar",
                "operation_kind": "close",
                "expected_cents": int(session.expected_cash_amount * 100),
                "cancel_url": reverse(
                    "cash_register:session_detail", args=[store.pk, session.pk]
                ),
            }
            return _form_response(request, context, 422 if _hx(request) else 200)
        form = CashSessionCloseForm(
            {
                "counted_amount": payload.get("counted_amount"),
                "notes": payload.get("notes", ""),
                "pin": request.POST.get("pin", ""),
            }
        )
        if not require_pin:
            form.fields.pop("pin")
        if form.is_valid():
            try:
                CashRegisterService().close_cash_session(
                    business=request.user.business,
                    store_id=store.pk,
                    cash_register_id=session.cash_register_id,
                    cash_session_id=session.pk,
                    user=request.user,
                    counted_cash_amount=form.cleaned_data["counted_amount"],
                    notes=form.cleaned_data["notes"],
                    pin=form.cleaned_data.get("pin"),
                )
            except ValidationError as exc:
                if not session.is_open or "cerrada" in " ".join(exc.messages).lower():
                    response = render(
                        request,
                        "cash_register/partials/_close_conflict.html",
                        {
                            "store": store,
                            "session": _session(request, store, session_id),
                        },
                        status=409,
                    )
                    response["X-Netxodo-Allow-Error-Swap"] = "true"
                    return response
                _service_errors(form, exc, {"counted_cash_amount": "counted_amount"})
                context = {
                    "store": store,
                    "session": session,
                    "payload": request.POST.get("close_payload", ""),
                    "counted_amount": form.data.get("counted_amount"),
                    "notes": form.data.get("notes", ""),
                    "difference": form.cleaned_data.get("counted_amount", 0)
                    - session.expected_cash_amount,
                    "require_pin": require_pin,
                    "pin_errors": form["pin"].errors if "pin" in form.fields else (),
                }
                return render(
                    request,
                    "cash_register/partials/_close_confirm.html"
                    if _hx(request)
                    else "cash_register/close_confirm.html",
                    context,
                    status=422 if _hx(request) else 200,
                )
            else:
                messages.success(request, "Caja cerrada correctamente.")
                return _hx_redirect(
                    request,
                    reverse(
                        "cash_register:session_detail", args=[store.pk, session.pk]
                    ),
                )
    else:
        form = CashSessionCloseForm(request.POST or None)
        form.fields.pop("pin")
        if request.method == "POST" and form.is_valid():
            payload = signing.dumps(
                {
                    "counted_amount": str(form.cleaned_data["counted_amount"]),
                    "notes": form.cleaned_data["notes"],
                    "business_id": request.user.business_id,
                    "store_id": store.pk,
                    "cash_session_id": session.pk,
                    "user_id": request.user.pk,
                },
                salt="cash-close",
            )
            context = {
                "store": store,
                "session": session,
                "payload": payload,
                "counted_amount": form.cleaned_data["counted_amount"],
                "notes": form.cleaned_data["notes"],
                "difference": form.cleaned_data["counted_amount"]
                - session.expected_cash_amount,
                "require_pin": require_pin,
            }
            return render(
                request,
                "cash_register/partials/_close_confirm.html"
                if _hx(request)
                else "cash_register/close_confirm.html",
                context,
            )
    context = {
        "form": form,
        "store": store,
        "session": session,
        "title": "Cerrar caja",
        "description": "Cuenta el efectivo final. Continuar todavía no cierra el turno.",
        "submit_label": "Continuar",
        "operation_kind": "close",
        "expected_cents": int(session.expected_cash_amount * 100),
        "cancel_url": reverse(
            "cash_register:session_detail", args=[store.pk, session.pk]
        ),
    }
    return _form_response(
        request, context, 422 if _hx(request) and request.method == "POST" else 200
    )


@login_required
@vary_on_headers("HX-Request")
def history(request, store_id):
    store = _store(request, store_id)
    form = CashHistoryFilterForm(
        request.GET or None, business=request.user.business, store=store
    )
    filters = form.cleaned_data if form.is_valid() else {}
    queryset = get_cash_sessions_for_history(
        business=request.user.business,
        store=store,
        cash_register_id=getattr(filters.get("cash_register"), "pk", None),
        user_id=getattr(filters.get("user"), "pk", None),
        date_from=filters.get("date_from"),
        date_to=filters.get("date_to"),
    )
    page = Paginator(queryset, 25).get_page(request.GET.get("page"))
    query = request.GET.copy()
    query.pop("page", None)
    context = {
        "store": store,
        "form": form,
        "page_obj": page,
        "sessions": page.object_list,
        "has_filters": any(
            request.GET.get(k)
            for k in ("cash_register", "user", "date_from", "date_to")
        ),
        "query_string": query.urlencode(),
    }
    return render(
        request,
        "cash_register/partials/_history_results.html"
        if _hx(request)
        else "cash_register/history.html",
        context,
    )
