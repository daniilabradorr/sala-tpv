from django.test import TestCase, override_settings
from django.urls import reverse

from apps.users.models import CustomUser, RoleChoices, UserStoreAccess
from apps.users.tests.factories import (
    create_business,
    create_store,
    create_user,
    create_store_access,
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
                        "users/login.html": "{{ form.errors }}",
                        "users/profile.html": "{{ object.email }}",
                        "users/profile_update.html": "{{ form.errors }}",
                        "users/password_change.html": "{{ form.errors }}",
                        "users/pin_change.html": "{{ form.errors }}",
                        "users/user_list.html": "{% for user in users %}{{ user.email }} {% endfor %}",
                        "users/user_detail.html": "{{ target_user.email }}",
                        "users/user_create.html": "{{ form.errors }}",
                        "users/user_update.html": "{{ form.errors }}",
                        "users/user_store_access_manage.html": "{{ formset.errors }} {{ formset.non_form_errors }}",
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
class UserViewsIntegrationTests(TestCase):
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

        self.owner = create_user(
            business=self.business,
            email="owner@test.com",
            password=self.password,
            role=RoleChoices.OWNER,
            first_name="Owner",
            last_name="User",
        )

        self.manager = create_user(
            business=self.business,
            email="manager@test.com",
            password=self.password,
            role=RoleChoices.MANAGER,
            first_name="Manager",
            last_name="User",
        )

        self.cashier = create_user(
            business=self.business,
            email="cashier@test.com",
            password=self.password,
            role=RoleChoices.CASHIER,
            first_name="Cashier",
            last_name="User",
        )

        self.target_user = create_user(
            business=self.business,
            email="target@test.com",
            password=self.password,
            role=RoleChoices.CASHIER,
            first_name="Target",
            last_name="User",
        )

        self.other_user = create_user(
            business=self.other_business,
            email="other@test.com",
            password=self.password,
            role=RoleChoices.CASHIER,
            first_name="Other",
            last_name="User",
        )

    def login_as(self, user):
        logged_in = self.client.login(
            email=user.email,
            password=self.password,
        )
        self.assertTrue(logged_in)

    # ============================================================
    # AUTENTICACIÓN
    # ============================================================

    def test_login_view_rejects_wrong_password_and_accepts_correct_password(self):
        """Verifica que el login rechace contraseñas incorrectas y acepte las correctas."""
        url = reverse("users:login") + f"?next={reverse('users:profile')}"

        bad_response = self.client.post(
            url,
            data={
                "username": self.owner.email,
                "password": "wrongpass123",
            },
        )

        self.assertEqual(bad_response.status_code, 200)
        self.assertNotIn("_auth_user_id", self.client.session)

        good_response = self.client.post(
            url,
            data={
                "username": self.owner.email,
                "password": self.password,
            },
        )

        self.assertRedirects(
            good_response,
            reverse("users:profile"),
            fetch_redirect_response=False,
        )
        self.assertIn("_auth_user_id", self.client.session)

    def test_logout_view_logs_user_out_and_redirects_to_login(self):
        """Verifica que el logout cierre la sesión y redirija al login."""
        self.login_as(self.owner)

        response = self.client.post(reverse("users:logout"))

        self.assertRedirects(
            response,
            reverse("users:login"),
            fetch_redirect_response=False,
        )
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_unauthenticated_user_is_redirected_from_profile(self):
        """Verifica que un usuario no autenticado sea redirigido al login desde el perfil."""
        response = self.client.get(reverse("users:profile"))

        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.url.startswith(reverse("users:login")))
        self.assertIn("next=", response.url)

    # ============================================================
    # PERFIL
    # ============================================================

    def test_logged_user_can_view_own_profile(self):
        """Verifica que un usuario autenticado pueda ver su propio perfil."""
        self.login_as(self.owner)

        response = self.client.get(reverse("users:profile"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["object"], self.owner)

    def test_profile_update_changes_only_allowed_fields(self):
        """Verifica que la actualización del perfil solo cambie campos permitidos e ignore intentos de manipulación."""
        self.login_as(self.owner)

        response = self.client.post(
            reverse("users:profile_update"),
            data={
                "first_name": "Daniel",
                "last_name": "Labrador",
                "phone": "600999888",
                # Campos manipulados que NO están en el form.
                # Django debe ignorarlos.
                "role": RoleChoices.CASHIER,
                "business": str(self.other_business.pk),
                "is_superuser": "on",
            },
        )

        self.owner.refresh_from_db()

        self.assertRedirects(
            response,
            reverse("users:profile"),
            fetch_redirect_response=False,
        )
        self.assertEqual(self.owner.first_name, "Daniel")
        self.assertEqual(self.owner.last_name, "Labrador")
        self.assertEqual(self.owner.phone, "600999888")
        self.assertEqual(self.owner.role, RoleChoices.OWNER)
        self.assertEqual(self.owner.business, self.business)
        self.assertFalse(self.owner.is_superuser)

    def test_password_change_updates_password(self):
        """Verifica que el cambio de contraseña actualice correctamente la password del usuario."""
        self.login_as(self.owner)

        response = self.client.post(
            reverse("users:password_change"),
            data={
                "old_password": self.password,
                "new_password1": "newpass12345",
                "new_password2": "newpass12345",
            },
        )

        self.owner.refresh_from_db()

        self.assertRedirects(
            response,
            reverse("users:profile"),
            fetch_redirect_response=False,
        )
        self.assertTrue(self.owner.check_password("newpass12345"))

        self.client.logout()
        self.assertTrue(
            self.client.login(
                email=self.owner.email,
                password="newpass12345",
            )
        )

    def test_pin_change_requires_login(self):
        """Verifica que el cambio de PIN requiera estar autenticado."""
        response = self.client.post(
            reverse("users:pin_change"),
            data={
                "new_pin": "1234",
                "new_pin_confirm": "1234",
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.url.startswith(reverse("users:login")))

    def test_pin_change_saves_pin_as_hash(self):
        """Verifica que el PIN se guarde hasheado y sea validable con check_pin()."""
        self.login_as(self.owner)

        response = self.client.post(
            reverse("users:pin_change"),
            data={
                "new_pin": "1234",
                "new_pin_confirm": "1234",
            },
        )

        self.owner.refresh_from_db()

        self.assertRedirects(
            response,
            reverse("users:profile"),
            fetch_redirect_response=False,
        )
        self.assertNotEqual(self.owner.pin_hash, "1234")
        self.assertTrue(self.owner.check_pin("1234"))

    # ============================================================
    # LISTADO Y DETALLE DE USUARIOS
    # ============================================================

    def test_owner_can_access_user_list(self):
        """Verifica que un propietario pueda acceder al listado de usuarios."""
        self.login_as(self.owner)

        response = self.client.get(reverse("users:user_list"))

        self.assertEqual(response.status_code, 200)

    def test_manager_can_access_user_list(self):
        """Verifica que un gerente pueda acceder al listado de usuarios."""
        self.login_as(self.manager)

        response = self.client.get(reverse("users:user_list"))

        self.assertEqual(response.status_code, 200)

    def test_cashier_cannot_access_user_list(self):
        """Verifica que un cajero no pueda acceder al listado de usuarios (error 403)."""
        self.login_as(self.cashier)

        response = self.client.get(reverse("users:user_list"))

        self.assertEqual(response.status_code, 403)

    def test_user_list_only_shows_users_from_same_business(self):
        """Verifica que el listado de usuarios solo muestre usuarios del mismo negocio."""
        self.login_as(self.owner)

        response = self.client.get(reverse("users:user_list"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "owner@test.com")
        self.assertContains(response, "manager@test.com")
        self.assertContains(response, "cashier@test.com")
        self.assertContains(response, "target@test.com")
        self.assertNotContains(response, "other@test.com")

    def test_owner_can_view_user_detail_from_same_business(self):
        """Verifica que un propietario pueda ver los detalles de un usuario del mismo negocio."""
        self.login_as(self.owner)

        response = self.client.get(
            reverse("users:user_detail", kwargs={"pk": self.target_user.pk})
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.target_user.email)

    def test_manager_can_view_user_detail_from_same_business(self):
        """Verifica que un gerente pueda ver los detalles de un usuario del mismo negocio."""
        self.login_as(self.manager)

        response = self.client.get(
            reverse("users:user_detail", kwargs={"pk": self.target_user.pk})
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.target_user.email)

    def test_user_detail_blocks_user_from_other_business(self):
        """Verifica que no se puedan ver detalles de usuarios de otro negocio (error 404)."""
        self.login_as(self.owner)

        response = self.client.get(
            reverse("users:user_detail", kwargs={"pk": self.other_user.pk})
        )

        self.assertEqual(response.status_code, 404)

    # ============================================================
    # CREACIÓN DE USUARIOS
    # ============================================================

    def test_owner_can_create_user_in_own_business(self):
        """Verifica que un propietario pueda crear un nuevo usuario en su negocio."""
        self.login_as(self.owner)

        response = self.client.post(
            reverse("users:user_create"),
            data={
                "email": "newuser@test.com",
                "first_name": "Nuevo",
                "last_name": "Usuario",
                "phone": "600123123",
                "role": RoleChoices.CASHIER,
                "password": self.password,
                "password_confirm": self.password,
            },
        )

        new_user = CustomUser.objects.get(email="newuser@test.com")

        self.assertEqual(response.status_code, 302)
        self.assertEqual(new_user.business, self.business)
        self.assertEqual(new_user.role, RoleChoices.CASHIER)
        self.assertTrue(new_user.check_password(self.password))

        self.assertRedirects(
            response,
            reverse("users:user_detail", kwargs={"pk": new_user.pk}),
            fetch_redirect_response=False,
        )

    def test_manager_can_create_user_in_own_business(self):
        """Verifica que un gerente pueda crear un nuevo usuario en su negocio."""
        self.login_as(self.manager)

        response = self.client.post(
            reverse("users:user_create"),
            data={
                "email": "managercreated@test.com",
                "first_name": "Manager",
                "last_name": "Created",
                "phone": "600123123",
                "role": RoleChoices.CASHIER,
                "password": self.password,
                "password_confirm": self.password,
            },
        )

        new_user = CustomUser.objects.get(email="managercreated@test.com")

        self.assertEqual(response.status_code, 302)
        self.assertEqual(new_user.business, self.business)

    def test_cashier_cannot_create_users(self):
        """Verifica que un cajero no pueda crear usuarios (error 403)."""
        self.login_as(self.cashier)

        response = self.client.post(
            reverse("users:user_create"),
            data={
                "email": "blocked@test.com",
                "first_name": "Blocked",
                "last_name": "User",
                "phone": "600123123",
                "role": RoleChoices.CASHIER,
                "password": self.password,
                "password_confirm": self.password,
            },
        )

        self.assertEqual(response.status_code, 403)
        self.assertFalse(CustomUser.objects.filter(email="blocked@test.com").exists())

    def test_manipulated_business_field_is_ignored_when_creating_user(self):
        """Verifica que intentos de manipular el campo business en creación se ignoren."""
        self.login_as(self.owner)

        response = self.client.post(
            reverse("users:user_create"),
            data={
                "email": "hacker@test.com",
                "first_name": "Hacker",
                "last_name": "User",
                "phone": "600123123",
                "role": RoleChoices.CASHIER,
                "password": self.password,
                "password_confirm": self.password,
                # Campo manipulado. No está en UserCreateForm.
                "business": str(self.other_business.pk),
            },
        )

        new_user = CustomUser.objects.get(email="hacker@test.com")

        self.assertEqual(response.status_code, 302)
        self.assertEqual(new_user.business, self.business)
        self.assertNotEqual(new_user.business, self.other_business)

    # ============================================================
    # EDICIÓN DE USUARIOS
    # ============================================================

    def test_owner_can_update_user_from_same_business(self):
        """Verifica que un propietario pueda actualizar un usuario del mismo negocio e ignore campos manipulados."""
        self.login_as(self.owner)

        response = self.client.post(
            reverse("users:user_update", kwargs={"pk": self.target_user.pk}),
            data={
                "first_name": "Editado",
                "last_name": "Por Owner",
                "phone": "600111222",
                "role": RoleChoices.MANAGER,
                "is_active": "on",
                # Campos manipulados que deben ignorarse.
                "business": str(self.other_business.pk),
                "is_superuser": "on",
            },
        )

        self.target_user.refresh_from_db()

        self.assertRedirects(
            response,
            reverse("users:user_detail", kwargs={"pk": self.target_user.pk}),
            fetch_redirect_response=False,
        )
        self.assertEqual(self.target_user.first_name, "Editado")
        self.assertEqual(self.target_user.last_name, "Por Owner")
        self.assertEqual(self.target_user.phone, "600111222")
        self.assertEqual(self.target_user.role, RoleChoices.MANAGER)
        self.assertEqual(self.target_user.business, self.business)
        self.assertFalse(self.target_user.is_superuser)

    def test_manager_can_update_user_from_same_business(self):
        """Verifica que un gerente pueda actualizar un usuario del mismo negocio."""
        self.login_as(self.manager)

        response = self.client.post(
            reverse("users:user_update", kwargs={"pk": self.target_user.pk}),
            data={
                "first_name": "Editado",
                "last_name": "Por Manager",
                "phone": "600333444",
                "role": RoleChoices.CASHIER,
                "is_active": "on",
            },
        )

        self.target_user.refresh_from_db()

        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.target_user.first_name, "Editado")
        self.assertEqual(self.target_user.last_name, "Por Manager")

    def test_cashier_cannot_update_users(self):
        """Verifica que un cajero no pueda actualizar usuarios (error 403)."""
        self.login_as(self.cashier)

        response = self.client.post(
            reverse("users:user_update", kwargs={"pk": self.target_user.pk}),
            data={
                "first_name": "No",
                "last_name": "Permitido",
                "phone": "600333444",
                "role": RoleChoices.MANAGER,
                "is_active": "on",
            },
        )

        self.target_user.refresh_from_db()

        self.assertEqual(response.status_code, 403)
        self.assertNotEqual(self.target_user.first_name, "No")

    def test_update_user_from_other_business_returns_404(self):
        """Verifica que no se pueda actualizar usuarios de otro negocio (error 404)."""
        self.login_as(self.owner)

        response = self.client.post(
            reverse("users:user_update", kwargs={"pk": self.other_user.pk}),
            data={
                "first_name": "Hack",
                "last_name": "Attempt",
                "phone": "600123123",
                "role": RoleChoices.MANAGER,
                "is_active": "on",
            },
        )

        self.other_user.refresh_from_db()

        self.assertEqual(response.status_code, 404)
        self.assertNotEqual(self.other_user.first_name, "Hack")

    # ============================================================
    # ACTIVAR / DESACTIVAR USUARIOS
    # ============================================================

    def test_owner_can_deactivate_user(self):
        """Verifica que un propietario pueda desactivar un usuario."""
        self.login_as(self.owner)

        response = self.client.post(
            reverse("users:user_deactivate", kwargs={"pk": self.target_user.pk})
        )

        self.target_user.refresh_from_db()

        self.assertRedirects(
            response,
            reverse("users:user_list"),
            fetch_redirect_response=False,
        )
        self.assertFalse(self.target_user.is_active)

    def test_manager_can_deactivate_user(self):
        """Verifica que un gerente pueda desactivar un usuario."""
        self.login_as(self.manager)

        response = self.client.post(
            reverse("users:user_deactivate", kwargs={"pk": self.target_user.pk})
        )

        self.target_user.refresh_from_db()

        self.assertEqual(response.status_code, 302)
        self.assertFalse(self.target_user.is_active)

    def test_cashier_cannot_deactivate_user(self):
        """Verifica que un cajero no pueda desactivar usuarios (error 403)."""
        self.login_as(self.cashier)

        response = self.client.post(
            reverse("users:user_deactivate", kwargs={"pk": self.target_user.pk})
        )

        self.target_user.refresh_from_db()

        self.assertEqual(response.status_code, 403)
        self.assertTrue(self.target_user.is_active)

    def test_user_cannot_deactivate_himself(self):
        """Verifica que un usuario no pueda desactivarse a sí mismo."""
        self.login_as(self.owner)

        response = self.client.post(
            reverse("users:user_deactivate", kwargs={"pk": self.owner.pk})
        )

        self.owner.refresh_from_db()

        self.assertRedirects(
            response,
            reverse("users:user_detail", kwargs={"pk": self.owner.pk}),
            fetch_redirect_response=False,
        )
        self.assertTrue(self.owner.is_active)

    def test_owner_can_activate_user(self):
        """Verifica que un propietario pueda activar un usuario desactivado."""
        self.target_user.is_active = False
        self.target_user.save(update_fields=["is_active", "updated_at"])

        self.login_as(self.owner)

        response = self.client.post(
            reverse("users:user_activate", kwargs={"pk": self.target_user.pk})
        )

        self.target_user.refresh_from_db()

        self.assertRedirects(
            response,
            reverse("users:user_detail", kwargs={"pk": self.target_user.pk}),
            fetch_redirect_response=False,
        )
        self.assertTrue(self.target_user.is_active)

    def test_activate_user_from_other_business_returns_404(self):
        """Verifica que no se pueda activar usuarios de otro negocio (error 404)."""
        self.other_user.is_active = False
        self.other_user.save(update_fields=["is_active", "updated_at"])

        self.login_as(self.owner)

        response = self.client.post(
            reverse("users:user_activate", kwargs={"pk": self.other_user.pk})
        )

        self.other_user.refresh_from_db()

        self.assertEqual(response.status_code, 404)
        self.assertFalse(self.other_user.is_active)

    # ============================================================
    # ACCESOS A TIENDAS
    # ============================================================

    def test_owner_can_open_user_store_access_management(self):
        """Verifica que un propietario pueda abrir la gestión de acceso a tiendas del usuario."""
        self.login_as(self.owner)

        response = self.client.get(
            reverse(
                "users:user_store_access_manage",
                kwargs={"pk": self.target_user.pk},
            )
        )

        self.assertEqual(response.status_code, 200)

    def test_manager_can_open_user_store_access_management(self):
        """Verifica que un gerente pueda abrir la gestión de acceso a tiendas del usuario."""
        self.login_as(self.manager)

        response = self.client.get(
            reverse(
                "users:user_store_access_manage",
                kwargs={"pk": self.target_user.pk},
            )
        )

        self.assertEqual(response.status_code, 200)

    def test_cashier_cannot_open_user_store_access_management(self):
        """Verifica que un cajero no pueda acceder a la gestión de acceso a tiendas (error 403)."""
        self.login_as(self.cashier)

        response = self.client.get(
            reverse(
                "users:user_store_access_manage",
                kwargs={"pk": self.target_user.pk},
            )
        )

        self.assertEqual(response.status_code, 403)

    def test_store_access_post_creates_access_for_target_user(self):
        """Verifica que se cree un nuevo acceso a tienda para el usuario con los permisos especificados."""
        self.login_as(self.owner)

        response = self.client.post(
            reverse(
                "users:user_store_access_manage",
                kwargs={"pk": self.target_user.pk},
            ),
            data={
                "store_accesses-TOTAL_FORMS": "1",
                "store_accesses-INITIAL_FORMS": "0",
                "store_accesses-MIN_NUM_FORMS": "0",
                "store_accesses-MAX_NUM_FORMS": "1000",
                "store_accesses-0-store": str(self.store.pk),
                "store_accesses-0-can_sell": "on",
                "store_accesses-0-can_open_cash": "on",
                "store_accesses-0-can_close_cash": "on",
                "store_accesses-0-is_active": "on",
            },
        )

        access = UserStoreAccess.objects.get(
            business=self.business,
            user=self.target_user,
            store=self.store,
        )

        self.assertRedirects(
            response,
            reverse("users:user_detail", kwargs={"pk": self.target_user.pk}),
            fetch_redirect_response=False,
        )
        self.assertTrue(access.can_sell)
        self.assertTrue(access.can_open_cash)
        self.assertTrue(access.can_close_cash)
        self.assertTrue(access.is_active)

    def test_store_access_post_updates_existing_access(self):
        """Verifica que se actualice un acceso a tienda existente con los nuevos permisos."""
        access = create_store_access(
            business=self.business,
            user=self.target_user,
            store=self.store,
            can_sell=True,
            can_open_cash=True,
            can_close_cash=False,
            is_active=True,
        )

        self.login_as(self.owner)

        response = self.client.post(
            reverse(
                "users:user_store_access_manage",
                kwargs={"pk": self.target_user.pk},
            ),
            data={
                "store_accesses-TOTAL_FORMS": "1",
                "store_accesses-INITIAL_FORMS": "1",
                "store_accesses-MIN_NUM_FORMS": "0",
                "store_accesses-MAX_NUM_FORMS": "1000",
                "store_accesses-0-id": str(access.pk),
                "store_accesses-0-store": str(self.store.pk),
                # No enviamos can_sell ni can_open_cash.
                # En formularios HTML, checkbox ausente = False.
                "store_accesses-0-can_close_cash": "on",
                "store_accesses-0-is_active": "on",
            },
        )

        access.refresh_from_db()

        self.assertRedirects(
            response,
            reverse("users:user_detail", kwargs={"pk": self.target_user.pk}),
            fetch_redirect_response=False,
        )
        self.assertFalse(access.can_sell)
        self.assertFalse(access.can_open_cash)
        self.assertTrue(access.can_close_cash)
        self.assertTrue(access.is_active)

    def test_store_access_post_deletes_existing_access(self):
        """Verifica que se pueda eliminar un acceso a tienda existente marcándolo como DELETE."""
        access = create_store_access(
            business=self.business,
            user=self.target_user,
            store=self.store,
        )

        self.login_as(self.owner)

        response = self.client.post(
            reverse(
                "users:user_store_access_manage",
                kwargs={"pk": self.target_user.pk},
            ),
            data={
                "store_accesses-TOTAL_FORMS": "1",
                "store_accesses-INITIAL_FORMS": "1",
                "store_accesses-MIN_NUM_FORMS": "0",
                "store_accesses-MAX_NUM_FORMS": "1000",
                "store_accesses-0-id": str(access.pk),
                "store_accesses-0-store": str(self.store.pk),
                "store_accesses-0-can_sell": "on",
                "store_accesses-0-is_active": "on",
                "store_accesses-0-DELETE": "on",
            },
        )

        self.assertRedirects(
            response,
            reverse("users:user_detail", kwargs={"pk": self.target_user.pk}),
            fetch_redirect_response=False,
        )
        self.assertFalse(UserStoreAccess.objects.filter(pk=access.pk).exists())

    def test_store_access_rejects_store_from_other_business(self):
        """Verifica que se rechace intentar crear acceso a tiendas de otro negocio."""
        self.login_as(self.owner)

        response = self.client.post(
            reverse(
                "users:user_store_access_manage",
                kwargs={"pk": self.target_user.pk},
            ),
            data={
                "store_accesses-TOTAL_FORMS": "1",
                "store_accesses-INITIAL_FORMS": "0",
                "store_accesses-MIN_NUM_FORMS": "0",
                "store_accesses-MAX_NUM_FORMS": "1000",
                "store_accesses-0-store": str(self.other_store.pk),
                "store_accesses-0-can_sell": "on",
                "store_accesses-0-is_active": "on",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(
            UserStoreAccess.objects.filter(
                user=self.target_user,
                store=self.other_store,
            ).exists()
        )

    def test_store_access_blocks_user_from_other_business(self):
        """Verifica que no se pueda acceder a la gestión de tiendas de usuarios de otro negocio (error 404)."""
        self.login_as(self.owner)

        response = self.client.get(
            reverse(
                "users:user_store_access_manage",
                kwargs={"pk": self.other_user.pk},
            )
        )

        self.assertEqual(response.status_code, 404)
