from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase


class HorizontalScrollContractTests(SimpleTestCase):
    def setUp(self):
        self.root = Path(settings.BASE_DIR)

    def read(self, relative_path):
        return self.root.joinpath(relative_path).read_text(encoding="utf-8")

    def test_shared_rows_enable_accessible_horizontal_drag(self):
        row = self.read("templates/app/components/_scrollable_row.html")

        self.assertIn('data-horizontal-drag="true"', row)
        self.assertIn('tabindex="0"', row)
        self.assertIn('role="region"', row)
        self.assertIn('aria-label="{{ row.title }}"', row)

    def test_base_loads_the_horizontal_drag_controller_once(self):
        base = self.read("templates/base.html")

        script_tag = '<script src="{% static \'js/horizontal-scroll.js\' %}'
        self.assertEqual(base.count(script_tag), 1)

    def test_drag_styles_use_theme_tokens_and_respect_reduced_motion(self):
        css = self.read("static/css/input.css")

        self.assertIn('[data-horizontal-drag="true"]', css)
        self.assertIn("cursor: grab", css)
        self.assertIn("cursor: grabbing", css)
        self.assertIn("var(--color-link)", css)
        self.assertIn("prefers-reduced-motion: reduce", css)
