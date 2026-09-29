"""Real-browser coverage for FE-21 Stores and CashRegister administration."""

import re
from contextlib import contextmanager

from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.test import override_settings
from django.urls import reverse
from playwright.sync_api import expect, sync_playwright

from apps.cash_register.models import CashRegister, CashSession
from apps.onboarding.services import OnboardingService
from apps.stores.models import Store
from apps.users.models import CustomUser, RoleChoices, UserStoreAccess


@override_settings(
    STORAGES={
        "staticfiles": {
            "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"
        }
    }
)
class BrowserStoresTests(StaticLiveServerTestCase):
    password = "E2E-Stores-Password-123!"

    def setUp(self):
        result = OnboardingService.create_business(
            legal_name="Stores E2E SL",
            trade_name="Stores E2E",
            tax_identifier="B10000021",
            phone="923000021",
            email="stores-business@example.com",
            address_line_1="Calle Tiendas 21",
            postal_code="37021",
            city="Salamanca",
            province="Salamanca",
            country_code="ES",
            store_name="Centro",
            owner_first_name="Owner",
            owner_last_name="Stores",
            owner_email="stores.e2e@example.com",
            owner_phone="600000021",
            owner_password=self.password,
            owner_pin="1234",
        )
        self.business, self.owner, self.default = (
            result.business,
            result.owner,
            result.store,
        )
        self.default.city = "Salamanca"
        self.default.save(update_fields=["city", "updated_at"])
        self.second = Store.objects.create(
            business=result.business,
            name="Gran Vía",
            code="GRAN-VIA",
            city="Madrid",
        )
        self.inactive = Store.objects.create(
            business=result.business,
            name="Archivo",
            code="ARCHIVO",
            city="Ávila",
            is_active=False,
        )
        self.register = CashRegister.objects.create(
            business=result.business,
            store=self.second,
            name="Caja principal",
            code="CAJA-01",
        )
        self.manager = CustomUser.objects.create_user(
            business=self.business,
            email="stores-manager.e2e@example.com",
            password=self.password,
            role=RoleChoices.MANAGER,
            first_name="Manager",
        )
        self.cashier = CustomUser.objects.create_user(
            business=self.business,
            email="stores-cashier.e2e@example.com",
            password=self.password,
            role=RoleChoices.CASHIER,
            first_name="Cashier",
        )
        UserStoreAccess.objects.create(
            business=self.business,
            user=self.manager,
            store=self.default,
            can_sell=True,
            can_open_cash=True,
            can_close_cash=True,
        )
        UserStoreAccess.objects.create(
            business=self.business,
            user=self.cashier,
            store=self.default,
            can_sell=True,
        )

    def login(self, page, user):
        page.goto(f"{self.live_server_url}{reverse('users:login')}")
        page.get_by_label("Correo electrónico").fill(user.email)
        page.get_by_label("Contraseña").fill(self.password)
        page.get_by_role("button", name="Iniciar sesión").click()
        page.wait_for_url(f"{self.live_server_url}/")

    def assert_no_overflow(self, page):
        self.assertTrue(
            page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        )

    @contextmanager
    def open_browser(self, playwright, **kwargs):
        """Always close Chromium, including when an assertion aborts a test."""
        browser = playwright.chromium.launch(headless=True, **kwargs)
        try:
            yield browser
        finally:
            browser.close()

    def test_owner_list_filters_navigation_menu_and_responsive_surfaces(self):
        with sync_playwright() as playwright:
            with self.open_browser(playwright) as browser:
                page = browser.new_page(viewport={"width": 1280, "height": 812})
                self.login(page, self.owner)
                expect(
                    page.locator("#app-sidebar").get_by_role("link", name="Tiendas")
                ).to_be_visible()
                page.keyboard.press("Control+k")
                page.locator("[data-command-input]").fill("tiendas")
                expect(
                    page.locator("[data-command-dialog]").get_by_role(
                        "link", name="Tiendas"
                    )
                ).to_be_visible()
                page.keyboard.press("Escape")
                page.goto(f"{self.live_server_url}{reverse('stores:store_list')}")
                kpis = page.get_by_label("Resumen de tiendas")
                expect(kpis.get_by_text("Tiendas activas", exact=True)).to_be_visible()
                expect(kpis.get_by_text("Inactivas", exact=True)).to_be_visible()
                expect(kpis.get_by_text("Predeterminada", exact=True)).to_be_visible()
                expect(
                    page.locator(
                        ".stores-table "
                        f'summary[aria-label="Acciones de {self.default.name}"]'
                    )
                ).to_be_visible()
                for query, expected in (
                    ("Gran Vía", "Gran Vía"),
                    ("ARCHIVO", "Archivo"),
                    ("Salamanca", "Centro"),
                ):
                    page.get_by_placeholder("Buscar tienda...").fill(query)
                    page.get_by_role("button", name="Filtrar").click()
                    expect(
                        page.locator(".stores-table").get_by_role(
                            "link", name=expected, exact=True
                        )
                    ).to_be_visible()
                page.get_by_placeholder("Buscar tienda...").fill("")
                page.get_by_label("Estado").select_option("inactive")
                page.get_by_role("button", name="Filtrar").click()
                expect(
                    page.locator(".stores-table").get_by_role(
                        "link", name="Archivo", exact=True
                    )
                ).to_be_visible()
                expect(page).to_have_url(re.compile(r"[?&]status=inactive(?:&|$)"))
                for width in (375, 767, 768, 1280):
                    page.set_viewport_size({"width": width, "height": 812})
                    self.assert_no_overflow(page)
                page.goto(
                    f"{self.live_server_url}{reverse('stores:store_detail', args=[self.second.pk])}"
                )
                for width in (375, 767, 768, 1280):
                    page.set_viewport_size({"width": width, "height": 812})
                    expect(
                        page.get_by_role("navigation", name="Secciones de la tienda")
                    ).to_be_visible()
                    self.assert_no_overflow(page)
                page.goto(
                    f"{self.live_server_url}{reverse('cash_register:register_admin', args=[self.second.pk])}"
                )
                for width in (375, 767, 768, 1280):
                    page.set_viewport_size({"width": width, "height": 812})
                    self.assert_no_overflow(page)

    def test_owner_create_and_active_store_remains_separate_from_default(self):
        with sync_playwright() as playwright:
            with self.open_browser(playwright) as browser:
                page = browser.new_page()
                self.login(page, self.owner)
                page.goto(f"{self.live_server_url}{reverse('stores:store_create')}")
                for field in ("business", "code", "is_active", "is_default"):
                    expect(page.locator(f'[name="{field}"]')).to_have_count(0)
                page.get_by_label("Nombre").fill("Nueva tienda")
                page.get_by_label("País").fill("ES")
                page.get_by_role("button", name="Crear tienda").click()
                expect(page.get_by_role("heading", name="Nueva tienda")).to_be_visible()
                expect(page.locator(".store-hero strong")).not_to_be_empty()
                expect(page.get_by_text("● Activa", exact=True)).to_be_visible()
                page.goto(
                    f"{self.live_server_url}{reverse('stores:store_detail', args=[self.second.pk])}"
                )
                page.get_by_role("button", name="Usar esta tienda").click()
                expect(page.locator("[data-store-trigger]")).to_contain_text("Gran Vía")
                page.goto(f"{self.live_server_url}{reverse('stores:store_list')}")
                expect(page.get_by_label("Resumen de tiendas")).to_contain_text(
                    "Centro"
                )
                page.goto(
                    f"{self.live_server_url}{reverse('stores:store_detail', args=[self.second.pk])}"
                )
                store_tabs = page.get_by_role(
                    "navigation", name="Secciones de la tienda"
                )
                store_tabs.get_by_role("link", name="Configuración", exact=True).click()
                page.get_by_role("link", name="Hacer predeterminada").click()
                default_change = page.locator(".default-change")
                current_default = default_change.locator("div").filter(
                    has_text="Actual"
                )
                new_default = default_change.locator("div").filter(has_text="Nueva")
                expect(current_default.locator("dt")).to_have_text("Actual")
                expect(current_default.locator("dd")).to_have_text(self.default.name)
                expect(new_default.locator("dt")).to_have_text("Nueva")
                expect(new_default.locator("dd")).to_have_text(self.second.name)
                page.get_by_role("button", name="Hacer predeterminada").click()
                expect(page.get_by_text("★ Predeterminada", exact=True)).to_be_visible()
                expect(page.locator("[data-store-trigger]")).to_contain_text("Gran Vía")

        created = Store.objects.get(name="Nueva tienda")
        self.assertEqual(created.business, self.business)
        self.assertTrue(created.code)
        self.assertTrue(created.is_active)
        self.default.refresh_from_db()
        self.second.refresh_from_db()
        self.assertFalse(self.default.is_default)
        self.assertTrue(self.second.is_default)

    def test_manager_admin_scope_and_cashier_read_only_scope(self):
        with sync_playwright() as playwright:
            with self.open_browser(playwright) as browser:
                manager_page = browser.new_page()
                self.login(manager_page, self.manager)
                manager_page.goto(
                    f"{self.live_server_url}{reverse('stores:store_list')}"
                )
                expect(
                    manager_page.locator(".stores-table").get_by_role(
                        "link", name="Gran Vía", exact=True
                    )
                ).to_be_visible()
                manager_page.goto(
                    f"{self.live_server_url}{reverse('stores:store_detail', args=[self.second.pk])}?tab=operation"
                )
                expect(manager_page.get_by_text("Ir al TPV")).to_have_count(0)
                manager_page.goto(
                    f"{self.live_server_url}{reverse('cash_register:register_admin', args=[self.second.pk])}"
                )
                expect(
                    manager_page.get_by_role("heading", name="Cajas")
                ).to_be_visible()

                cashier_page = browser.new_page()
                self.login(cashier_page, self.cashier)
                expect(
                    cashier_page.locator("#app-sidebar").get_by_role(
                        "link", name="Tiendas"
                    )
                ).to_have_count(0)
                cashier_page.keyboard.press("Control+k")
                cashier_page.locator("[data-command-input]").fill("tiendas")
                expect(
                    cashier_page.locator("[data-command-dialog]").get_by_role(
                        "link", name="Tiendas"
                    )
                ).to_have_count(0)
                cashier_page.keyboard.press("Escape")
                cashier_page.goto(
                    f"{self.live_server_url}{reverse('stores:store_detail', args=[self.default.pk])}"
                )
                for text in (
                    "Nueva tienda",
                    "Editar",
                    "Gestionar cajas",
                    "Gestionar usuarios",
                    "Eliminar tienda",
                ):
                    expect(cashier_page.get_by_text(text, exact=True)).to_have_count(0)
                response = cashier_page.goto(
                    f"{self.live_server_url}{reverse('stores:store_detail', args=[self.second.pk])}"
                )
                self.assertIn(response.status, (403, 404))
                response = cashier_page.goto(
                    f"{self.live_server_url}{reverse('cash_register:register_admin', args=[self.default.pk])}"
                )
                self.assertEqual(response.status, 403)

    def test_store_and_register_open_session_guards_and_register_lifecycle(self):
        session = CashSession.objects.create(
            business=self.business,
            store=self.second,
            cash_register=self.register,
            opened_by=self.owner,
        )
        clean_store = Store.objects.create(
            business=self.business, name="Lifecycle", code="LIFECYCLE"
        )
        clean_register = CashRegister.objects.create(
            business=self.business,
            store=clean_store,
            name="Lifecycle register",
            code="LIFE-01",
        )
        with sync_playwright() as playwright:
            with self.open_browser(playwright) as browser:
                page = browser.new_page()
                self.login(page, self.owner)
                page.goto(
                    f"{self.live_server_url}{reverse('stores:store_deactivate', args=[self.second.pk])}"
                )
                page.get_by_role("button", name="Desactivar tienda").click()
                expect(
                    page.get_by_text(
                        "No puedes desactivar esta tienda porque tiene una sesión de caja abierta",
                        exact=False,
                    )
                ).to_be_visible()
                page.goto(
                    f"{self.live_server_url}{reverse('cash_register:register_admin', args=[self.second.pk])}"
                )
                page.get_by_role("button", name="Desactivar").click()
                expect(
                    page.get_by_text(
                        "No puedes desactivar esta caja porque tiene una sesión abierta",
                        exact=False,
                    )
                ).to_be_visible()
                page.goto(
                    f"{self.live_server_url}{reverse('cash_register:register_admin', args=[clean_store.pk])}"
                )
                clean_card = page.locator(".store-card").filter(
                    has_text="Lifecycle register"
                )
                clean_card.get_by_role("button", name="Desactivar").click()
                expect(clean_card.get_by_text("○ Inactiva", exact=True)).to_be_visible()
                clean_card.get_by_role("button", name="Activar").click()
                expect(clean_card.get_by_text("● Activa", exact=True)).to_be_visible()

                page.goto(
                    f"{self.live_server_url}{reverse('stores:store_deactivate', args=[clean_store.pk])}"
                )
                page.get_by_role("button", name="Desactivar tienda").click()
                expect(page.get_by_text("○ Inactiva", exact=True)).to_be_visible()
                store_tabs = page.get_by_role(
                    "navigation", name="Secciones de la tienda"
                )
                store_tabs.get_by_role("link", name="Configuración", exact=True).click()
                page.get_by_role("link", name="Activar tienda").click()
                page.get_by_role("button", name="Activar tienda").click()
                expect(page.get_by_text("● Activa", exact=True)).to_be_visible()

        self.second.refresh_from_db()
        self.register.refresh_from_db()
        session.refresh_from_db()
        clean_store.refresh_from_db()
        clean_register.refresh_from_db()
        self.assertTrue(self.second.is_active)
        self.assertTrue(self.register.is_active)
        self.assertEqual(session.status, CashSession.Status.OPEN)
        self.assertTrue(clean_store.is_active)
        self.assertTrue(clean_register.is_active)

    def test_cash_register_crud_delete_confirmation_and_tenant_isolation(self):
        other = OnboardingService.create_business(
            legal_name="Other Stores E2E SL",
            trade_name="Other Stores E2E",
            tax_identifier="B10000022",
            phone="923000022",
            email="other-stores@example.com",
            address_line_1="Other 22",
            postal_code="37022",
            city="Salamanca",
            province="Salamanca",
            country_code="ES",
            store_name="Other store",
            owner_first_name="Other",
            owner_last_name="Owner",
            owner_email="other-owner@example.com",
            owner_phone="600000022",
            owner_password=self.password,
            owner_pin="1234",
        )
        other_register = CashRegister.objects.create(
            business=other.business,
            store=other.store,
            name="Other register",
            code="OTHER-01",
        )
        clean_store = Store.objects.create(
            business=self.business, name="Creada por error", code="ERROR"
        )
        with sync_playwright() as playwright:
            with self.open_browser(playwright) as browser:
                page = browser.new_page()
                self.login(page, self.owner)
                page.goto(
                    f"{self.live_server_url}{reverse('cash_register:register_admin', args=[self.second.pk])}"
                )
                page.get_by_role("link", name="Nueva caja").click()
                page.get_by_label("Nombre").fill("Caja secundaria")
                page.get_by_label("Código").fill("CAJA-02")
                page.get_by_role("button", name="Guardar caja").click()
                page.locator(".store-card").filter(
                    has_text="Caja secundaria"
                ).get_by_role("link", name="Editar").click()
                page.get_by_label("Nombre").fill("Caja mostrador")
                page.get_by_label("Código").fill("CAJA-03")
                page.get_by_role("button", name="Guardar caja").click()
                edited_card = page.locator(".store-card").filter(
                    has_text="Caja mostrador"
                )
                expect(edited_card.get_by_text("CAJA-03", exact=True)).to_be_visible()

                page.goto(
                    f"{self.live_server_url}{reverse('stores:store_delete', args=[clean_store.pk])}"
                )
                page.get_by_label("Escribe ELIMINAR para confirmar").fill("INCORRECTO")
                page.get_by_role("button", name="Eliminar tienda").click()
                expect(
                    page.get_by_role("alert").get_by_text(
                        "Escribe ELIMINAR para confirmar el borrado definitivo.",
                        exact=True,
                    )
                ).to_be_visible()
                page.get_by_label("Escribe ELIMINAR para confirmar").fill("ELIMINAR")
                page.get_by_role("button", name="Eliminar tienda").click()
                expect(page.get_by_role("heading", name="Tiendas")).to_be_visible()
                expect(page.get_by_text("Creada por error", exact=True)).to_have_count(
                    0
                )

                for path in (
                    reverse("stores:store_detail", args=[other.store.pk]),
                    reverse("stores:store_update", args=[other.store.pk]),
                    reverse("cash_register:register_admin", args=[other.store.pk]),
                    reverse(
                        "cash_register:register_update",
                        args=[other.store.pk, other_register.pk],
                    ),
                ):
                    response = page.request.get(f"{self.live_server_url}{path}")
                    self.assertIn(response.status, (403, 404))

        secondary = CashRegister.objects.get(code="CAJA-03")
        self.assertEqual(secondary.name, "Caja mostrador")
        self.assertEqual(secondary.business, self.business)
        self.assertEqual(secondary.store, self.second)
        self.assertTrue(secondary.is_active)
        self.assertFalse(Store.objects.filter(pk=clean_store.pk).exists())
        other_register.refresh_from_db()
        self.assertTrue(other_register.is_active)
