"""Real Chromium coverage for the FE-07 onboarding wizard."""

import json
from pathlib import Path

from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.test import override_settings
from playwright.sync_api import expect, sync_playwright


@override_settings(
    STORAGES={
        "staticfiles": {
            "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"
        }
    },
)
class BrowserOnboardingTests(StaticLiveServerTestCase):
    @staticmethod
    def _capture_failure(page, *, viewport, errors, index):
        artifact_dir = Path("artifacts/e2e")
        artifact_dir.mkdir(parents=True, exist_ok=True)
        prefix = f"onboarding-{viewport['width']}x{viewport['height']}-{index}"
        page.screenshot(path=str(artifact_dir / f"{prefix}.png"), full_page=True)
        (artifact_dir / f"{prefix}.html").write_text(page.content(), encoding="utf-8")
        (artifact_dir / f"{prefix}.json").write_text(
            json.dumps(
                {"url": page.url, "title": page.title(), "page_errors": errors},
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

    def test_wizard_desktop_and_mobile(self):
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            try:
                for index, viewport in enumerate(
                    ({"width": 1440, "height": 900}, {"width": 375, "height": 812})
                ):
                    with self.subTest(viewport=viewport):
                        context = browser.new_context(viewport=viewport)
                        page = context.new_page()
                        errors = []
                        page.on("pageerror", lambda error: errors.append(str(error)))
                        try:
                            page.goto(f"{self.live_server_url}/onboarding/")
                            expect(page.locator("[data-app-shell]")).to_have_count(0)
                            expect(
                                page.get_by_text("Paso 1 de 4").first
                            ).to_be_visible()

                            page.get_by_label("Razón social").fill(
                                f"Taller E2E {index}"
                            )
                            page.get_by_label("NIF/CIF").fill(f"B1234567{index}")
                            page.get_by_label("Nombre comercial").fill(
                                f"Taller {index}"
                            )
                            page.locator("#id_phone").fill("910000000")
                            page.locator("#id_email").fill(
                                f"negocio{index}@example.com"
                            )
                            page.locator("#id_address_line_1").fill("Calle Mayor 1")
                            page.locator("#id_postal_code").fill("28001")
                            page.locator("#id_city").fill("Madrid")
                            page.locator("#id_province").fill("Madrid")
                            page.get_by_role("button", name="Continuar").click()

                            page.get_by_label("Nombre de la tienda").fill("Centro")
                            custom = page.locator("[data-store-address]")
                            store_email = page.locator("#id_store_email")
                            store_postal_code = page.locator("#id_store_postal_code")
                            expect(custom).to_be_hidden()
                            expect(store_email).to_be_disabled()
                            expect(store_postal_code).to_be_disabled()
                            page.get_by_label(
                                "Usar la misma dirección del negocio"
                            ).uncheck()
                            expect(custom).to_be_visible()
                            expect(store_email).to_be_enabled()
                            expect(store_postal_code).to_be_enabled()
                            store_email.fill("esto-no-es-email")
                            store_postal_code.fill("BAD")
                            page.get_by_label(
                                "Usar la misma dirección del negocio"
                            ).check()
                            expect(custom).to_be_hidden()
                            expect(store_email).to_be_disabled()
                            expect(store_postal_code).to_be_disabled()
                            page.get_by_role("button", name="Continuar").click()
                            expect(page.get_by_text("Paso 3 de 4").last).to_be_visible()

                            page.locator("#id_owner_first_name").fill("Ada")
                            page.locator("#id_owner_last_name").fill("Lovelace")
                            page.locator("#id_owner_email").fill(
                                f"owner{index}@example.com"
                            )
                            password = page.locator("#id_owner_password")
                            password.fill("A-secure-password-2026!")
                            page.get_by_role("button", name="Mostrar").click()
                            expect(password).to_have_attribute("type", "text")
                            page.locator("#id_owner_password_confirmation").fill(
                                "A-secure-password-2026!"
                            )
                            page.locator("#id_owner_pin").fill("2468")
                            page.get_by_role("button", name="Continuar").click()

                            expect(
                                page.get_by_text(f"Taller E2E {index}")
                            ).to_be_visible()
                            review = page.locator("[data-step='4']")
                            expect(review).not_to_contain_text(
                                "A-secure-password-2026!"
                            )
                            expect(review).not_to_contain_text("2468")

                            # Hold this one submit in the browser so the visual
                            # provisioning state is asserted without sleeps.
                            page.evaluate(
                                """window.__holdOnboarding = event => event.preventDefault();
                                document.querySelector('[data-onboarding-form]')
                                  .addEventListener('submit', window.__holdOnboarding);"""
                            )
                            submit = page.locator("[data-submit]")
                            expect(submit).to_have_text("Crear mi Netxodo")
                            submit.click()
                            expect(submit).to_be_disabled()
                            expect(submit).to_have_text("Procesando…")
                            expect(page.locator("[data-processing]")).to_be_visible()
                            page.evaluate(
                                """const form = document.querySelector('[data-onboarding-form]');
                                form.removeEventListener('submit', window.__holdOnboarding);
                                form.requestSubmit();"""
                            )
                            expect(
                                page.get_by_role(
                                    "heading", name="Tu Netxodo está listo"
                                )
                            ).to_be_visible()
                            expect(page.locator("[data-app-shell]")).to_have_count(0)
                            page.get_by_role("link", name="Entrar en Netxodo").click()
                            expect(
                                page.get_by_role("heading", name="Buenos días, Ada")
                            ).to_be_visible()
                            expect(
                                page.get_by_role("link", name="Añade tus productos")
                            ).to_be_visible()
                            expect(
                                page.get_by_role(
                                    "link", name="Configura el stock inicial"
                                )
                            ).to_be_visible()
                            expect(
                                page.get_by_role("link", name="Añade a tu equipo")
                            ).to_be_visible()
                            self.assertEqual(
                                page.evaluate("document.documentElement.scrollWidth"),
                                viewport["width"],
                            )
                            self.assertEqual(errors, [])
                        except Exception:
                            self._capture_failure(
                                page,
                                viewport=viewport,
                                errors=errors,
                                index=index,
                            )
                            raise
                        finally:
                            context.close()
            finally:
                browser.close()
