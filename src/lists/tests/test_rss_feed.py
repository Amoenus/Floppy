import xml.etree.ElementTree as ET
from datetime import UTC, datetime
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from app.models import Item, MediaTypes, Sources
from lists.feeds import PublicListFeed
from lists.models import CustomList, CustomListItem


class PublicListRssContractTests(TestCase):
    """Cover RSS titles, identity, query growth, and offline operation."""

    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="rss-contract-user",
            password="testpassword",
        )
        self.custom_list = CustomList.objects.create(
            name="RSS Contract",
            description="RSS contract regression tests",
            owner=self.user,
            visibility="public",
        )

    def _create_list_item(self, **item_fields):
        item = Item.objects.create(**item_fields)
        CustomListItem.objects.create(custom_list=self.custom_list, item=item)
        return item

    def _feed_items(self):
        response = self.client.get(
            reverse("list_rss", args=[self.custom_list.id]),
        )
        self.assertEqual(response.status_code, 200)
        root = ET.fromstring(response.content)
        return root.findall("./channel/item")

    def test_movie_title_includes_year(self):
        """A movie title includes its stored release year for matching."""
        self._create_list_item(
            media_id="movie-with-year",
            source=Sources.TMDB.value,
            media_type=MediaTypes.MOVIE.value,
            title="RSS Feed Movie",
            release_datetime=datetime(2024, 5, 1, tzinfo=UTC),
        )

        titles = [item.findtext("title") for item in self._feed_items()]

        self.assertEqual(titles, ["RSS Feed Movie (2024)"])

    def test_grouped_anime_uses_matching_library_parent(self):
        """A grouped anime episode uses the title from its library parent."""
        Item.objects.create(
            media_id="grouped-anime",
            source=Sources.TMDB.value,
            media_type=MediaTypes.TV.value,
            library_media_type=MediaTypes.ANIME.value,
            title="Anime Library Title",
        )
        Item.objects.create(
            media_id="grouped-anime",
            source=Sources.TMDB.value,
            media_type=MediaTypes.ANIME.value,
            title="Anime Model Title",
        )
        Item.objects.create(
            media_id="grouped-anime",
            source=Sources.TMDB.value,
            media_type=MediaTypes.TV.value,
            library_media_type=MediaTypes.TV.value,
            title="TV Library Title",
        )
        self._create_list_item(
            media_id="grouped-anime",
            source=Sources.TMDB.value,
            media_type=MediaTypes.EPISODE.value,
            library_media_type=MediaTypes.ANIME.value,
            title="Episode Name",
            season_number=1,
            episode_number=3,
        )

        titles = [item.findtext("title") for item in self._feed_items()]

        self.assertEqual(titles, ["Anime Library Title S01E03"])

    def test_tv_episode_uses_matching_legacy_tv_parent(self):
        """A normal TV episode does not select an anime-library parent."""
        Item.objects.create(
            media_id="tv-with-anime-variant",
            source=Sources.TMDB.value,
            media_type=MediaTypes.TV.value,
            library_media_type=MediaTypes.ANIME.value,
            title="Anime Variant Title",
        )
        Item.objects.create(
            media_id="tv-with-anime-variant",
            source=Sources.TMDB.value,
            media_type=MediaTypes.TV.value,
            title="TV Variant Title",
        )
        self._create_list_item(
            media_id="tv-with-anime-variant",
            source=Sources.TMDB.value,
            media_type=MediaTypes.EPISODE.value,
            title="Episode Name",
            season_number=1,
            episode_number=4,
        )

        titles = [item.findtext("title") for item in self._feed_items()]

        self.assertEqual(titles, ["TV Variant Title S01E04"])

    def test_series_name_is_used_when_parent_is_not_stored(self):
        """An orphan episode remains matchable from its stored series name."""
        self._create_list_item(
            media_id="orphan-episode",
            source=Sources.TMDB.value,
            media_type=MediaTypes.EPISODE.value,
            title="Pilot",
            series_name="Orphan Series",
            season_number=1,
            episode_number=1,
        )

        titles = [item.findtext("title") for item in self._feed_items()]

        self.assertEqual(titles, ["Orphan Series S01E01"])

    def test_season_uses_stored_parent_title(self):
        """A season entry uses its parent title and season marker."""
        Item.objects.create(
            media_id="season-show",
            source=Sources.TMDB.value,
            media_type=MediaTypes.TV.value,
            title="Season Show",
        )
        self._create_list_item(
            media_id="season-show",
            source=Sources.TMDB.value,
            media_type=MediaTypes.SEASON.value,
            title="Season One",
            season_number=1,
       )

        titles = [item.findtext("title") for item in self._feed_items()]

        self.assertEqual(titles, ["Season Show S01"])

    def test_grouped_anime_uses_matching_library_parent(self):
        """A grouped anime episode uses the title from its library parent."""
        Item.objects.create(
            media_id="grouped-anime",
            source=Sources.TMDB.value,
            media_type=MediaTypes.TV.value,
            library_media_type=MediaTypes.ANIME.value,
            title="Anime Library Title",
        )
        Item.objects.create(
            media_id="grouped-anime",
            source=Sources.TMDB.value,
            media_type=MediaTypes.ANIME.value,
            title="Anime Model Title",
        )
        Item.objects.create(
            media_id="grouped-anime",
            source=Sources.TMDB.value,
            media_type=MediaTypes.TV.value,
            library_media_type=MediaTypes.TV.value,
            title="TV Library Title",
        )
        self._create_list_item(
            media_id="grouped-anime",
            source=Sources.TMDB.value,
            media_type=MediaTypes.EPISODE.value,
            library_media_type=MediaTypes.ANIME.value,
            title="Episode Name",
            season_number=1,
            episode_number=3,
        )

        titles = [item.findtext("title") for item in self._feed_items()]

        self.assertEqual(titles, ["Anime Library Title S01E03"])

    def test_tv_episode_uses_matching_legacy_tv_parent(self):
        """A normal TV episode does not select an anime-library parent."""
        Item.objects.create(
            media_id="tv-with-anime-variant",
            source=Sources.TMDB.value,
            media_type=MediaTypes.TV.value,
            library_media_type=MediaTypes.ANIME.value,
            title="Anime Variant Title",
        )
        Item.objects.create(
            media_id="tv-with-anime-variant",
            source=Sources.TMDB.value,
            media_type=MediaTypes.TV.value,
            title="TV Variant Title",
        )
        self._create_list_item(
            media_id="tv-with-anime-variant",
            source=Sources.TMDB.value,
            media_type=MediaTypes.EPISODE.value,
            title="Episode Name",
            season_number=1,
            episode_number=4,
        )

        titles = [item.findtext("title") for item in self._feed_items()]

        self.assertEqual(titles, ["TV Variant Title S01E04"])

    def test_series_name_is_used_when_parent_is_not_stored(self):
        """An orphan episode remains matchable from its stored series name."""
        self._create_list_item(
            media_id="orphan-episode",
            source=Sources.TMDB.value,
            media_type=MediaTypes.EPISODE.value,
            title="Pilot",
            series_name="Orphan Series",
            season_number=1,
            episode_number=1,
        )

        titles = [item.findtext("title") for item in self._feed_items()]

        self.assertEqual(titles, ["Orphan Series S01E01"])

    def test_season_uses_stored_parent_title(self):
        """A season entry uses its parent title and season marker."""
        Item.objects.create(
            media_id="season-show",
            source=Sources.TMDB.value,
            media_type=MediaTypes.TV.value,
            title="Season Show",
        )
        self._create_list_item(
            media_id="season-show",
            source=Sources.TMDB.value,
            media_type=MediaTypes.SEASON.value,
            title="Season One",
            season_number=1,
       )

        titles = [item.findtext("title") for item in self._feed_items()]

        self.assertEqual(titles, ["Season Show S01"])

    def test_guid_distinguishes_episode_coordinates(self):
        """Episodes from one show have distinct coordinate-based GUIDs."""
        for episode_number in (1, 2):
            self._create_list_item(
                media_id="episode-guid-show",
                source=Sources.TMDB.value,
                media_type=MediaTypes.EPISODE.value,
                title=f"Episode {episode_number}",
                season_number=1,
                episode_number=episode_number,
            )

        guids = {item.findtext("guid") for item in self._feed_items()}

        self.assertEqual(
            guids,
            {
                "tmdb:episode:episode-guid-show:s1:e1",
                "tmdb:episode:episode-guid-show:s1:e2",
            },
        )

    def test_guid_ignores_external_ids_and_is_not_permalink(self):
        """Mutable external IDs do not affect the non-permalink GUID."""
        self._create_list_item(
            media_id="movie-with-external-id",
            source=Sources.TMDB.value,
            media_type=MediaTypes.MOVIE.value,
            title="Movie With External ID",
            provider_external_ids={"imdb_id": "tt1234567"},
        )

        guid = self._feed_items()[0].find("guid")

        self.assertEqual(guid.text, "tmdb:movie:movie-with-external-id")
        self.assertEqual(guid.get("isPermaLink"), "false")

    def test_guid_distinguishes_library_variants(self):
        """Legacy and explicit library rows have distinct GUIDs."""
        self._create_list_item(
            media_id="shared-show",
            source=Sources.TMDB.value,
            media_type=MediaTypes.TV.value,
            title="Legacy TV Row",
        )
        self._create_list_item(
            media_id="shared-show",
            source=Sources.TMDB.value,
            media_type=MediaTypes.TV.value,
            library_media_type=MediaTypes.TV.value,
            title="TV Library Row",
       )
        self._create_list_item(
            media_id="shared-show",
            source=Sources.TMDB.value,
            media_type=MediaTypes.TV.value,
            library_media_type=MediaTypes.ANIME.value,
            title="Anime Library Row",
        )

        guids = {item.findtext("guid") for item in self._feed_items()}

        self.assertEqual(
            guids,
            {
                "tmdb:tv:shared-show",
                "tmdb:tv:shared-show:library:tv",
                "tmdb:tv:shared-show:library:anime",
            },
        )

    def test_guid_encodes_reserved_identity_characters(self):
        """Reserved characters cannot make GUID components ambiguous."""
        self._create_list_item(
            media_id="custom:item/one",
            source=Sources.MANUAL.value,
            media_type=MediaTypes.MOVIE.value,
            title="Manual Movie",
        )

        guid = self._feed_items()[0].findtext("guid")

        self.assertEqual(guid, "manual:movie:custom%3Aitem%2Fone")

    def test_item_category_reflects_media_type(self):
        """An RSS item exposes its display media type as a category."""
        self._create_list_item(
            media_id="rss-game",
            source=Sources.IGDB.value,
            media_type=MediaTypes.GAME.value,
            title="RSS Game",
        )

        category = self._feed_items()[0].findtext("category")

        self.assertEqual(category, "Game")

    def test_parent_title_lookup_uses_one_query_for_multiple_children(self):
        """Parent lookup query count does not grow with the item count."""
        Item.objects.create(
            media_id="query-show",
            source=Sources.TMDB.value,
            media_type=MediaTypes.TV.value,
            title="Query Show",
       )
        for episode_number in (1, 2):
            self._create_list_item(
                media_id="query-show",
                source=Sources.TMDB.value,
                media_type=MediaTypes.EPISODE.value,
                title=f"Episode {episode_number}",
                season_number=1,
                episode_number=episode_number,
            )
        list_items = list(
            CustomListItem.objects.filter(custom_list=self.custom_list)
            .select_related("item")
            .order_by("pk")
        )

        with self.assertNumQueries(1):
            PublicListFeed()._attach_show_titles(list_items)

        self.assertEqual(
            [item.feed_show_title for item in list_items],
            ["Query Show", "Query Show"],
        )

    def test_owner_status_lookup_batches_for_backend_parameter_limit(self):
        """Large owner-status lookups stay below the parameter limit."""
        for index in (1, 2):
            self._create_list_item(
                media_id=f"batched-movie-{index}",
                source=Sources.TMDB.value,
                media_type=MediaTypes.MOVIE.value,
                title=f"Batched Movie {index}",
            )
        list_items = list(
            CustomListItem.objects.filter(custom_list=self.custom_list)
            .select_related("item")
            .order_by("pk")
        )

        with (
            patch("lists.feeds.connection.features.max_query_params", 9),
            self.assertNumQueries(2),
        ):
            PublicListFeed()._attach_owner_media_statuses(list_items, self.user)

        self.assertEqual(
            [item.feed_status for item in list_items],
            ["", ""],
        )

    def test_parent_title_lookup_batches_for_backend_parameter_limit(self):
        """Large parent lookups stay below the database parameter limit."""
        for index in (1, 2):
            Item.objects.create(
                media_id=f"batched-show-{index}",
                source=Sources.TMDB.value,
                media_type=MediaTypes.TV.value,
                title=f"Batched Show {index}",
            )
            self._create_list_item(
                media_id=f"batched-show-{index}",
                source=Sources.TMDB.value,
                media_type=MediaTypes.EPISODE.value,
                title=f"Batched Episode {index}",
                season_number=1,
                episode_number=1,
            )
        list_items = list(
            CustomListItem.objects.filter(custom_list=self.custom_list)
            .select_related("item")
            .order_by("pk")
        )

        with (
            patch("lists.feeds.connection.features.max_query_params", 9),
            self.assertNumQueries(2),
        ):
            PublicListFeed()._attach_show_titles(list_items)

        self.assertEqual(
            [item.feed_show_title for item in list_items],
            ["Batched Show 1", "Batched Show 2"],
        )

    @patch("lists.feeds.tmdb.tv")
    def test_rss_generation_does_not_call_external_providers(self, tmdb_tv):
        """RSS generation remains usable when providers are offline."""
        self._create_list_item(
            media_id="offline-movie",
            source=Sources.TMDB.value,
            media_type=MediaTypes.MOVIE.value,
            title="Offline Movie",
        )

        items = self._feed_items()

        self.assertEqual(len(items), 1)
        tmdb_tv.assert_not_called()
