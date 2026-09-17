from pathlib import Path

from django.conf import settings
from django.contrib.staticfiles import finders
from django.http import HttpResponse
from django.test import RequestFactory, SimpleTestCase
from django_htmx.middleware import HtmxMiddleware


class HtmxMiddlewareTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.middleware = HtmxMiddleware(lambda request: HttpResponse())

    def test_middleware_is_configured(self):
        self.assertIn("django_htmx.middleware.HtmxMiddleware", settings.MIDDLEWARE)

    def test_hx_request_is_recognized(self):
        request = self.factory.get("/", HTTP_HX_REQUEST="true")

        self.middleware(request)

        self.assertTrue(request.htmx)

    def test_normal_request_is_not_htmx(self):
        request = self.factory.get("/")

        self.middleware(request)

        self.assertFalse(request.htmx)


class LocalHtmxAssetTests(SimpleTestCase):
    asset_path = "vendor/htmx/1.9.12/htmx.min.js"

    def test_base_uses_only_local_htmx_asset(self):
        base_template = Path(settings.BASE_DIR, "templates", "base.html").read_text()

        self.assertIn(self.asset_path, base_template)
        self.assertNotIn("unpkg.com/htmx", base_template)

    def test_vendored_htmx_is_resolvable(self):
        self.assertIsNotNone(finders.find(self.asset_path))
