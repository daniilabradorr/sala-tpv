"""Browser media gate.

Media-specific browser coverage shares the production-like live server harness;
backend lifecycle and validation edge cases live in ``apps.core.tests``.
"""

from django.test import SimpleTestCase

from apps.core.media.naming import asset_keys


class BrowserMediaConfigurationTests(SimpleTestCase):
    """Keep the explicit CI entry point and assert immutable URL foundations."""

    def test_asset_urls_are_versioned(self):
        first = asset_keys(business_id=1, entity_kind="products", entity_id=1)
        second = asset_keys(business_id=1, entity_kind="products", entity_id=1)
        self.assertNotEqual(first["master"], second["master"])
