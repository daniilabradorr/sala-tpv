from decimal import Decimal

from django.test import Client, TestCase
from django.urls import reverse

from apps.business_config.forms import BusinessProfileForm
from apps.business_config.models import BusinessProfile
from apps.business_config.services import create_business_configuration
from apps.core.models import Business
from apps.users.models import CustomUser, RoleChoices


class BusinessProfileViewTests(TestCase):
    password = "test-password-123"

    def setUp(self):
        self.business = Business.objects.create(
            name="Sala original", slug="sala-original"
        )
        self.profile, _ = create_business_configuration(
            business=self.business,
            legal_name="Sala Original SL",
            tax_identifier="B12345678",
            trade_name="Sala Centro",
            phone="600123123",
            email="empresa@example.com",
            website="https://example.com",
            address_line_1="Calle Mayor 1",
            address_line_2="Local A",
            postal_code="28001",
            city="Madrid",
            province="Madrid",
            brand_name="Sala",
            receipt_footer="Gracias por su visita",
            return_policy="Treinta días",
        )
        self.owner = self.create_user("owner@example.com", RoleChoices.OWNER)
        self.url = reverse("business_config:profile")

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
            field: getattr(self.profile, field)
            for field in BusinessProfileForm.Meta.fields
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

    def test_owner_gets_own_profile_form(self):
        self.client.force_login(self.owner)

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "business_config/profile_form.html")
        self.assertEqual(response.context["form"].instance, self.profile)

    def test_manager_and_cashier_cannot_get_or_post(self):
        for role in (RoleChoices.MANAGER, RoleChoices.CASHIER):
            with self.subTest(role=role):
                user = self.create_user(f"{role}@example.com", role)
                self.client.force_login(user)
                self.assertEqual(self.client.get(self.url).status_code, 403)
                self.assertEqual(
                    self.client.post(
                        self.url, self.valid_data(legal_name="No autorizado SL")
                    ).status_code,
                    403,
                )
                self.profile.refresh_from_db()
                self.assertEqual(self.profile.legal_name, "Sala Original SL")
                self.client.logout()

    def test_owner_updates_profile_with_post_redirect_get(self):
        self.client.force_login(self.owner)

        response = self.client.post(
            self.url,
            self.valid_data(
                legal_name="Sala Actualizada SL",
                trade_name="Sala Nueva",
                phone="699999999",
                email="nueva@example.com",
                address_line_1="Gran Vía 2",
                postal_code="28013",
                city="Madrid",
                province="Comunidad de Madrid",
                receipt_footer="Hasta pronto",
            ),
        )

        self.assertRedirects(
            response,
            self.url,
            fetch_redirect_response=False,
        )
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.legal_name, "Sala Actualizada SL")
        self.assertEqual(self.profile.trade_name, "Sala Nueva")
        self.assertEqual(self.profile.phone, "699999999")
        self.assertEqual(self.profile.email, "nueva@example.com")
        self.assertEqual(self.profile.address_line_1, "Gran Vía 2")
        self.assertEqual(self.profile.receipt_footer, "Hasta pronto")
        follow_response = self.client.get(self.url)
        self.assertContains(
            follow_response,
            "Datos de empresa actualizados correctamente.",
        )

    def test_manipulated_business_and_legacy_tax_fields_are_ignored(self):
        other = Business.objects.create(name="Otra empresa", slug="otra-empresa")
        other_profile, _ = create_business_configuration(
            business=other,
            legal_name="Otra Empresa SL",
            tax_identifier="B87654321",
            phone="611111111",
            email="otra@example.com",
            address_line_1="Otra calle 1",
            postal_code="08001",
            city="Barcelona",
            province="Barcelona",
        )
        original_tax = self.profile.default_tax_rate
        self.client.force_login(self.owner)

        response = self.client.post(
            self.url,
            self.valid_data(
                legal_name="Solo mi empresa SL",
                business=other.pk,
                business_id=other.pk,
                default_tax_rate="99.00",
            ),
        )

        self.assertRedirects(response, self.url)
        self.profile.refresh_from_db()
        other_profile.refresh_from_db()
        self.assertEqual(self.profile.business, self.business)
        self.assertEqual(self.profile.legal_name, "Solo mi empresa SL")
        self.assertEqual(self.profile.default_tax_rate, original_tax)
        self.assertEqual(other_profile.legal_name, "Otra Empresa SL")

    def test_form_and_html_exclude_business_and_default_tax_rate(self):
        self.client.force_login(self.owner)
        response = self.client.get(self.url)

        self.assertNotIn("business", response.context["form"].fields)
        self.assertNotIn("default_tax_rate", response.context["form"].fields)
        self.assertNotContains(response, 'name="business"')
        self.assertNotContains(response, 'name="default_tax_rate"')

    def test_profile_update_does_not_change_business_identity(self):
        self.client.force_login(self.owner)
        self.client.post(
            self.url,
            self.valid_data(
                legal_name="Legal nueva SL",
                trade_name="Comercial nuevo",
                brand_name="Marca nueva",
            ),
        )

        self.business.refresh_from_db()
        self.assertEqual(self.business.name, "Sala original")
        self.assertEqual(self.business.slug, "sala-original")

    def test_duplicate_country_and_tax_identifier_is_a_form_error(self):
        other = Business.objects.create(name="Otra", slug="otra")
        create_business_configuration(
            business=other,
            legal_name="Otra SL",
            tax_identifier="A11111111",
            phone="611111111",
            email="otra@example.com",
            address_line_1="Otra calle",
            postal_code="08001",
            city="Barcelona",
            province="Barcelona",
        )
        self.client.force_login(self.owner)

        response = self.client.post(
            self.url, self.valid_data(country_code="ES", tax_identifier="A11111111")
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["form"].non_field_errors())
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.tax_identifier, "B12345678")

    def test_owner_update_normalizes_fiscal_identity(self):
        self.client.force_login(self.owner)

        response = self.client.post(
            self.url,
            self.valid_data(
                country_code=" es ",
                tax_identifier=" b99999999 ",
            ),
        )

        self.assertRedirects(response, self.url)
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.country_code, "ES")
        self.assertEqual(self.profile.tax_identifier, "B99999999")

    def test_normalized_duplicate_fiscal_identity_is_a_form_error(self):
        other = Business.objects.create(
            name="Otra normalizada", slug="otra-normalizada"
        )
        other_profile, _ = create_business_configuration(
            business=other,
            legal_name="Otra Normalizada SL",
            tax_identifier="B99999999",
            phone="611111111",
            email="normalizada@example.com",
            address_line_1="Otra calle",
            postal_code="08001",
            city="Barcelona",
            province="Barcelona",
        )
        other_owner = self.create_user(
            "normalizada-owner@example.com",
            RoleChoices.OWNER,
            business=other,
        )
        self.client.force_login(other_owner)

        response = self.client.post(
            self.url,
            {
                field: getattr(other_profile, field)
                for field in BusinessProfileForm.Meta.fields
            }
            | {
                "country_code": " es ",
                "tax_identifier": " b12345678 ",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["form"].non_field_errors())
        other_profile.refresh_from_db()
        self.assertEqual(other_profile.country_code, "ES")
        self.assertEqual(other_profile.tax_identifier, "B99999999")

    def test_missing_profile_returns_404_without_creating_one(self):
        business = Business.objects.create(name="Sin perfil", slug="sin-perfil")
        owner = self.create_user(
            "sin-perfil@example.com", RoleChoices.OWNER, business=business
        )
        self.client.force_login(owner)

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 404)
        self.assertFalse(BusinessProfile.objects.filter(business=business).exists())

    def test_superuser_without_business_gets_403(self):
        superuser = self.create_user(
            "admin@example.com", RoleChoices.OWNER, business=None, is_superuser=True
        )
        superuser.business = None
        superuser.save()
        self.client.force_login(superuser)

        self.assertEqual(self.client.get(self.url).status_code, 403)

    def test_post_requires_csrf_token(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.owner)

        response = client.post(self.url, self.valid_data(legal_name="Ataque SL"))

        self.assertEqual(response.status_code, 403)
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.legal_name, "Sala Original SL")

    def test_invalid_data_displays_errors_without_persisting(self):
        self.client.force_login(self.owner)

        response = self.client.post(
            self.url,
            self.valid_data(legal_name="", email="no-es-email", website="no-es-url"),
        )

        self.assertEqual(response.status_code, 200)
        self.assertFormError(
            response.context["form"], "legal_name", "Este campo es obligatorio."
        )
        self.assertTrue(response.context["form"]["email"].errors)
        self.assertTrue(response.context["form"]["website"].errors)
        self.assertContains(response, "Este campo es obligatorio.")
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.email, "empresa@example.com")

    def test_profile_page_has_no_business_id_route(self):
        self.assertEqual(self.url, "/config/profile/")
        response = self.client.get(f"/config/{self.business.pk}/profile/")
        self.assertEqual(response.status_code, 404)

    def test_default_tax_rate_starts_unchanged(self):
        self.assertEqual(self.profile.default_tax_rate, Decimal("21.00"))
