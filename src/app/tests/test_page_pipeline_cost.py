"""Fixed per-page costs: what every full page load downloads and blocks on."""

import re

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse


class PagePipelineCostTests(TestCase):
    """Every page's head must stay cheap to load and cache."""

    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user(username="pipeline")

    def setUp(self):
        self.client.force_login(self.user)

    def test_translation_catalog_is_versioned_and_browser_cached(self):
        page = self.client.get(reverse("home")).content.decode()
        match = re.search(r'<script src="(/jsi18n/\?v=[^"]+)">', page)

        self.assertIsNotNone(match, "the catalog URL must carry a version")
        catalog_url = match.group(1).replace("&amp;", "&")
        self.assertIn("&l=", catalog_url)

        response = self.client.get(catalog_url)

        self.assertEqual(response.status_code, 200)
        cache_control = response["Cache-Control"]
        self.assertIn("immutable", cache_control)
        self.assertIn("max-age=31536000", cache_control)

    def test_barcode_library_is_not_loaded_on_every_page(self):
        page = self.client.get(reverse("home")).content.decode()

        self.assertNotIn('<script src="/static/js/libraries/zxing', page)
        self.assertIn("data-zxing-src=", page)
