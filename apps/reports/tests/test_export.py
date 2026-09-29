from django.test import TestCase
from django.urls import reverse

from apps.onboarding.services import OnboardingService
from apps.stores.models import Store
from apps.users.models import CustomUser, RoleChoices, UserStoreAccess


class SalesExportTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        result = OnboardingService.create_business(
            legal_name="Reports Export SL",
            tax_identifier="B10000004",
            phone="923000004",
            email="export@example.com",
            address_line_1="Calle Cuatro",
            postal_code="37004",
            city="Salamanca",
            province="Salamanca",
            country_code="ES",
            store_name="Centro",
            owner_first_name="Owner",
            owner_last_name="Export",
            owner_email="export-owner@example.com",
            owner_phone="600000004",
            owner_password="Safe-Reports-123!",
            owner_pin="1234",
        )
        cls.business, cls.owner, cls.store = result.business, result.owner, result.store
        cls.other_store = Store.objects.create(
            business=cls.business, name="Oeste", code="WEST"
        )
        cls.manager = CustomUser.objects.create_user(
            email="export-manager@example.com",
            password="Safe-Reports-123!",
            business=cls.business,
            role=RoleChoices.MANAGER,
        )
        UserStoreAccess.objects.create(
            business=cls.business, user=cls.manager, store=cls.store
        )

    def test_csv_is_server_generated_from_active_scope(self):
        self.client.force_login(self.owner)
        response = self.client.get(
            reverse("reports:sales_export"), {"period": "today", "store": self.store.pk}
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "text/csv; charset=utf-8")
        self.assertIn("Resumen", response.content.decode("utf-8-sig"))
        self.assertIn("Productos", response.content.decode("utf-8-sig"))

    def test_partial_manager_cannot_export_all_stores(self):
        self.client.force_login(self.manager)
        response = self.client.get(
            reverse("reports:sales_export"), {"period": "today", "store": "all"}
        )
        self.assertEqual(response.status_code, 400)
