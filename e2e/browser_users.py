"""Real Chromium coverage for FE-22 user administration."""

import re
from contextlib import contextmanager
from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.test import override_settings
from django.urls import reverse
from playwright.sync_api import expect, sync_playwright
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
class BrowserUsersTests(StaticLiveServerTestCase):
    password = "E2E-Users-Password-123!"

    def setUp(self):
        result = OnboardingService.create_business(
            legal_name="Users E2E SL",
            trade_name="Users E2E",
            tax_identifier="B10000022",
            phone="923000022",
            email="users-business@example.com",
            address_line_1="Calle Usuarios 22",
            postal_code="37022",
            city="Salamanca",
            province="Salamanca",
            country_code="ES",
            store_name="Centro",
            owner_first_name="Olivia",
            owner_last_name="Owner",
            owner_email="users-owner@example.com",
            owner_phone="600000022",
            owner_password=self.password,
            owner_pin="1234",
        )
        self.business, self.owner, self.centre = (
            result.business,
            result.owner,
            result.store,
        )
        self.second = Store.objects.create(
            business=self.business, name="Gran Vía", code="GRAN-VIA"
        )
        self.manager = CustomUser.objects.create_user(
            business=self.business,
            email="users-manager@example.com",
            password=self.password,
            role=RoleChoices.MANAGER,
            first_name="Laura",
            last_name="Martín",
            phone="600000023",
        )
        self.cashier = CustomUser.objects.create_user(
            business=self.business,
            email="users-cashier@example.com",
            password=self.password,
            role=RoleChoices.CASHIER,
            first_name="Carlos",
            last_name="Caja",
            phone="600000024",
        )
        UserStoreAccess.objects.create(
            business=self.business, user=self.manager, store=self.centre
        )
        UserStoreAccess.objects.create(
            business=self.business, user=self.cashier, store=self.centre
        )

    @contextmanager
    def browser(self, playwright):
        browser = playwright.chromium.launch(headless=True)
        try:
            yield browser
        finally:
            browser.close()

    def login(self, page, user):
        page.goto(f"{self.live_server_url}{reverse('users:login')}")
        page.get_by_label("Correo electrónico").fill(user.email)
        page.get_by_label("Contraseña").fill(self.password)
        page.get_by_role("button", name="Iniciar sesión").click()
        page.wait_for_url(f"{self.live_server_url}/")

    def test_owner_list_filters_and_real_responsive_cards(self):
        with sync_playwright() as p:
            with self.browser(p) as browser:
                page = browser.new_page(viewport={"width": 1280, "height": 812})
                self.login(page, self.owner)
                expect(
                    page.locator("#app-sidebar").get_by_role("link", name="Usuarios")
                ).to_be_visible()
                page.keyboard.press("Control+k")
                expect(
                    page.locator("[data-command-dialog]").get_by_role(
                        "link", name="Usuarios"
                    )
                ).to_be_visible()
                page.keyboard.press("Escape")
                page.goto(f"{self.live_server_url}{reverse('users:user_list')}")
                users_table = page.locator(".users-table")
                cards = page.locator(".user-cards")
                expect(page.get_by_role("heading", name="Usuarios")).to_be_visible()
                expect(users_table).to_be_visible()
                expect(cards).to_be_hidden()
                page.get_by_label("Buscar por nombre o email").fill("Laura")
                page.get_by_role("button", name="Filtrar").click()
                expect(
                    users_table.get_by_text("users-manager@example.com", exact=True)
                ).to_be_visible()
                page.set_viewport_size({"width": 375, "height": 812})
                expect(users_table).to_be_hidden()
                expect(cards).to_be_visible()
                self.assertLessEqual(
                    page.evaluate("document.documentElement.scrollWidth"), 375
                )

    def test_owner_creates_manager_with_store_matrix(self):
        with sync_playwright() as p:
            with self.browser(p) as browser:
                page = browser.new_page()
                self.login(page, self.owner)
                page.goto(f"{self.live_server_url}{reverse('users:user_create')}")
                step1 = page.locator('[data-wizard-step="1"]')
                step2 = page.locator('[data-wizard-step="2"]')
                expect(step1).to_be_visible()
                expect(step2).to_be_hidden()
                step1.get_by_label("Correo electrónico").fill("new-manager@example.com")
                step1.get_by_label("Nombre").fill("Nueva")
                step1.get_by_label("Apellidos").fill("Manager")
                step1.get_by_label("Teléfono").fill("600000025")
                step1.get_by_label("Rol").select_option("manager")
                step1.get_by_label(re.compile(r"^Contraseña")).fill(self.password)
                step1.get_by_label(re.compile(r"^Confirmar contraseña")).fill(
                    self.password
                )
                step1.get_by_role("button", name="Continuar").click()
                expect(step1).to_be_hidden()
                expect(step2).to_be_visible()
                step2.get_by_role("button", name="Volver").click()
                expect(step1).to_be_visible()
                step1.get_by_role("button", name="Continuar").click()
                centre = page.locator("fieldset", has_text="Centro")
                centre.get_by_label("Acceso").check()
                centre.get_by_label("Vender").check()
                centre.get_by_label("Abrir caja").check()
                centre.get_by_label("Cerrar caja").check()
                second = page.locator("fieldset", has_text="Gran Vía")
                second.get_by_label("Acceso").check()
                second.get_by_label("Vender").check()
                second.get_by_label("Abrir caja").check()
                page.get_by_role("button", name="Crear usuario").click()
                expect(
                    page.get_by_role("heading", name="Nueva Manager")
                ).to_be_visible()
        created = CustomUser.objects.get(email="new-manager@example.com")
        self.assertTrue(created.check_password(self.password))
        self.assertEqual(created.store_accesses.filter(is_active=True).count(), 2)

    def test_owner_role_uses_global_access_instead_of_matrix(self):
        with sync_playwright() as p:
            with self.browser(p) as browser:
                page = browser.new_page()
                self.login(page, self.owner)
                page.goto(f"{self.live_server_url}{reverse('users:user_create')}")
                page.get_by_label("Rol").select_option("owner")
                page.get_by_role("button", name="Continuar").click()
                expect(page.locator("[data-owner-global]")).to_be_visible()
                expect(page.locator("[data-access-matrix]")).to_be_hidden()

    def test_manager_owner_read_only_and_cashier_denied(self):
        with sync_playwright() as p:
            with self.browser(p) as browser:
                page = browser.new_page()
                self.login(page, self.manager)
                page.goto(
                    f"{self.live_server_url}{reverse('users:user_detail', kwargs={'pk': self.owner.pk})}"
                )
                expect(page.get_by_role("heading", name="Olivia Owner")).to_be_visible()
                expect(page.get_by_role("link", name="Editar")).to_have_count(0)
                page.goto(
                    f"{self.live_server_url}{reverse('users:user_update', kwargs={'pk': self.owner.pk})}"
                )
                expect(
                    page.get_by_role("heading", name="No tienes acceso a esta sección")
                ).to_be_visible()
                page.context.clear_cookies()
                self.login(page, self.cashier)
                page.goto(f"{self.live_server_url}{reverse('users:user_list')}")
                expect(
                    page.get_by_role("heading", name="No tienes acceso a esta sección")
                ).to_be_visible()
