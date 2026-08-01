from django.contrib.auth import get_user_model
from django.contrib.messages import get_messages
from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse

from integrations.imports.helpers import decrypt


class TmdbProxyUpdateTests(TestCase):
    """Tests for the Advanced settings TMDB proxy field."""

    def setUp(self):
        """Create user for the tests."""
        self.credentials = {"username": "test", "password": "12345"}
        self.user = get_user_model().objects.create_user(**self.credentials)
        self.client.login(**self.credentials)

    def tearDown(self):
        """Avoid leaking the tmdb proxy cache key between tests."""
        cache.delete("tmdb_proxy_url")
        super().tearDown()

    def test_update_tmdb_proxy_saves_encrypted_value(self):
        """Posting a proxy URL should save it encrypted and invalidate the cache."""
        cache.set("tmdb_proxy_url", "stale-value", 60)

        response = self.client.post(
            reverse("update_tmdb_proxy"),
            {"tmdb_proxy_url": "socks5://user:pass@host:1080"},
        )

        self.assertRedirects(response, reverse("advanced"))
        self.user.refresh_from_db()

        self.assertNotEqual(self.user.tmdb_proxy_url, "socks5://user:pass@host:1080")
        self.assertEqual(
            decrypt(self.user.tmdb_proxy_url),
            "socks5://user:pass@host:1080",
        )
        self.assertIsNone(cache.get("tmdb_proxy_url"))

        messages = list(get_messages(response.wsgi_request))
        self.assertEqual(len(messages), 1)
        self.assertIn("updated successfully", str(messages[0]))

    def test_update_tmdb_proxy_blank_clears_value(self):
        """Posting a blank value should clear the stored proxy URL."""
        from integrations.imports.helpers import encrypt

        self.user.tmdb_proxy_url = encrypt("socks5://host:1080")
        self.user.save(update_fields=["tmdb_proxy_url"])

        response = self.client.post(
            reverse("update_tmdb_proxy"),
            {"tmdb_proxy_url": ""},
        )

        self.user.refresh_from_db()
        self.assertEqual(self.user.tmdb_proxy_url, "")

        messages = list(get_messages(response.wsgi_request))
        self.assertEqual(len(messages), 1)
        self.assertIn("removed", str(messages[0]))

    def test_advanced_page_shows_configured_status(self):
        """The advanced page should reflect whether a proxy is configured."""
        response = self.client.get(reverse("advanced"))
        self.assertFalse(response.context["tmdb_proxy_configured"])

        from integrations.imports.helpers import encrypt

        self.user.tmdb_proxy_url = encrypt("socks5://host:1080")
        self.user.save(update_fields=["tmdb_proxy_url"])

        response = self.client.get(reverse("advanced"))
        self.assertTrue(response.context["tmdb_proxy_configured"])
