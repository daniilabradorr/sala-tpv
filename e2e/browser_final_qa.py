"""Cross-cutting browser checks for the final pre-VeriFactu frontend audit."""

from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.test import override_settings
from playwright.sync_api import expect, sync_playwright

from apps.onboarding.services import OnboardingService


@override_settings(
    STORAGES={
        "staticfiles": {
            "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"
        }
    }
)
class BrowserFinalQATests(StaticLiveServerTestCase):
    email = "final-qa@example.com"
    password = "Final-QA-Password-123!"

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        OnboardingService.create_business(
            legal_name="Final QA SL",
            trade_name="Final QA",
            tax_identifier="B10000024",
            phone="923000024",
            email="final-qa-business@example.com",
            address_line_1="Calle QA 24",
            postal_code="37001",
            city="Salamanca",
            province="Salamanca",
            country_code="ES",
            store_name="Tienda QA",
            owner_first_name="Final",
            owner_last_name="QA",
            owner_email=cls.email,
            owner_phone="600000024",
            owner_password=cls.password,
            owner_pin="2424",
        )

    def test_authorized_navigation_dom_references_and_breakpoints(self):
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1280, "height": 900})
            javascript_errors = []
            critical_asset_errors = []
            page.on("pageerror", lambda error: javascript_errors.append(str(error)))
            page.on(
                "response",
                lambda response: (
                    critical_asset_errors.append(f"{response.status} {response.url}")
                    if response.status >= 400
                    and response.request.resource_type in {"script", "stylesheet"}
                    and response.url.startswith(self.live_server_url)
                    else None
                ),
            )
            try:
                page.goto(f"{self.live_server_url}/users/login/")
                page.get_by_label("Correo electrónico").fill(self.email)
                page.get_by_label("Contraseña").fill(self.password)
                page.get_by_role("button", name="Iniciar sesión").click()
                expect(page.locator("#dashboard-title")).to_contain_text("Resumen de")

                audit = page.evaluate(
                    """async () => {
                        const ids = [...document.querySelectorAll('[id]')].map(el => el.id);
                        const brokenRefs = [];
                        for (const el of document.querySelectorAll(
                            '[aria-labelledby], [aria-describedby], [aria-controls]'
                        )) {
                            for (const attr of ['aria-labelledby', 'aria-describedby', 'aria-controls']) {
                                for (const token of (el.getAttribute(attr) || '').split(/\\s+/).filter(Boolean)) {
                                    if (!document.getElementById(token)) brokenRefs.push(`${attr}:${token}`);
                                }
                            }
                        }
                        const sidebar = [...document.querySelectorAll('.sidebar-nav a')]
                            .map(link => link.href);
                        const palette = [...document.querySelectorAll('.command-results section')]
                            .filter(section => section.querySelector('h3')?.textContent.trim() !== 'Acciones rápidas')
                            .flatMap(section => [...section.querySelectorAll('a')].map(link => link.href));
                        const statuses = await Promise.all(sidebar.map(async href =>
                            (await fetch(href, {credentials: 'same-origin'})).status
                        ));
                        return {
                            duplicateIds: ids.filter((id, index) => ids.indexOf(id) !== index),
                            brokenRefs,
                            sidebar,
                            palette,
                            statuses,
                        };
                    }"""
                )
                self.assertEqual(audit["duplicateIds"], [])
                self.assertEqual(audit["brokenRefs"], [])
                self.assertEqual(set(audit["sidebar"]), set(audit["palette"]))
                self.assertTrue(all(status < 400 for status in audit["statuses"]))

                for width, height in (
                    (375, 812),
                    (767, 900),
                    (768, 900),
                    (1024, 768),
                    (1280, 900),
                    (1440, 900),
                ):
                    page.set_viewport_size({"width": width, "height": height})
                    self.assertLessEqual(
                        page.evaluate("document.documentElement.scrollWidth"), width
                    )
                    overflow = page.evaluate(
                        """() => ({
                            html: getComputedStyle(document.documentElement).overflowX,
                            body: getComputedStyle(document.body).overflowX,
                        })"""
                    )
                    self.assertNotIn(overflow["html"], {"hidden", "clip"})
                    self.assertNotIn(overflow["body"], {"hidden", "clip"})
                self.assertEqual(javascript_errors, [])
                self.assertEqual(critical_asset_errors, [])
            finally:
                browser.close()
