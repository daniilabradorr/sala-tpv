"""Browser contract for the operational cash-register surface."""

from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from playwright.sync_api import sync_playwright

from apps.cash_register.models import CashSession
from apps.cash_register.test_factories import (
    create_cash_business,
    create_cash_register,
    create_cash_store,
)
from apps.users.models import RoleChoices
from apps.users.tests.factories import create_user


class CashRegisterBrowserTests(StaticLiveServerTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.playwright = sync_playwright().start()
        cls.browser = cls.playwright.chromium.launch(headless=True)

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.playwright.stop()
        super().tearDownClass()

    def test_register_states_and_responsive_session(self):
        business = create_cash_business()
        store = create_cash_store(business=business)
        user = create_user(
            business=business,
            email="cash-browser@test.com",
            role=RoleChoices.OWNER,
            password="secret",
        )
        closed = create_cash_register(
            business=business, store=store, name="Caja A", code="A"
        )
        opened = create_cash_register(
            business=business, store=store, name="Caja B", code="B"
        )
        create_cash_register(
            business=business, store=store, name="Caja C", code="C", is_active=False
        )
        CashSession.objects.create(
            business=business,
            store=store,
            cash_register=opened,
            opened_by=user,
            opening_amount=100,
            expected_cash_amount=100,
        )
        page = self.browser.new_page(viewport={"width": 375, "height": 812})
        page.goto(f"{self.live_server_url}/accounts/login/")
        page.fill('[name="username"]', user.email)
        page.fill('[name="password"]', "secret")
        page.click('button[type="submit"]')
        page.goto(f"{self.live_server_url}/cash-register/stores/{store.pk}/")
        page.get_by_text("ABIERTA", exact=True).wait_for()
        page.get_by_text("INACTIVA", exact=True).wait_for()
        page.get_by_role("link", name="Abrir caja").click()
        page.locator('input[name="opening_amount"]').fill("100")
        page.get_by_role("button", name="Abrir caja").click()
        self.assertTrue(
            CashSession.objects.filter(
                cash_register=closed, expected_cash_amount=100
            ).exists()
        )
        page.close()
