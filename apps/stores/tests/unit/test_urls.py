from django.test import SimpleTestCase
from django.urls import resolve, reverse

from apps.stores.views import (
    ListStoresView,
    StoreDetailView,
    StoreCreateView,
    StoreUpdateView,
    StoreDeactivateView,
    StoreActivateView,
    StoreDeleteView,
)


class StoreUrlsTests(SimpleTestCase):
    def test_store_list_url_resolves(self):
        url = reverse("stores:store_list")

        self.assertEqual(resolve(url).func.view_class, ListStoresView)

    def test_store_create_url_resolves(self):
        url = reverse("stores:store_create")

        self.assertEqual(resolve(url).func.view_class, StoreCreateView)

    def test_store_detail_url_resolves(self):
        url = reverse("stores:store_detail", kwargs={"pk": 1})

        self.assertEqual(resolve(url).func.view_class, StoreDetailView)

    def test_store_update_url_resolves(self):
        url = reverse("stores:store_update", kwargs={"pk": 1})

        self.assertEqual(resolve(url).func.view_class, StoreUpdateView)

    def test_store_deactivate_url_resolves(self):
        url = reverse("stores:store_deactivate", kwargs={"pk": 1})

        self.assertEqual(resolve(url).func.view_class, StoreDeactivateView)

    def test_store_activate_url_resolves(self):
        url = reverse("stores:store_activate", kwargs={"pk": 1})

        self.assertEqual(resolve(url).func.view_class, StoreActivateView)

    def test_store_delete_url_resolves(self):
        url = reverse("stores:store_delete", kwargs={"pk": 1})

        self.assertEqual(resolve(url).func.view_class, StoreDeleteView)
