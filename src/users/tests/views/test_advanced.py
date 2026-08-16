from django.contrib.auth import get_user_model
from django.contrib.messages import get_messages
from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from app.discover.tab_cache import DISCOVER_TAB_PREFIX
from app.history_cache_utils import HISTORY_DAY_PREFIX, HISTORY_INDEX_PREFIX
from app.models import (
    TV,
    Book,
    DeletedMedia,
    DiscoverRowCache,
    DiscoverTasteProfile,
    Item,
    MediaTypes,
    Movie,
    Sources,
    Status,
)
from app.statistics_cache import STATISTICS_CACHE_PREFIX, STATISTICS_DAY_PREFIX
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


class CacheClearButtonsTests(TestCase):
    """Tests for the per-cache clear buttons in Settings > Advanced."""

    def setUp(self):
        """Create two users so per-user clears can be checked for cross-talk."""
        self.credentials = {"username": "test", "password": "12345"}
        self.user = get_user_model().objects.create_user(**self.credentials)
        self.other_user = get_user_model().objects.create_user(
            username="other",
            password="12345",
        )
        self.client.login(**self.credentials)

    def test_advanced_page_renders_cache_management_buttons_and_overlay(self):
        """The Advanced page should render a button and confirm copy per cache."""
        response = self.client.get(reverse("advanced"))

        self.assertContains(response, "Cache Management")
        for key in ("search", "history", "statistics", "discover", "all"):
            self.assertContains(response, f"openConfirm('{key}')")
        self.assertContains(response, "Clear All Caches")
        # The "clear all" warning is the one place placeholder-value behavior
        # (statistics rebuilds async, unlike the others) needs to be called out.
        self.assertContains(response, "background task")

    def test_advanced_page_renders_media_type_delete_confirmation(self):
        """The Danger Zone should expose a typed confirmation for media deletion."""
        response = self.client.get(reverse("advanced"))

        self.assertContains(response, "Danger Zone")
        self.assertContains(response, "Delete Selected Type")
        self.assertContains(response, "Type <strong>DELETE</strong> to confirm.")
        self.assertContains(response, "bulk_delete_by_media_type")
        self.assertContains(response, 'x-for="option in options"')
        self.assertContains(response, "bg-[var(--color-panel)]")
        self.assertContains(response, "selectedMediaType = option.value")
        self.assertContains(response, "label: 'Movies'")
        self.assertNotContains(response, "label: 'Episode'")

    def test_delete_media_type_only_deletes_current_users_rows_and_clears_caches(self):
        """Deleting a type removes all of this user's rows and leaves others alone."""
        mine_item = Item.objects.create(
            media_id="mine-movie",
            source=Sources.TMDB.value,
            media_type=MediaTypes.MOVIE.value,
            title="Mine",
        )
        mine_movie = Movie.objects.create(
            item=mine_item,
            user=self.user,
            status=Status.PLANNING.value,
        )
        other_item = Item.objects.create(
            media_id="other-movie",
            source=Sources.TMDB.value,
            media_type=MediaTypes.MOVIE.value,
            title="Other",
        )
        other_movie = Movie.objects.create(
            item=other_item,
            user=self.other_user,
            status=Status.PLANNING.value,
        )
        book_item = Item.objects.create(
            media_id="mine-book",
            source=Sources.OPENLIBRARY.value,
            media_type=MediaTypes.BOOK.value,
            title="Mine Book",
        )
        Book.objects.create(
            item=book_item,
            user=self.user,
            status=Status.PLANNING.value,
        )

        history_key = f"{HISTORY_DAY_PREFIX}_{self.user.id}_repeats_20260805"
        stats_key = f"{STATISTICS_CACHE_PREFIX}_{self.user.id}_all_time"
        cache.set(history_key, {"entries": []}, None)
        cache.set(stats_key, {"total": 1}, None)

        response = self.client.post(
            reverse("bulk_delete_by_media_type"),
            {"media_type": MediaTypes.MOVIE.value},
        )

        self.assertRedirects(response, reverse("advanced"))
        self.assertFalse(Movie.objects.filter(id=mine_movie.id).exists())
        self.assertTrue(Movie.objects.filter(id=other_movie.id).exists())
        self.assertTrue(
            Book.objects.filter(user=self.user, item=book_item).exists(),
        )
        self.assertTrue(
            DeletedMedia.objects.filter(
                user=self.user,
                media_type=MediaTypes.MOVIE.value,
                media_id="mine-movie",
            ).exists(),
        )
        self.assertIsNone(cache.get(history_key))
        self.assertIsNone(cache.get(stats_key))

        messages = list(get_messages(response.wsgi_request))
        self.assertIn("Permanently deleted 1 Movie item", str(messages[0]))

    def test_delete_media_type_rejects_episode_and_unknown_types(self):
        """Derived Episodes and arbitrary values cannot reach apps.get_model."""
        for media_type in (MediaTypes.EPISODE.value, "not-a-real-type"):
            response = self.client.post(
                reverse("bulk_delete_by_media_type"),
                {"media_type": media_type},
            )

            self.assertRedirects(response, reverse("advanced"))
            messages = list(get_messages(response.wsgi_request))
            self.assertIn("Unknown media type", str(messages[-1]))

    def test_delete_anime_respects_grouped_library_rows(self):
        """Anime deletion includes grouped TV rows but TV deletion does not."""
        grouped_anime_item = Item.objects.create(
            media_id="grouped-anime",
            source=Sources.TVDB.value,
            media_type=MediaTypes.TV.value,
            library_media_type=MediaTypes.ANIME.value,
            title="Grouped Anime",
        )
        grouped_anime = TV.objects.create(
            item=grouped_anime_item,
            user=self.user,
            status=Status.PLANNING.value,
        )
        regular_tv_item = Item.objects.create(
            media_id="regular-tv",
            source=Sources.TVDB.value,
            media_type=MediaTypes.TV.value,
            library_media_type=MediaTypes.TV.value,
            title="Regular TV",
        )
        regular_tv = TV.objects.create(
            item=regular_tv_item,
            user=self.user,
            status=Status.PLANNING.value,
        )

        response = self.client.post(
            reverse("bulk_delete_by_media_type"),
            {"media_type": MediaTypes.TV.value},
        )

        self.assertRedirects(response, reverse("advanced"))
        self.assertFalse(TV.objects.filter(id=regular_tv.id).exists())
        self.assertTrue(TV.objects.filter(id=grouped_anime.id).exists())

        response = self.client.post(
            reverse("bulk_delete_by_media_type"),
            {"media_type": MediaTypes.ANIME.value},
        )

        self.assertRedirects(response, reverse("advanced"))
        self.assertFalse(TV.objects.filter(id=grouped_anime.id).exists())

    def test_clear_history_cache_only_clears_current_user(self):
        """Clearing history cache must not touch another user's cached days."""
        mine = f"{HISTORY_DAY_PREFIX}_{self.user.id}_repeats_20260805"
        mine_index = f"{HISTORY_INDEX_PREFIX}_{self.user.id}_repeats"
        theirs = f"{HISTORY_DAY_PREFIX}_{self.other_user.id}_repeats_20260805"
        cache.set(mine, {"entries": ["eden"]}, None)
        cache.set(mine_index, {"days": ["20260805"]}, None)
        cache.set(theirs, {"entries": ["unaffected"]}, None)

        response = self.client.post(reverse("clear_history_cache"))

        self.assertRedirects(response, reverse("advanced"))
        self.assertIsNone(cache.get(mine))
        self.assertIsNone(cache.get(mine_index))
        self.assertIsNotNone(cache.get(theirs))

        messages = list(get_messages(response.wsgi_request))
        self.assertEqual(len(messages), 1)
        self.assertIn("history cache entr", str(messages[0]))

    def test_clear_statistics_cache_clears_page_and_day_keys_for_current_user(self):
        """Clearing statistics cache must clear both the page and day payloads."""
        page_key = f"{STATISTICS_CACHE_PREFIX}_{self.user.id}_all_time"
        day_key = f"{STATISTICS_DAY_PREFIX}:{self.user.id}:2026-08-05"
        other_page_key = f"{STATISTICS_CACHE_PREFIX}_{self.other_user.id}_all_time"
        cache.set(page_key, {"total": 1}, None)
        cache.set(day_key, {"total": 1}, None)
        cache.set(other_page_key, {"total": 1}, None)

        response = self.client.post(reverse("clear_statistics_cache"))

        self.assertRedirects(response, reverse("advanced"))
        self.assertIsNone(cache.get(page_key))
        self.assertIsNone(cache.get(day_key))
        self.assertIsNotNone(cache.get(other_page_key))

    def test_clear_discover_cache_deletes_rows_profile_and_tab_cache(self):
        """Clearing discover cache must clear DB rows, profile, and warm-tab keys."""
        DiscoverRowCache.objects.create(
            user=self.user,
            media_type="all",
            row_key="trending",
            payload={"items": []},
            expires_at=timezone.now(),
        )
        DiscoverTasteProfile.objects.create(
            user=self.user,
            media_type="all",
            expires_at=timezone.now(),
        )
        other_row = DiscoverRowCache.objects.create(
            user=self.other_user,
            media_type="all",
            row_key="trending",
            payload={"items": []},
            expires_at=timezone.now(),
        )
        tab_key = f"{DISCOVER_TAB_PREFIX}_{self.user.id}_all_False"
        cache.set(tab_key, {"rows": []}, None)

        response = self.client.post(reverse("clear_discover_cache"))

        self.assertRedirects(response, reverse("advanced"))
        self.assertFalse(DiscoverRowCache.objects.filter(user=self.user).exists())
        self.assertFalse(
            DiscoverTasteProfile.objects.filter(user=self.user).exists(),
        )
        self.assertIsNone(cache.get(tab_key))
        # Another user's row must survive.
        self.assertTrue(DiscoverRowCache.objects.filter(id=other_row.id).exists())

    def test_clear_all_caches_clears_search_and_current_users_own_caches(self):
        """Clear All must sweep search plus this user's history/stats/discover."""
        cache.set("search_tmdb_movie_batman_1", {"results": []}, None)
        history_key = f"{HISTORY_DAY_PREFIX}_{self.user.id}_repeats_20260805"
        stats_key = f"{STATISTICS_CACHE_PREFIX}_{self.user.id}_all_time"
        cache.set(history_key, {"entries": []}, None)
        cache.set(stats_key, {"total": 1}, None)
        DiscoverTasteProfile.objects.create(
            user=self.user,
            media_type="all",
            expires_at=timezone.now(),
        )

        response = self.client.post(reverse("clear_all_caches"))

        self.assertRedirects(response, reverse("advanced"))
        self.assertIsNone(cache.get("search_tmdb_movie_batman_1"))
        self.assertIsNone(cache.get(history_key))
        self.assertIsNone(cache.get(stats_key))
        self.assertFalse(
            DiscoverTasteProfile.objects.filter(user=self.user).exists(),
        )

        messages = list(get_messages(response.wsgi_request))
        self.assertEqual(len(messages), 1)
        self.assertIn("search, history, statistics, and discover", str(messages[0]))

    def test_cache_clear_views_require_post(self):
        """GET requests to any clear-cache endpoint must be rejected."""
        for url_name in (
            "clear_history_cache",
            "clear_statistics_cache",
            "clear_discover_cache",
            "clear_all_caches",
        ):
            response = self.client.get(reverse(url_name))
            self.assertEqual(response.status_code, 405)
