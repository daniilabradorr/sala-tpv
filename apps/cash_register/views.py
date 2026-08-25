from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.shortcuts import get_object_or_404, redirect, render

from apps.cash_register.forms import (
    CashAdjustmentForm,
    CashCountReviewForm,
    CashInForm,
    CashOutForm,
    CashSessionCloseForm,
    CashSessionOpenForm,
)
from apps.cash_register.selectors import (
    get_cash_registers_for_store,
    get_cash_session_counts,
    get_cash_session_detail,
    get_cash_session_movements,
    get_cash_session_payment_summary,
    get_closed_cash_sessions,
)
from apps.cash_register.services import CashRegisterService
from apps.stores.models import Store
from apps.users.helpers import can_access_store


def _store(request, store_id):
    store = get_object_or_404(Store, pk=store_id, business=request.user.business)
    if not can_access_store(request.user, store):
        from django.core.exceptions import PermissionDenied

        raise PermissionDenied
    return store


def _run(request, operation, success_url):
    try:
        operation()
    except ValidationError as exc:
        messages.error(request, " ".join(exc.messages))
    else:
        messages.success(request, "Operación de caja completada.")
    return redirect(success_url)


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
    session = get_cash_session_detail(
        business=request.user.business, store=store, cash_session_id=session_id
    )
    return render(
        request,
        "cash_register/session_detail.html",
        {
            "store": store,
            "session": session,
            "movements": get_cash_session_movements(
                business=request.user.business, store=store, cash_session=session
            ),
            "counts": get_cash_session_counts(
                business=request.user.business, store=store, cash_session=session
            ),
            "payment_summary": get_cash_session_payment_summary(
                business=request.user.business, store=store, cash_session=session
            ),
        },
    )


@login_required
def open_session(request, store_id):
    store = _store(request, store_id)
    form = CashSessionOpenForm(
        request.POST or None, business=request.user.business, store=store
    )
    if request.method == "POST" and form.is_valid():
        register = form.cleaned_data["cash_register"]
        return _run(
            request,
            lambda: CashRegisterService().open_cash_session(
                business=request.user.business,
                store_id=store.pk,
                cash_register_id=register.pk,
                user=request.user,
                opening_amount=form.cleaned_data["opening_amount"],
            ),
            f"/cash-register/stores/{store.pk}/",
        )
    return render(
        request, "cash_register/form.html", {"form": form, "title": "Abrir caja"}
    )


def _session_action(request, store_id, session_id, form_class, method):
    store = _store(request, store_id)
    session = get_cash_session_detail(
        business=request.user.business, store=store, cash_session_id=session_id
    )
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
        return _run(
            request,
            lambda: method(common, data),
            f"/cash-register/stores/{store.pk}/sessions/{session.pk}/",
        )
    return render(request, "cash_register/form.html", {"form": form})


@login_required
def cash_in(request, store_id, session_id):
    return _session_action(
        request,
        store_id,
        session_id,
        CashInForm,
        lambda common, data: CashRegisterService().register_cash_in(**common, **data),
    )


@login_required
def cash_out(request, store_id, session_id):
    return _session_action(
        request,
        store_id,
        session_id,
        CashOutForm,
        lambda common, data: CashRegisterService().register_cash_out(**common, **data),
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
    )


@login_required
def review(request, store_id, session_id):
    return _session_action(
        request,
        store_id,
        session_id,
        CashCountReviewForm,
        lambda common, data: CashRegisterService().review_cash_count(**common, **data),
    )


@login_required
def close(request, store_id, session_id):
    return _session_action(
        request,
        store_id,
        session_id,
        CashSessionCloseForm,
        lambda common, data: CashRegisterService().close_cash_session(
            **common,
            counted_cash_amount=data["counted_amount"],
            pin=data["pin"],
            notes=data["notes"],
        ),
    )


@login_required
def history(request, store_id):
    store = _store(request, store_id)
    return render(
        request,
        "cash_register/history.html",
        {
            "store": store,
            "sessions": get_closed_cash_sessions(
                business=request.user.business, store=store
            ),
        },
    )
