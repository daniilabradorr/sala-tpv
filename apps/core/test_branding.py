from django.contrib import admin
from django.template.loader import render_to_string
from django.test import SimpleTestCase


class BrandingConfigurationTests(SimpleTestCase):
    def test_admin_uses_netxodo_branding(self):
        self.assertEqual(admin.site.site_header, "Netxodo Admin")
        self.assertEqual(admin.site.site_title, "Netxodo")
        self.assertEqual(admin.site.index_title, "Panel de administración")

    def test_generic_error_template_uses_netxodo_branding(self):
        rendered = render_to_string("404.html")

        self.assertIn("Página no encontrada | Netxodo", rendered)
        self.assertNotIn("Sala TPV", rendered)
