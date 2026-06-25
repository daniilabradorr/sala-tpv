from django.test import TestCase, override_settings
from django.urls import reverse

from apps.stores.models import Store
from apps.users.models import RoleChoices
from apps.users.tests.factories import (
    create_business,
    create_store,
    create_user,
)


TEST_TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "APP_DIRS": False,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
            "loaders": [
                (
                    "django.template.loaders.locmem.Loader",
                    {
                        "stores/list_stores.html": "{% for store in stores %}{{ store.name }} {% endfor %}",
                        "stores/store_detail.html": "{{ store.name }}",
                        "stores/store_create.html": "{{ form.errors }}",
                        "stores/store_update.html": "{{ form.errors }}",
                        "stores/store_confirm_delete.html": "{{ store.name }}",
                    },
                )
            ],
        },
    }
]


@override_settings(
    TEMPLATES=TEST_TEMPLATES,
    LOGIN_URL="/users/login/",
)
class StoreViewsIntegrationTests(TestCase):
    password = "testpass123"

    def setUp(self):
        self.business = create_business(
            name="Negocio A",
            slug="negocio-a",
        )

        self.other_business = create_business(
            name="Negocio B",
            slug="negocio-b",
        )

        self.owner = create_user(
            business=self.business,
            email="owner@stores.com",
            password=self.password,
            role=RoleChoices.OWNER,
        )

        self.manager = create_user(
            business=self.business,
            email="manager@stores.com",
            password=self.password,
            role=RoleChoices.MANAGER,
        )

        self.cashier = create_user(
            business=self.business,
            email="cashier@stores.com",
            password=self.password,
            role=RoleChoices.CASHIER,
        )

        self.store = create_store(
            business=self.business,
            name="Tienda Centro",
            code="CENTRO",
        )

        self.other_store = create_store(
            business=self.other_business,
            name="Tienda Otro Negocio",
            code="OTRA",
        )

    def login_as(self, user):
        logged_in = self.client.login(
            email=user.email,
            password=self.password,
        )
        self.assertTrue(logged_in)

    def valid_store_data(self, **overrides):
        data = {
            "name": "Tienda Nueva",
            "address_line_1": "Calle Mayor 1",
            "address_line_2": "",
            "postal_code": "37001",
            "city": "Salamanca",
            "province": "Salamanca",
            "country_code": "ES",
            "phone_store": "600123123",
            "email_store": "nueva@test.com",
        }
        data.update(overrides)
        return data

    def test_store_list_only_shows_stores_from_current_business(self):
        """
        Test de integración:
        comprueba que la vista lista solo tiendas del negocio del usuario.
        """
        self.login_as(self.owner)

        response = self.client.get(reverse("stores:store_list"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Tienda Centro")
        self.assertNotContains(response, "Tienda Otro Negocio")

    def test_owner_can_create_store_in_own_business_and_manipulated_business_is_ignored(
        self,
    ):
        """
        Test de integración:
        comprueba URL + login + form + guardado en BD.

        También valida que aunque alguien mande business por POST,
        la vista lo ignore y use request.user.business.
        """
        self.login_as(self.owner)

        response = self.client.post(
            reverse("stores:store_create"),
            data={
                **self.valid_store_data(),
                "business": str(self.other_business.pk),
                "is_active": "",
            },
        )

        new_store = Store.objects.get(name="Tienda Nueva")

        self.assertRedirects(
            response,
            reverse("stores:store_detail", kwargs={"pk": new_store.pk}),
            fetch_redirect_response=False,
        )
        self.assertEqual(new_store.business, self.business)
        self.assertNotEqual(new_store.business, self.other_business)
        self.assertTrue(new_store.code)
        self.assertTrue(new_store.is_active)
