from django.test import Client, TestCase
from django.urls import reverse

from apps.business_config.forms import POSSettingsForm
from apps.business_config.models import POSSettings
from apps.business_config.services import create_business_configuration
from apps.core.models import Business
from apps.users.models import CustomUser, RoleChoices


class POSSettingsViewTests(TestCase):
    password = "test-password-123"

    def setUp(self):
        self.business = Business.objects.create(name="Sala", slug="sala")
        self.profile, self.settings = self.create_configuration(
            self.business, "B12345678"
        )
        self.owner = self.create_user("owner@example.com", RoleChoices.OWNER)
        self.url = reverse("business_config:pos")

    def create_configuration(self, business, tax_identifier):
        return create_business_configuration(
            business=business,
            legal_name=f"{business.name} SL",
            tax_identifier=tax_identifier,
            phone="600000000",
            email=f"{business.slug}@example.com",
            address_line_1="Calle Uno",
            postal_code="28001",
            city="Madrid",
            province="Madrid",
        )

    def create_user(self, email, role, *, business=None, is_superuser=False):
        return CustomUser.objects.create_user(
            email=email,
            password=self.password,
            business=self.business if business is None else business,
            role=role,
            first_name="Test",
            last_name="User",
            phone="600000000",
            is_superuser=is_superuser,
        )

    def valid_data(self, **overrides):
        data = {
            field: getattr(self.settings, field)
            for field in POSSettingsForm.Meta.fields
        }
        data.update(overrides)
        return data

    def test_anonymous_user_is_redirected_to_login_with_next(self):
        response = self.client.get(self.url)
        self.assertRedirects(
            response,
            f"{reverse('users:login')}?next={self.url}",
            fetch_redirect_response=False,
        )

    def test_owner_gets_own_settings_form(self):
        self.client.force_login(self.owner)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "business_config/pos_settings_form.html")
        self.assertEqual(response.context["form"].instance, self.settings)
        self.assertContains(response, self.business.name)
        self.assertContains(response, reverse("business_config:profile"))

    def test_manager_and_cashier_cannot_get_or_post(self):
        for role in (RoleChoices.MANAGER, RoleChoices.CASHIER):
            with self.subTest(role=role):
                user = self.create_user(f"{role}@example.com", role)
                self.client.force_login(user)
                self.assertEqual(self.client.get(self.url).status_code, 403)
                self.assertEqual(
                    self.client.post(
                        self.url, self.valid_data(prices_include_tax=False)
                    ).status_code,
                    403,
                )
                self.settings.refresh_from_db()
                self.assertTrue(self.settings.prices_include_tax)
                self.client.logout()

    def test_owner_updates_settings_with_post_redirect_get(self):
        self.client.force_login(self.owner)
        response = self.client.post(
            self.url,
            self.valid_data(
                prices_include_tax=False,
                enable_stock_control=True,
                allow_sale_without_stock=True,
                allow_manual_price=False,
                allow_manual_discounts=False,
                max_manual_discount_percent="0",
                require_open_cash_register=False,
                allow_split_payments=False,
                require_pin_for_sensitive_actions=False,
            ),
        )
        self.assertRedirects(response, self.url, fetch_redirect_response=False)
        self.settings.refresh_from_db()
        self.assertFalse(self.settings.prices_include_tax)
        self.assertTrue(self.settings.enable_stock_control)
        self.assertTrue(self.settings.allow_sale_without_stock)
        self.assertFalse(self.settings.allow_manual_price)
        self.assertFalse(self.settings.allow_manual_discounts)
        self.assertEqual(self.settings.max_manual_discount_percent, 0)
        self.assertFalse(self.settings.require_open_cash_register)
        self.assertFalse(self.settings.allow_split_payments)
        self.assertFalse(self.settings.require_pin_for_sensitive_actions)
        self.assertContains(
            self.client.get(self.url),
            "Configuración del TPV actualizada correctamente.",
        )

    def test_manipulated_business_is_ignored(self):
        other = Business.objects.create(name="Otra", slug="otra")
        _, other_settings = self.create_configuration(other, "B87654321")
        self.client.force_login(self.owner)
        self.client.post(
            self.url,
            self.valid_data(
                prices_include_tax=False,
                business=other.pk,
                business_id=other.pk,
            ),
        )
        self.settings.refresh_from_db()
        other_settings.refresh_from_db()
        self.assertFalse(self.settings.prices_include_tax)
        self.assertTrue(other_settings.prices_include_tax)

    def test_form_and_html_exclude_business(self):
        self.client.force_login(self.owner)
        response = self.client.get(self.url)
        self.assertNotIn("business", response.context["form"].fields)
        self.assertNotContains(response, 'name="business"')

    def test_invalid_discount_combination_is_visible_and_not_persisted(self):
        self.client.force_login(self.owner)
        response = self.client.post(
            self.url,
            self.valid_data(
                allow_manual_discounts=False,
                max_manual_discount_percent="20",
            ),
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response, "Debe ser 0 si los descuentos manuales están desactivados."
        )
        self.settings.refresh_from_db()
        self.assertTrue(self.settings.allow_manual_discounts)

    def test_disabled_discounts_with_zero_are_persisted(self):
        self.client.force_login(self.owner)
        response = self.client.post(
            self.url,
            self.valid_data(
                allow_manual_discounts=False, max_manual_discount_percent="0"
            ),
        )
        self.assertRedirects(response, self.url)
        self.settings.refresh_from_db()
        self.assertFalse(self.settings.allow_manual_discounts)
        self.assertEqual(self.settings.max_manual_discount_percent, 0)

    def test_discount_range_is_validated(self):
        self.client.force_login(self.owner)
        for value in ("-0.01", "100.01"):
            with self.subTest(value=value):
                response = self.client.post(
                    self.url, self.valid_data(max_manual_discount_percent=value)
                )
                self.assertEqual(response.status_code, 200)
                self.assertTrue(
                    response.context["form"]["max_manual_discount_percent"].errors
                )
                self.settings.refresh_from_db()
                self.assertEqual(self.settings.max_manual_discount_percent, 20)

    def test_missing_settings_return_404_without_creating_them(self):
        business = Business.objects.create(name="Sin ajustes", slug="sin-ajustes")
        owner = self.create_user(
            "missing@example.com", RoleChoices.OWNER, business=business
        )
        self.client.force_login(owner)
        self.assertEqual(self.client.get(self.url).status_code, 404)
        self.assertEqual(self.client.post(self.url, {}).status_code, 404)
        self.assertFalse(POSSettings.objects.filter(business=business).exists())

    def test_superuser_without_business_gets_403_for_get_and_post(self):
        superuser = self.create_user(
            "admin@example.com", RoleChoices.OWNER, business=None, is_superuser=True
        )
        superuser.business = None
        superuser.save()
        self.client.force_login(superuser)
        self.assertEqual(self.client.get(self.url).status_code, 403)
        self.assertEqual(self.client.post(self.url, {}).status_code, 403)

    def test_post_requires_csrf_token(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.owner)
        response = client.post(self.url, self.valid_data(prices_include_tax=False))
        self.assertEqual(response.status_code, 403)
        self.settings.refresh_from_db()
        self.assertTrue(self.settings.prices_include_tax)

    def test_update_does_not_change_business_or_profile(self):
        original_profile = {
            "legal_name": self.profile.legal_name,
            "default_tax_rate": self.profile.default_tax_rate,
        }
        self.client.force_login(self.owner)
        self.client.post(self.url, self.valid_data(prices_include_tax=False))
        self.business.refresh_from_db()
        self.profile.refresh_from_db()
        self.assertEqual(self.business.name, "Sala")
        self.assertEqual(self.profile.legal_name, original_profile["legal_name"])
        self.assertEqual(
            self.profile.default_tax_rate, original_profile["default_tax_rate"]
        )
