"""Real Chromium recovery without changing economic services or identifiers."""

import os

from decimal import Decimal
from threading import Event
from unittest.mock import patch

from django.conf import settings
from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.core.exceptions import ValidationError
from django.test import Client
from django.urls import reverse
from playwright.sync_api import expect, sync_playwright

from apps.sales import checkout, views
from apps.sales.tests_postgres_recovery import save_case, state
from e2e.browser_optimistic_cart import JoinedLiveServerThread
from tests.performance.dataset import Dataset


class BrowserCheckoutRecoveryTests(StaticLiveServerTestCase):
    server_thread_class = JoinedLiveServerThread

    def setUp(self):
        cls = type(self)
        if not cls.server_thread.is_alive():
            cls.server_thread = cls._create_server_thread(
                cls.server_thread.connections_override
            )
            cls.server_thread.daemon = True
            cls.server_thread.start()
            cls.server_thread.is_ready.wait()
            if cls.server_thread.error:
                raise cls.server_thread.error

    def _post_teardown(self):
        self.server_thread.terminate()
        super()._post_teardown()

    def test_lost_commit_timeout_render_and_identity_recovery(self):
        dataset = Dataset(1, label="browser-recovery-c")
        dataset.settings.allow_split_payments = True
        dataset.settings.save()
        labels = [
            "after_T1",
            "after_T2",
            "after_T3",
            "render_500",
            "timeout",
            "abort",
            "split_partial",
            "reload",
            "reopen",
        ]
        fixtures = {
            (width, label): dataset.sale(1)[0]
            for width in (1440, 820, 390)
            for label in labels
        }
        client = Client()
        client.force_login(dataset.user)
        for width in (1440, 820, 390):
            for label in labels:
                sale = fixtures[width, label]
                first, release, finished = Event(), Event(), Event()
                if label in ("after_T1", "reload"):
                    module, attribute = checkout, "register_sale_payment"
                elif label == "render_500":
                    module, attribute = views.SaleCheckoutView, "_render"
                else:
                    module, attribute = checkout, "issue_sale_document"
                original = getattr(module, attribute)
                card = next(m.pk for m in dataset.methods if m.code == "card")
                if label == "split_partial":
                    module, attribute = checkout, "register_sale_payment"
                    original = checkout.register_sale_payment

                def controlled(*args, **kwargs):
                    post_render = (
                        label != "render_500" or args[0].request.method == "POST"
                    )
                    should_fail = (
                        not first.is_set()
                        and post_render
                        and (label != "split_partial" or kwargs["method_id"] == card)
                    )
                    if should_fail:
                        first.set()
                        if label in ("timeout", "abort"):
                            try:
                                if not release.wait(6):
                                    raise TimeoutError("release timed out")
                                return original(*args, **kwargs)
                            finally:
                                finished.set()
                        if label == "render_500":
                            raise RuntimeError("Synthetic render failure after commits")
                        if label != "after_T3":
                            raise ValidationError("Synthetic partial boundary")
                    return original(*args, **kwargs)

                if label == "after_T3":
                    controlled = original
                with (
                    patch.object(module, attribute, controlled),
                    sync_playwright() as p,
                ):
                    browser = p.chromium.launch(
                        executable_path=os.getenv("TPV_CHROMIUM") or None, headless=True
                    )
                    context = browser.new_context(
                        viewport={"width": width, "height": 900}, has_touch=width < 1440
                    )
                    context.add_cookies(
                        [
                            {
                                "name": settings.SESSION_COOKIE_NAME,
                                "value": client.cookies[
                                    settings.SESSION_COOKIE_NAME
                                ].value,
                                "url": self.live_server_url,
                            }
                        ]
                    )
                    context.route(
                        "**/*",
                        lambda route: (
                            route.continue_()
                            if route.request.url.startswith(self.live_server_url + "/")
                            else route.abort()
                        ),
                    )
                    page = context.new_page()
                    page.goto(
                        self.live_server_url
                        + reverse("sales:sale_detail", args=[sale.store_id, sale.pk]),
                        wait_until="load",
                    )
                    if (
                        width < 1200
                        and not page.locator("[data-checkout-open]").is_visible()
                    ):
                        page.locator('[data-nx-drawer-trigger="sale-cart"]').click()
                    page.locator("[data-checkout-open]").click()
                    expect(page.locator("[data-checkout-form]")).to_be_visible()
                    if label == "split_partial":
                        page.locator('[name="mode"][value="split"]').check()
                        half = (sale.total_amount / 2).quantize(Decimal(".01"))
                        for index, code in enumerate(("cash", "card")):
                            page.locator(
                                f'[name="payments-{index}-method"]'
                            ).select_option(
                                str(
                                    next(
                                        m.pk for m in dataset.methods if m.code == code
                                    )
                                )
                            )
                            page.locator(f'[name="payments-{index}-amount"]').fill(
                                str(half if index == 0 else sale.total_amount - half)
                            )
                    else:
                        page.locator('[name="method"][data-method-code="card"]').check()
                    keys = page.locator("[data-checkout-form]").evaluate(
                        '(form) => Object.fromEntries([...new FormData(form)].filter(([name]) => name.endsWith("idempotency_key")))'
                    )
                    posts = []
                    page.on(
                        "request",
                        lambda request: (
                            posts.append(True)
                            if request.method == "POST" and "/checkout/" in request.url
                            else None
                        ),
                    )
                    if label not in ("timeout", "abort", "render_500"):

                        def lose(route):
                            route.fetch()
                            route.abort("failed")

                        page.route("**/checkout/", lose)
                    if label == "abort":
                        page.evaluate(
                            "document.addEventListener('htmx:beforeSend', e => { if (e.detail.elt.matches('[data-checkout-form]') && !window.didAbort) { window.didAbort = true; setTimeout(() => e.detail.xhr.abort(), 250); } })"
                        )
                    if label == "timeout":
                        page.evaluate(
                            "document.addEventListener('htmx:beforeRequest', e => { if (e.detail.elt.matches('[data-checkout-form]') && !window.didTimeout) { window.didTimeout = true; e.detail.xhr.timeout = 250; } })"
                        )
                    try:
                        page.locator(".checkout-confirm").click()
                        expect(page.locator("#nx-feedback")).to_contain_text(
                            "No podemos confirmar el resultado"
                        )
                        expect(
                            page.locator('[data-checkout-form] [type="submit"]')
                        ).to_be_disabled()
                        self.assertEqual(len(posts), 1)
                        if label not in ("timeout", "abort", "render_500"):
                            page.unroute("**/checkout/", lose)
                        # Even a programmatic duplicate submit is blocked until GET.
                        page.locator("[data-checkout-form]").evaluate(
                            "(form) => form.requestSubmit()"
                        )
                        self.assertEqual(len(posts), 1)
                        if label == "reload":
                            page.goto(
                                self.live_server_url
                                + reverse(
                                    "sales:sale_checkout", args=[sale.store_id, sale.pk]
                                ),
                                wait_until="load",
                            )
                            expect(
                                page.locator('[data-checkout-form] [type="submit"]')
                            ).to_be_disabled()
                            for name, key in keys.items():
                                expect(page.locator(f'[name="{name}"]')).to_have_value(
                                    key
                                )
                        elif label == "reopen":
                            page.locator("[data-checkout-close]").click()
                            if (
                                width < 1200
                                and not page.locator(
                                    "[data-checkout-open]"
                                ).is_visible()
                            ):
                                page.locator(
                                    '[data-nx-drawer-trigger="sale-cart"]'
                                ).click()
                            page.locator("[data-checkout-open]").click()
                            expect(page.locator("[data-checkout-form]")).to_be_visible()
                        if label != "reopen":
                            page.locator("[data-nx-checkout-status]").click()
                        if label in ("after_T3", "render_500"):
                            expect(page.locator(".checkout-success")).to_be_visible()
                            self.assertEqual(len(posts), 1)
                        else:
                            expect(
                                page.locator('[data-checkout-form] [type="submit"]')
                            ).to_be_enabled()
                            for name, key in keys.items():
                                expect(
                                    page.locator(
                                        f'[data-checkout-form] [name="{name}"]'
                                    )
                                ).to_have_value(key)
                            self.assertEqual(len(posts), 1)
                            page.locator('[data-checkout-form] [type="submit"]').click()
                            expect(page.locator(".checkout-success")).to_be_visible(
                                timeout=12000
                            )
                            self.assertEqual(len(posts), 2)
                        expect(
                            page.locator(
                                ".checkout-success [data-nx-sale-start] button"
                            )
                        ).to_be_enabled()
                        self.assertFalse(
                            page.locator("#nx-feedback").is_visible(),
                            f"{label}-{width}",
                        )
                        self.assertLessEqual(
                            page.locator("body").evaluate("(body) => body.scrollWidth"),
                            width + 2,
                        )
                    finally:
                        release.set()
                        if label in ("timeout", "abort"):
                            self.assertTrue(finished.wait(6))
                        browser.close()
                final = state(dataset, [sale])
                save_case(
                    f"browser-{label}-{width}",
                    {"posts": len(posts), "identity_preserved": True, **final},
                )
                self.assertEqual(
                    final["sales"][0]["payments"], 2 if label == "split_partial" else 1
                )
                self.assertEqual(final["sales"][0]["documents"], 1)
                self.assertEqual(final["sales"][0]["stock_movements"], 1)
                self.assertEqual(Decimal(final["sales"][0]["pending"]), 0)

    def test_double_submit_during_processing(self):
        d = Dataset(1, label="double-browser-c")
        sale, _ = d.sale(1)
        client = Client()
        client.force_login(d.user)
        entered, release = Event(), Event()
        original = checkout.issue_sale_document

        def hold(**kwargs):
            entered.set()
            if not release.wait(6):
                raise TimeoutError("release")
            return original(**kwargs)

        with (
            patch.object(checkout, "issue_sale_document", hold),
            sync_playwright() as p,
        ):
            browser = p.chromium.launch(
                executable_path=os.getenv("TPV_CHROMIUM") or None, headless=True
            )
            context = browser.new_context()
            context.add_cookies(
                [
                    {
                        "name": settings.SESSION_COOKIE_NAME,
                        "value": client.cookies[settings.SESSION_COOKIE_NAME].value,
                        "url": self.live_server_url,
                    }
                ]
            )
            page = context.new_page()
            page.goto(
                self.live_server_url
                + reverse("sales:sale_detail", args=[sale.store_id, sale.pk])
            )
            page.locator("[data-checkout-open]").click()
            page.locator('[name="method"][data-method-code="card"]').check()
            posts = []
            page.on(
                "request",
                lambda request: (
                    posts.append(True)
                    if request.method == "POST" and "/checkout/" in request.url
                    else None
                ),
            )
            try:
                page.locator(".checkout-confirm").click()
                self.assertTrue(entered.wait(5))
                page.locator("[data-checkout-form]").evaluate(
                    "(form) => { form.requestSubmit(); form.requestSubmit(); }"
                )
                self.assertEqual(len(posts), 1)
                expect(
                    page.locator("[data-checkout-form] button[type=submit]")
                ).to_be_disabled()
                release.set()
                expect(page.locator(".checkout-success")).to_be_visible()
            finally:
                release.set()
                browser.close()
        final = state(d, [sale])
        save_case("browser-double-processing", {"posts": len(posts), **final})
        self.assertEqual(final["sales"][0]["payments"], 1)
        self.assertEqual(final["sales"][0]["documents"], 1)

    def test_dismissed_reload_notice_and_damaged_journal_fail_closed(self):
        d = Dataset(1, label="journal-browser-c")
        sale, _ = d.sale(1)
        client = Client()
        client.force_login(d.user)
        with sync_playwright() as p:
            browser = p.chromium.launch(
                executable_path=os.getenv("TPV_CHROMIUM") or None, headless=True
            )
            context = browser.new_context(
                viewport={"width": 390, "height": 900}, has_touch=True
            )
            context.add_cookies(
                [
                    {
                        "name": settings.SESSION_COOKIE_NAME,
                        "value": client.cookies[settings.SESSION_COOKIE_NAME].value,
                        "url": self.live_server_url,
                    }
                ]
            )
            page = context.new_page()
            posts = []
            page.on(
                "request", lambda r: posts.append(True) if r.method == "POST" else None
            )
            try:
                page.goto(
                    self.live_server_url
                    + reverse("sales:sale_checkout", args=[sale.store_id, sale.pk])
                )
                key = page.locator("[data-checkout]").get_attribute(
                    "data-checkout-recovery-key"
                )
                page.evaluate(
                    """key => {
                    const form = document.querySelector('[data-checkout-form]');
                    const record = {key, action: new URL(form.action).pathname,
                        fields: [...new FormData(form)].filter(([name]) => name !== 'csrfmiddlewaretoken')};
                    sessionStorage.setItem('netxodo:checkout-recovery:v1:' + key, JSON.stringify(record));
                }""",
                    key,
                )
                page.reload()
                expect(
                    page.locator("[data-checkout-form] [type=submit]")
                ).to_be_disabled()
                page.locator("[data-nx-feedback-close]").click()
                page.locator("[data-nx-checkout-read-inline]").click()
                expect(
                    page.locator("[data-checkout-form] [type=submit]")
                ).to_be_enabled()
                page.evaluate(
                    "key => sessionStorage.setItem('netxodo:checkout-recovery:v1:' + key, '{bad-json')",
                    key,
                )
                page.reload()
                page.locator("[data-nx-feedback-close]").click()
                page.locator("[data-nx-checkout-read-inline]").click()
                expect(page.locator("[data-checkout-form]")).to_be_hidden()
                expect(page.locator("[data-checkout]")).to_contain_text(
                    "No se puede recuperar la operación guardada"
                )
                self.assertEqual(posts, [])
                # A storage-denied browser still retains the current intent in memory.
                page.evaluate("sessionStorage.clear()")
                page.reload()
                page.evaluate("""() => {
                    Storage.prototype.getItem = () => { throw new Error('blocked'); };
                    Storage.prototype.setItem = () => { throw new Error('blocked'); };
                }""")
                page.route(
                    "**/checkout/",
                    lambda route: (
                        route.abort("failed")
                        if route.request.method == "POST"
                        else route.continue_()
                    ),
                )
                page.locator(".checkout-confirm").click()
                expect(page.locator("#nx-feedback")).to_contain_text(
                    "No podemos confirmar el resultado"
                )
                page.locator("[data-nx-feedback-close]").click()
                page.locator("[data-nx-checkout-read-inline]").click()
                expect(
                    page.locator("[data-checkout-form] [type=submit]")
                ).to_be_enabled()
                self.assertEqual(len(posts), 1)
            finally:
                browser.close()
        final = state(d, [sale])
        self.assertEqual(final["sales"][0]["payments"], 0)
        self.assertEqual(final["sales"][0]["stock_movements"], 0)
        save_case(
            "browser-journal-fail-closed", {"posts_aborted_before_server": 1, **final}
        )
