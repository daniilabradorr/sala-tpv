from django.test import TestCase
from django.urls import reverse
from unittest.mock import patch

from django.core.exceptions import ValidationError

from apps.stores.models import Store
from apps.users.models import CustomUser, RoleChoices, UserStoreAccess
from apps.users.tests.factories import (
    create_business,
    create_store,
    create_user,
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

    def test_owner_sees_edit_store_action_using_existing_update_route(self):
        self.login_as(self.owner)
        response = self.client.get(reverse("stores:store_list"))

        self.assertContains(response, "Editar tienda")
        self.assertContains(
            response, reverse("stores:store_update", kwargs={"pk": self.store.pk})
        )

    def test_store_update_rejects_cross_business_and_cashier(self):
        self.login_as(self.owner)
        self.assertEqual(
            self.client.get(
                reverse("stores:store_update", kwargs={"pk": self.other_store.pk})
            ).status_code,
            404,
        )
        self.client.logout()
        self.login_as(self.cashier)
        self.assertEqual(
            self.client.get(
                reverse("stores:store_update", kwargs={"pk": self.store.pk})
            ).status_code,
            403,
        )

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

    def test_manager_list_shows_all_business_stores_without_access_rows(self):
        second_store = create_store(
            business=self.business,
            name="Tienda Norte",
            code="NORTE",
        )
        self.login_as(self.manager)

        response = self.client.get(reverse("stores:store_list"))

        self.assertContains(response, self.store.name)
        self.assertContains(response, second_store.name)
        self.assertNotContains(response, self.other_store.name)

    def test_cashier_list_only_shows_stores_with_active_access(self):
        inaccessible_store = create_store(
            business=self.business,
            name="Tienda Sin Acceso",
            code="SIN-ACCESO",
        )
        UserStoreAccess.objects.create(
            business=self.business,
            user=self.cashier,
            store=self.store,
            is_active=True,
        )
        UserStoreAccess.objects.create(
            business=self.business,
            user=self.cashier,
            store=inaccessible_store,
            is_active=False,
        )
        self.login_as(self.cashier)

        response = self.client.get(reverse("stores:store_list"))

        self.assertContains(response, self.store.name)
        self.assertNotContains(response, inaccessible_store.name)
        self.assertNotContains(response, self.other_store.name)
        self.assertNotContains(response, "Crear tienda")

    def test_store_list_paginates_ten_stores(self):
        for number in range(11):
            create_store(
                business=self.business,
                name=f"Sucursal {number:02d}",
                code=f"SUC-{number:02d}",
            )
        self.login_as(self.owner)

        response = self.client.get(reverse("stores:store_list"))

        self.assertEqual(len(response.context["stores"]), 10)
        self.assertContains(response, "Página 1 de 2")
        self.assertContains(response, "Siguiente")

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

    def test_owner_can_deactivate_store(self):
        self.login_as(self.owner)

        response = self.client.post(
            reverse("stores:store_deactivate", kwargs={"pk": self.store.pk}),
        )

        self.store.refresh_from_db()

        self.assertRedirects(
            response,
            reverse("stores:store_detail", kwargs={"pk": self.store.pk}),
            fetch_redirect_response=False,
        )
        self.assertFalse(self.store.is_active)

    def test_deactivating_default_store_assigns_replacement(self):
        second_store = create_store(
            business=self.business,
            name="Tienda Norte",
            code="NORTE",
            is_active=True,
        )

        self.store.is_default = True
        self.store.save(update_fields=["is_default", "updated_at"])

        self.login_as(self.owner)

        response = self.client.post(
            reverse("stores:store_deactivate", kwargs={"pk": self.store.pk}),
        )

        self.assertRedirects(
            response,
            reverse("stores:store_detail", kwargs={"pk": self.store.pk}),
            fetch_redirect_response=False,
        )

        self.store.refresh_from_db()
        second_store.refresh_from_db()

        self.assertFalse(self.store.is_default)
        self.assertFalse(self.store.is_active)
        self.assertTrue(second_store.is_default)

    def test_owner_can_activate_store(self):
        self.store.is_active = False
        self.store.save(update_fields=["is_active", "updated_at"])
        self.login_as(self.owner)

        response = self.client.post(
            reverse("stores:store_activate", kwargs={"pk": self.store.pk}),
        )

        self.store.refresh_from_db()

        self.assertRedirects(
            response,
            reverse("stores:store_detail", kwargs={"pk": self.store.pk}),
            fetch_redirect_response=False,
        )
        self.assertTrue(self.store.is_active)

    def test_owner_can_set_default_store(self):
        self.store.is_default = False
        self.store.save(update_fields=["is_default", "updated_at"])

        self.login_as(self.owner)

        response = self.client.post(
            reverse("stores:store_set_default", kwargs={"pk": self.store.pk}),
        )

        self.store.refresh_from_db()

        self.assertRedirects(
            response,
            reverse("stores:store_detail", kwargs={"pk": self.store.pk}),
            fetch_redirect_response=False,
        )
        self.assertTrue(self.store.is_default)

    def test_set_default_view_calls_service_even_if_store_is_already_default(self):
        self.assertTrue(self.store.is_default)

        self.login_as(self.owner)

        with patch(
            "apps.stores.views.set_default_store", return_value=self.store
        ) as mock_service:
            response = self.client.post(
                reverse("stores:store_set_default", kwargs={"pk": self.store.pk}),
            )

        self.assertRedirects(
            response,
            reverse("stores:store_detail", kwargs={"pk": self.store.pk}),
            fetch_redirect_response=False,
        )
        mock_service.assert_called_once()
        self.assertEqual(mock_service.call_args.kwargs["business"], self.business)
        self.assertEqual(mock_service.call_args.kwargs["store"].pk, self.store.pk)

    def test_set_default_view_keeps_working_when_target_is_already_default(self):
        self.assertTrue(self.store.is_default)
        self.login_as(self.owner)

        response = self.client.post(
            reverse("stores:store_set_default", kwargs={"pk": self.store.pk}),
            follow=True,
        )

        self.store.refresh_from_db()

        self.assertEqual(response.status_code, 200)
        self.assertTrue(self.store.is_default)
        self.assertContains(response, self.store.name)
        self.assertContains(response, "es ahora la tienda predeterminada.")

    def test_set_default_view_shows_controlled_error_when_service_fails(self):
        self.login_as(self.owner)

        with patch(
            "apps.stores.views.set_default_store",
            side_effect=ValidationError("Error de validacion controlado."),
        ):
            response = self.client.post(
                reverse("stores:store_set_default", kwargs={"pk": self.store.pk}),
                follow=True,
            )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Error de validacion controlado.")

    def test_manager_can_set_default_store(self):
        second_store = create_store(
            business=self.business,
            name="Tienda Norte",
            code="NORTE",
            is_active=True,
        )

        self.login_as(self.manager)

        response = self.client.post(
            reverse("stores:store_set_default", kwargs={"pk": second_store.pk}),
        )

        second_store.refresh_from_db()
        self.store.refresh_from_db()

        self.assertRedirects(
            response,
            reverse("stores:store_detail", kwargs={"pk": second_store.pk}),
            fetch_redirect_response=False,
        )
        self.assertTrue(second_store.is_default)
        self.assertFalse(self.store.is_default)

    def test_cashier_cannot_set_default_store(self):
        self.login_as(self.cashier)

        response = self.client.post(
            reverse("stores:store_set_default", kwargs={"pk": self.store.pk}),
        )

        self.assertEqual(response.status_code, 403)

    def test_owner_cannot_set_default_store_from_other_business(self):
        self.login_as(self.owner)

        response = self.client.post(
            reverse("stores:store_set_default", kwargs={"pk": self.other_store.pk}),
        )

        self.assertEqual(response.status_code, 404)

    def test_owner_cannot_set_default_when_store_is_inactive(self):
        self.store.is_active = False
        self.store.save(update_fields=["is_active", "updated_at"])

        self.login_as(self.owner)

        response = self.client.post(
            reverse("stores:store_set_default", kwargs={"pk": self.store.pk}),
            follow=True,
        )

        self.store.refresh_from_db()

        self.assertEqual(response.status_code, 200)
        self.assertFalse(self.store.is_default)
        self.assertContains(
            response,
            "No se puede marcar como predeterminada una tienda inactiva.",
        )

    def test_owner_can_delete_store(self):
        self.login_as(self.owner)

        response = self.client.post(
            reverse("stores:store_delete", kwargs={"pk": self.store.pk}),
        )

        self.assertRedirects(
            response,
            reverse("stores:store_list"),
            fetch_redirect_response=False,
        )
        self.assertFalse(Store.objects.filter(pk=self.store.pk).exists())

    def test_manager_cannot_delete_store_from_other_business(self):
        self.login_as(self.manager)

        response = self.client.post(
            reverse("stores:store_delete", kwargs={"pk": self.other_store.pk}),
        )

        self.assertEqual(response.status_code, 404)

    def test_cashier_cannot_access_store_create(self):
        self.login_as(self.cashier)

        response = self.client.get(reverse("stores:store_create"))

        self.assertEqual(response.status_code, 403)

    def test_manager_can_create_store(self):
        self.login_as(self.manager)

        response = self.client.post(
            reverse("stores:store_create"), data=self.valid_store_data()
        )

        self.assertEqual(response.status_code, 302)
        self.assertTrue(
            Store.objects.filter(
                business=self.business, name=self.valid_store_data()["name"]
            ).exists()
        )

    def test_manager_can_update_store(self):
        self.login_as(self.manager)
        data = self.valid_store_data(name="Centro actualizado")
        data["code"] = self.store.code

        response = self.client.post(
            reverse("stores:store_update", kwargs={"pk": self.store.pk}), data=data
        )

        self.store.refresh_from_db()
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.store.name, "Centro actualizado")

    def test_cashier_cannot_update_store(self):
        self.login_as(self.cashier)

        response = self.client.get(
            reverse("stores:store_update", kwargs={"pk": self.store.pk})
        )

        self.assertEqual(response.status_code, 403)

    def test_store_detail_view_works_with_pk_kwarg(self):
        self.login_as(self.owner)

        response = self.client.get(
            reverse("stores:store_detail", kwargs={"pk": self.store.pk}),
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Tienda Centro")

    def test_manager_can_view_business_store_without_access_row(self):
        self.login_as(self.manager)

        response = self.client.get(
            reverse("stores:store_detail", kwargs={"pk": self.store.pk})
        )

        self.assertEqual(response.status_code, 200)

    def test_superuser_owner_without_business_can_view_store_detail(self):
        superuser = CustomUser.objects.create_superuser(
            email="admin-owner@stores.com",
            password=self.password,
            role=RoleChoices.OWNER,
        )
        self.login_as(superuser)

        response = self.client.get(
            reverse("stores:store_detail", kwargs={"pk": self.store.pk})
        )

        self.assertEqual(response.status_code, 200)

    def test_superuser_manager_without_business_can_view_store_detail(self):
        superuser = CustomUser.objects.create_superuser(
            email="admin-manager@stores.com",
            password=self.password,
            role=RoleChoices.MANAGER,
        )
        self.login_as(superuser)

        response = self.client.get(
            reverse("stores:store_detail", kwargs={"pk": self.store.pk})
        )

        self.assertEqual(response.status_code, 200)

    def test_cashier_detail_requires_active_store_access(self):
        self.login_as(self.cashier)
        url = reverse("stores:store_detail", kwargs={"pk": self.store.pk})

        self.assertEqual(self.client.get(url).status_code, 403)
        access = UserStoreAccess.objects.create(
            business=self.business,
            user=self.cashier,
            store=self.store,
            is_active=False,
        )
        self.assertEqual(self.client.get(url).status_code, 403)
        access.is_active = True
        access.save(update_fields=["is_active", "updated_at"])
        self.assertEqual(self.client.get(url).status_code, 200)

    def test_detail_never_allows_a_store_from_another_business(self):
        self.login_as(self.owner)

        response = self.client.get(
            reverse("stores:store_detail", kwargs={"pk": self.other_store.pk})
        )

        self.assertEqual(response.status_code, 403)

    def test_manager_cannot_view_store_from_another_business(self):
        self.login_as(self.manager)

        response = self.client.get(
            reverse("stores:store_detail", kwargs={"pk": self.other_store.pk})
        )

        self.assertEqual(response.status_code, 403)

    def test_mutation_endpoints_do_not_accept_get(self):
        self.login_as(self.owner)

        for route in (
            "store_activate",
            "store_deactivate",
            "store_set_default",
        ):
            with self.subTest(route=route):
                response = self.client.get(
                    reverse(f"stores:{route}", kwargs={"pk": self.store.pk})
                )
                self.assertEqual(response.status_code, 405)

    def test_manager_cannot_modify_store_from_other_business(self):
        self.login_as(self.manager)

        response = self.client.post(
            reverse("stores:store_deactivate", kwargs={"pk": self.other_store.pk}),
        )

        self.assertEqual(response.status_code, 404)
