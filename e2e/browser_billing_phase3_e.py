"""Block E fiscal print/reprint probes with synthetic PostgreSQL fixtures."""

import os
import re
import subprocess
from pathlib import Path
from unittest.mock import patch

from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.db import connections
from playwright.sync_api import expect, sync_playwright

from e2e import browser_checkout_authorized as authorized
from e2e.browser_optimistic_cart import JoinedLiveServerThread
from tests.performance import phase3_billing_audit as audit


class BillingPrintPhase3ETests(StaticLiveServerTestCase):
    server_thread_class = JoinedLiveServerThread
    page = authorized.BrowserAuthorizedCheckoutTests.page

    @classmethod
    def setUpClass(cls):
        guard = patch.dict(os.environ, {"DJANGO_ALLOW_ASYNC_UNSAFE": "true"})
        guard.start()
        cls.addClassCleanup(guard.stop)
        super().setUpClass()

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

    def test_f1_f2_reprint_preserves_snapshots_and_renders_pdf(self):
        root = Path(os.getenv("TPV_BILLING_E_ARTIFACTS", "/tmp/tpv-phase3-e-print"))
        root.mkdir(parents=True, exist_ok=True)
        for invoice, size in ((False, 20), (True, 70)):
            d, sale = audit.fixture("browser-print-" + str(invoice), size, invoice)
            with sync_playwright() as p:
                browser = p.chromium.launch(
                    executable_path=os.getenv("TPV_CHROMIUM") or None, headless=True
                )
                page, context = self.page(browser, d, sale, 1440)
                errors = []
                context.on(
                    "page",
                    lambda opened: opened.on(
                        "pageerror", lambda error: errors.append(str(error))
                    ),
                )
                try:
                    page.locator('[name="method"][data-method-code="card"]').check()
                    page.locator(".checkout-confirm").click()
                    expect(page.locator(".checkout-success")).to_be_visible()
                    document = audit.BillingDocument.objects.get(sale=sale)
                    original = audit.digest(audit.document_rows(document))
                    before = audit.snapshot(d, [sale])
                    product = d.products[0]
                    product.name = "Current product must not replace history"
                    product.base_price = "99.99"
                    product.tax = d.taxes[1]
                    product.save()
                    d.taxes[0].rate = "19.00"
                    d.taxes[0].save(update_fields=["rate"])
                    customer = d.customers[0]
                    customer.name = customer.legal_name = (
                        "Current customer must not replace history"
                    )
                    customer.save()
                    profile = d.business.profile
                    profile.legal_name = "Current issuer must not replace history"
                    profile.save()
                    pdf_info = None
                    for repetition in range(2):
                        with page.expect_popup() as info:
                            page.get_by_role(
                                "link", name="IMPRIMIR (abre una nueva pestaña)"
                            ).click()
                        popup = info.value
                        popup.wait_for_function("window.printCalls === 1")
                        expect(popup.locator("body")).to_contain_text(
                            document.issuer_legal_name
                        )
                        expect(popup.locator("body")).not_to_contain_text(
                            "must not replace history"
                        )
                        expect(
                            popup.locator(
                                ".document-print-product"
                                if not invoice
                                else ".document-print-lines tbody tr"
                            )
                        ).to_have_count(size)
                        popup.get_by_role("button", name="IMPRIMIR", exact=True).click()
                        self.assertEqual(popup.evaluate("window.printCalls"), 2)
                        if repetition == 0:
                            popup.emulate_media(media="print")
                            expect(
                                popup.locator(".document-print-controls")
                            ).to_be_hidden()
                            path = root / f"{document.document_type}.pdf"
                            kwargs = (
                                {"prefer_css_page_size": True}
                                if invoice
                                else {
                                    "width": "80mm",
                                    "height": "500mm",
                                    "prefer_css_page_size": False,
                                }
                            )
                            popup.pdf(path=str(path), print_background=True, **kwargs)
                            metadata = subprocess.check_output(
                                ["pdfinfo", str(path)], text=True
                            )
                            pages = int(
                                re.search(r"^Pages:\s+(\d+)", metadata, re.M).group(1)
                            )
                            width = float(
                                re.search(
                                    r"^Page size:\s+([\d.]+)", metadata, re.M
                                ).group(1)
                            )
                            self.assertAlmostEqual(
                                width, 595.28 if invoice else 226.77, delta=1
                            )
                            if invoice:
                                self.assertGreater(pages, 1)
                            text = subprocess.check_output(
                                ["pdftotext", "-layout", str(path), "-"], text=True
                            )
                            for line in document.lines.all():
                                self.assertIn(line.product_name, text)
                            pdf_info = {
                                "pages": pages,
                                "width_pt": width,
                                "all_line_names_found": True,
                                "print_controls_hidden": True,
                                "physical_printer": False,
                            }
                            popup.emulate_media(media="screen")
                            popup.reload()
                            popup.wait_for_function("window.printCalls === 1")
                        popup.close()
                    self.assertEqual(
                        audit.digest(audit.document_rows(document)), original
                    )
                    self.assertEqual(audit.snapshot(d, [sale]), before)
                    self.assertEqual(errors, [])
                    audit.record(
                        "E-browser-print-" + document.document_type,
                        {
                            "pdf": pdf_info,
                            "reprints": True,
                            "stub_print_returns_without_paper": True,
                            "fiscal_rows_and_economic_state_unchanged": True,
                            **before,
                        },
                    )
                finally:
                    context.close()
                    browser.close()
                    connections.close_all()

    def test_chromium_blocks_print_popup_without_user_activation(self):
        d, sale = audit.fixture("popup-block")
        with sync_playwright() as p:
            browser = p.chromium.launch(
                executable_path=os.getenv("TPV_CHROMIUM") or None,
                headless=True,
                ignore_default_args=["--disable-popup-blocking"],
            )
            page, context = self.page(browser, d, sale, 1440)
            try:
                page.locator('[name="method"][data-method-code="card"]').check()
                page.locator(".checkout-confirm").click()
                expect(page.locator(".checkout-success")).to_be_visible()
                before = audit.snapshot(d, [sale])
                reads = []
                context.on(
                    "request",
                    lambda request: (
                        reads.append(request.method)
                        if "/print/" in request.url
                        else None
                    ),
                )
                print_url = page.get_by_role(
                    "link", name="IMPRIMIR (abre una nueva pestaña)"
                ).get_attribute("href")
                # A user-activated anchor is ordinarily allowed. Probe a genuine
                # browser-denied automatic popup after transient activation ends.
                page.evaluate(
                    """url => {
                    window.billingPopupOutcome = 'waiting';
                    setTimeout(() => {window.billingPopupOutcome = window.open(url, '_blank') ? 'opened' : 'blocked';}, 5500);
                }""",
                    print_url,
                )
                page.wait_for_function("window.billingPopupOutcome !== 'waiting'")
                self.assertEqual(page.evaluate("window.billingPopupOutcome"), "blocked")
                self.assertEqual(len(context.pages), 1)
                self.assertEqual(reads, [])
                expect(page.locator(".checkout-success")).to_be_visible()
                self.assertEqual(audit.snapshot(d, [sale]), before)
                audit.record(
                    "E-browser-popup-blocked",
                    {
                        "browser_policy": "default popup blocker; no transient user activation; Playwright disable-popup-blocking argument removed",
                        "print_requests": reads,
                        "economic_state_unchanged": True,
                        **before,
                    },
                )
            finally:
                context.close()
                browser.close()
                connections.close_all()

    def test_p01_fiscal_error_visible_repair_inactive_method_and_print(self):
        from apps.business_config.models import BusinessProfile

        d, sale = audit.fixture("p01-visible-fiscal-error", 1, True)
        with sync_playwright() as p:
            browser = p.chromium.launch(
                executable_path=os.getenv("TPV_CHROMIUM") or None, headless=True
            )
            page, context = self.page(browser, d, sale, 1440)
            try:
                key = page.locator('[name="billing_idempotency_key"]').input_value()
                BusinessProfile.objects.filter(business=d.business).update(
                    legal_name=""
                )
                page.locator('[name="method"][data-method-code="card"]').check()
                page.locator(".checkout-confirm").click()
                expect(page.locator(".recovery-note")).to_contain_text(
                    "El cobro se ha registrado correctamente"
                )
                expect(
                    page.locator("[data-checkout-error-summary]").first
                ).to_contain_text("perfil fiscal")
                before = audit.snapshot(d, [sale])
                self.assertEqual(before["sales"][0]["payments"], 1)
                self.assertEqual(before["sales"][0]["documents"], 0)
                d.methods[1].is_active = False
                d.methods[1].save(update_fields=["is_active"])
                BusinessProfile.objects.filter(business=d.business).update(
                    legal_name="Repaired synthetic issuer"
                )
                # Read again after operational repair, retaining the Billing UUID.
                page.locator("[data-checkout-close]").click()
                page.locator("[data-checkout-open]").click()
                expect(page.locator('[name="billing_idempotency_key"]')).to_have_value(
                    key
                )
                page.get_by_role("button", name="REINTENTAR EMISIÓN").click()
                expect(page.locator(".checkout-success")).to_be_visible()
                with page.expect_popup() as popup_info:
                    page.get_by_role(
                        "link", name="IMPRIMIR (abre una nueva pestaña)"
                    ).click()
                popup = popup_info.value
                popup.wait_for_function("window.printCalls === 1")
                expect(popup.locator("body")).to_contain_text(
                    "Repaired synthetic issuer"
                )
                popup.close()
                after = audit.snapshot(d, [sale])
                self.assertEqual(after["sales"][0]["payments"], 1)
                self.assertEqual(after["sales"][0]["documents"], 1)
                self.assertEqual(after["sales"][0]["stock_movements"], 1)
                audit.record(
                    "E-browser-P01-fiscal-repair",
                    {"before_repair": before, "after_repair_and_print": after},
                )
            finally:
                context.close()
                browser.close()
                connections.close_all()

    def test_autoprint_waits_for_local_logo_and_survives_image_failure(self):
        for outcome in ("loaded", "failed"):
            d, sale = audit.fixture("logo-" + outcome)
            with sync_playwright() as p:
                browser = p.chromium.launch(
                    executable_path=os.getenv("TPV_CHROMIUM") or None, headless=True
                )
                page, context = self.page(browser, d, sale, 1440)
                held = []
                try:
                    page.locator('[name="method"][data-method-code="card"]').check()
                    page.locator(".checkout-confirm").click()
                    expect(page.locator(".checkout-success")).to_be_visible()
                    before = audit.snapshot(d, [sale])
                    profile = d.business.profile
                    profile.logo_url = self.live_server_url + "/phase3-e/logo.svg"
                    profile.save()
                    context.route(
                        "**/phase3-e/logo.svg", lambda route: held.append(route)
                    )
                    with page.expect_popup() as info:
                        page.get_by_role(
                            "link", name="IMPRIMIR (abre una nueva pestaña)"
                        ).click()
                    popup = info.value
                    popup.wait_for_load_state("domcontentloaded")
                    expect(popup.locator(".document-print-logo")).to_have_count(1)
                    self.assertEqual(len(held), 1)
                    self.assertEqual(popup.evaluate("window.printCalls"), 0)
                    self.assertFalse(
                        popup.locator(".document-print-logo").evaluate(
                            "image => image.complete"
                        )
                    )
                    if outcome == "loaded":
                        held[0].fulfill(
                            content_type="image/svg+xml",
                            body='<svg xmlns="http://www.w3.org/2000/svg" width="80" height="40"><rect width="80" height="40" fill="navy"/></svg>',
                        )
                    else:
                        held[0].abort("failed")
                    popup.wait_for_function("window.printCalls === 1")
                    width = popup.locator(".document-print-logo").evaluate(
                        "image => image.naturalWidth"
                    )
                    self.assertEqual(width > 0, outcome == "loaded")
                    popup.close()
                    self.assertEqual(audit.snapshot(d, [sale]), before)
                    audit.record(
                        "E-browser-logo-" + outcome,
                        {
                            "autoprint_before_image_completed": 0,
                            "autoprint_after_image_finished": 1,
                            "image_natural_width": width,
                            "economic_and_fiscal_state_unchanged": True,
                            **before,
                        },
                    )
                finally:
                    context.close()
                    browser.close()
                    connections.close_all()
