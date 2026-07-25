from django.core.exceptions import PermissionDenied
from django.http import HttpResponse
from django.test import RequestFactory, TestCase
from django.views import View

from apps.users.mixins import (
    CanCloseCashRegisterMixin,
    CanOpenCashRegisterMixin,
    CanSellInStoreMixin,
    StoreAccessRequiredMixin,
)
from apps.users.models import CustomUser, RoleChoices
from apps.users.tests.factories import create_business, create_store


class _AccessView(StoreAccessRequiredMixin, View):
    def get(self, request, *args, **kwargs):
        return HttpResponse("ok")


class _SellView(CanSellInStoreMixin, View):
    def get(self, request, *args, **kwargs):
        return HttpResponse("ok")


class _OpenCashView(CanOpenCashRegisterMixin, View):
    def get(self, request, *args, **kwargs):
        return HttpResponse("ok")


class _CloseCashView(CanCloseCashRegisterMixin, View):
    def get(self, request, *args, **kwargs):
        return HttpResponse("ok")


class StorePermissionMixinsSuperuserTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()

        self.business = create_business(
            name="Negocio Mixins",
            slug="negocio-mixins",
        )

        self.active_store = create_store(
            business=self.business,
            name="Tienda Activa",
            code="ACTIVA",
            is_active=True,
        )

        self.inactive_store = create_store(
            business=self.business,
            name="Tienda Inactiva",
            code="INACTIVA",
            is_active=False,
        )

        self.superuser = CustomUser.objects.create_superuser(
            email="mixins-admin@test.com",
            password="adminpass123",
            role=RoleChoices.OWNER,
            first_name="Admin",
            last_name="Mixins",
            phone="600123123",
        )

    def _request(self):
        request = self.factory.get("/")
        request.user = self.superuser
        return request

    def test_store_access_required_allows_superuser_for_inactive_store(self):
        response = _AccessView.as_view()(
            self._request(), store_id=self.inactive_store.pk
        )

        self.assertEqual(response.status_code, 200)

    def test_can_sell_in_store_rejects_superuser_for_inactive_store(self):
        with self.assertRaises(PermissionDenied):
            _SellView.as_view()(self._request(), store_id=self.inactive_store.pk)

    def test_can_open_cash_register_rejects_superuser_for_inactive_store(self):
        with self.assertRaises(PermissionDenied):
            _OpenCashView.as_view()(self._request(), store_id=self.inactive_store.pk)

    def test_can_close_cash_register_rejects_superuser_for_inactive_store(self):
        with self.assertRaises(PermissionDenied):
            _CloseCashView.as_view()(self._request(), store_id=self.inactive_store.pk)

    def test_sell_open_and_close_mixins_allow_superuser_for_active_store(self):
        sell_response = _SellView.as_view()(
            self._request(), store_id=self.active_store.pk
        )
        open_response = _OpenCashView.as_view()(
            self._request(), store_id=self.active_store.pk
        )
        close_response = _CloseCashView.as_view()(
            self._request(), store_id=self.active_store.pk
        )

        self.assertEqual(sell_response.status_code, 200)
        self.assertEqual(open_response.status_code, 200)
        self.assertEqual(close_response.status_code, 200)
