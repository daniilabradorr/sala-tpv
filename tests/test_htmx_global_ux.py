import json
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from django.conf import settings
from django.http import HttpResponse
from django.http import HttpResponseRedirect
from django.test import Client, RequestFactory, SimpleTestCase, TestCase
from django.urls import reverse

from apps.core.htmx import add_hx_trigger
from apps.core.middleware import HtmxLoginRedirectMiddleware


class HxTriggerTests(SimpleTestCase):
    def test_adds_one_event_as_json(self):
        response = add_hx_trigger(HttpResponse(), {"nx:toast": {"message": "Hecho"}})
        self.assertEqual(
            json.loads(response["HX-Trigger"]), {"nx:toast": {"message": "Hecho"}}
        )

    def test_merges_multiple_and_existing_events(self):
        response = HttpResponse(headers={"HX-Trigger": '{"existing":{}}'})
        add_hx_trigger(
            response, {"nx:close-modal": {}, "nx:toast": {"tone": "success"}}
        )
        self.assertEqual(
            set(json.loads(response["HX-Trigger"])),
            {"existing", "nx:close-modal", "nx:toast"},
        )

    def test_normalizes_legacy_and_unexpected_existing_headers(self):
        response = HttpResponse(headers={"HX-Trigger": "legacy-one, legacy-two"})
        add_hx_trigger(response, {"nx:toast": {}})
        self.assertEqual(
            set(json.loads(response["HX-Trigger"])),
            {"legacy-one", "legacy-two", "nx:toast"},
        )

        response = HttpResponse(headers={"HX-Trigger": "42"})
        add_hx_trigger(response, {"nx:toast": {}})
        self.assertEqual(json.loads(response["HX-Trigger"]), {"nx:toast": {}})


class HtmxBaseContractTests(SimpleTestCase):
    def test_csrf_contract_remains_enabled(self):
        self.assertIn("django.middleware.csrf.CsrfViewMiddleware", settings.MIDDLEWARE)
        source = Path(settings.BASE_DIR, "templates", "base.html").read_text()
        self.assertIn('meta name="csrf-token" content="{{ csrf_token }}"', source)
        self.assertNotIn("hx-boost", source)

    def test_global_components_and_scripts_are_declared(self):
        base = Path(settings.BASE_DIR, "templates", "base.html").read_text()
        feedback = Path(
            settings.BASE_DIR, "templates/components/global_feedback.html"
        ).read_text()
        self.assertIn("components/global_feedback.html", base)
        self.assertIn('aria-live="polite"', feedback)


class ExpiredSessionTests(TestCase):
    def test_htmx_login_redirect_is_a_full_navigation(self):
        response = Client().get(reverse("core:home"), HTTP_HX_REQUEST="true")
        self.assertEqual(response.status_code, 204)
        self.assertIn("HX-Redirect", response)
        redirect = urlsplit(response["HX-Redirect"])
        self.assertEqual(redirect.path, reverse("users:login"))
        self.assertEqual(parse_qs(redirect.query).get("next"), ["/"])
        self.assertNotIn("expired", parse_qs(redirect.query))
        self.assertEqual(response.content, b"")

    def test_authenticated_shell_hint_marks_expired_session(self):
        response = Client().get(
            reverse("core:home"),
            HTTP_HX_REQUEST="true",
            HTTP_X_NETXODO_AUTHENTICATED_SHELL="1",
        )
        self.assertEqual(response.status_code, 204)
        redirect = urlsplit(response["HX-Redirect"])
        self.assertEqual(parse_qs(redirect.query).get("next"), ["/"])
        self.assertEqual(parse_qs(redirect.query).get("expired"), ["1"])
        self.assertEqual(response.content, b"")

    def test_normal_request_keeps_django_redirect(self):
        response = Client().get(reverse("core:home"))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("users:login"), response["Location"])
        self.assertNotIn("HX-Redirect", response)

    def test_non_login_redirect_is_never_converted(self):
        request = RequestFactory().get("/source/", HTTP_HX_REQUEST="true")
        request.htmx = True
        middleware = HtmxLoginRedirectMiddleware(
            lambda _request: HttpResponseRedirect("/sales/")
        )
        response = middleware(request)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], "/sales/")
        self.assertNotIn("HX-Redirect", response)

    def test_request_without_htmx_attribute_is_safe(self):
        request = RequestFactory().get("/source/")
        response = HtmxLoginRedirectMiddleware(
            lambda _request: HttpResponseRedirect("/users/login/?next=/source/")
        )(request)
        self.assertEqual(response.status_code, 302)
