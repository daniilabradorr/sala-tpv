import json
from pathlib import Path

from django.conf import settings
from django.http import HttpResponse
from django.test import Client, SimpleTestCase
from django.urls import reverse

from apps.core.htmx import add_hx_trigger


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


class ExpiredSessionTests(SimpleTestCase):
    def test_htmx_login_redirect_is_a_full_navigation(self):
        response = Client().get(reverse("core:home"), HTTP_HX_REQUEST="true")
        self.assertEqual(response.status_code, 204)
        self.assertIn(reverse("users:login"), response["HX-Redirect"])
        self.assertIn("next=%2F", response["HX-Redirect"])
        self.assertEqual(response.content, b"")

    def test_normal_request_keeps_django_redirect(self):
        response = Client().get(reverse("core:home"))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("users:login"), response["Location"])
        self.assertNotIn("HX-Redirect", response)
