from pathlib import Path

from django.conf import settings
from django.contrib.staticfiles import finders
from django.template import Context, Template
from django.templatetags.static import static
from django.test import SimpleTestCase


class DesignSystemAssetTests(SimpleTestCase):
    styles = (
        "css/tokens.css",
        "css/components/buttons.css",
        "css/components/forms.css",
        "css/components/cards.css",
        "css/components/badges.css",
        "css/components/tables.css",
        "css/components/tabs.css",
        "css/components/skeleton.css",
    )

    def test_design_system_assets_are_resolvable(self):
        for asset in (*self.styles, "icons/netxodo-ui.svg"):
            with self.subTest(asset=asset):
                self.assertIsNotNone(finders.find(asset))

    def test_base_loads_tokens_before_consumers(self):
        source = Path(settings.BASE_DIR, "templates", "base.html").read_text()
        token_position = source.index("css/tokens.css")

        for stylesheet in ("css/base.css", *self.styles[1:], "css/erp_admin.css"):
            with self.subTest(stylesheet=stylesheet):
                self.assertGreater(source.index(stylesheet), token_position)

    def test_official_brand_values_are_tokens(self):
        tokens = (
            Path(settings.BASE_DIR, "static", "css", "tokens.css").read_text().lower()
        )

        for color in (
            "#020c18",
            "#07182b",
            "#f1b902",
            "#0061c1",
            "#0794f2",
            "#f7f8fa",
            "#9aa7b7",
        ):
            with self.subTest(color=color):
                self.assertIn(color, tokens)

    def test_legacy_unclassed_buttons_are_scoped_to_main_content(self):
        buttons = Path(
            settings.BASE_DIR, "static", "css", "components", "buttons.css"
        ).read_text()

        self.assertIn(
            ".site-main form:not([class]) button:not([class])",
            buttons,
        )
        self.assertIn(
            ".public-main form:not([class]) button:not([class])",
            buttons,
        )
        self.assertNotIn(".sidebar-footer", buttons)

    def test_small_text_on_light_surfaces_uses_accessible_colors(self):
        base = Path(settings.BASE_DIR, "static", "css", "base.css").read_text()
        skip_link = base.split(".skip-link {", 1)[1].split("}", 1)[0]
        skip_link_focus = base.split(".skip-link:focus {", 1)[1].split("}", 1)[0]
        eyebrow = base.split(".eyebrow {", 1)[1].split("}", 1)[0]

        self.assertIn("background: var(--nx-yellow)", skip_link)
        self.assertIn("color: var(--nx-brand-night)", skip_link)
        self.assertNotIn("color: var(--nx-bg)", skip_link)
        self.assertIn("color: var(--nx-brand-night)", skip_link_focus)
        self.assertIn("color: var(--nx-primary)", eyebrow)


class IconComponentTests(SimpleTestCase):
    def test_icon_helper_references_local_sprite_and_is_decorative(self):
        rendered = Template(
            '{% include "components/icon.html" with name="search" %}'
        ).render(Context())
        expected_sprite_url = static("icons/netxodo-ui.svg")

        self.assertIn(f"{expected_sprite_url}#search", rendered)
        self.assertIn("<svg", rendered)
        self.assertIn('aria-hidden="true"', rendered)
        self.assertNotIn("aria-label", rendered)
        self.assertIn('stroke="currentColor"', rendered)
