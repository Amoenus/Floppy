from unittest.mock import patch

from django.test import TestCase

from api.serializers import ItemSerializer
from app.models import Item, ItemProviderLink, MediaTypes, Sources
from app.services import mal_ratings


class MalRatingSyncTests(TestCase):
    def test_item_serializer_includes_persisted_mal_fields(self):
        item = Item.objects.create(
            media_id="8",
            source=Sources.MAL.value,
            media_type=MediaTypes.ANIME.value,
            title="Serialized Anime",
            mal_rating=8.4,
            mal_rating_count=321,
        )

        serialized = ItemSerializer(item).data

        self.assertEqual(serialized["mal_rating"], 8.4)
        self.assertEqual(serialized["mal_rating_count"], 321)

    def test_flat_mal_anime_uses_its_media_id(self):
        item = Item.objects.create(
            media_id="9",
            source=Sources.MAL.value,
            media_type=MediaTypes.ANIME.value,
            title="Flat Anime",
            provider_external_ids={"mal_id": "10"},
        )

        self.assertEqual(mal_ratings.resolve_mal_id(item), "9")

    def test_sync_deduplicates_exact_ids_and_skips_ambiguous_mappings(self):
        first = Item.objects.create(
            media_id="1",
            source=Sources.MAL.value,
            media_type=MediaTypes.ANIME.value,
            title="Flat Anime 1",
        )
        second = Item.objects.create(
            media_id="tv-0",
            source=Sources.TVDB.value,
            media_type=MediaTypes.TV.value,
            library_media_type=MediaTypes.ANIME.value,
            title="Flat Anime 2",
            provider_external_ids={"mal_id": "1"},
        )
        grouped = Item.objects.create(
            media_id="tv-1",
            source=Sources.TVDB.value,
            media_type=MediaTypes.TV.value,
            library_media_type=MediaTypes.ANIME.value,
            title="Grouped Anime",
            provider_external_ids={"mal_id": "2"},
        )
        ambiguous = Item.objects.create(
            media_id="tv-2",
            source=Sources.TVDB.value,
            media_type=MediaTypes.TV.value,
            library_media_type=MediaTypes.ANIME.value,
            title="Ambiguous Anime",
            provider_external_ids={"mal_id": "3"},
        )
        ItemProviderLink.objects.create(
            item=ambiguous,
            provider=Sources.MAL.value,
            provider_media_type=MediaTypes.TV.value,
            provider_media_id="4",
        )
        Item.objects.create(
            media_id="tv-3",
            source=Sources.TVDB.value,
            media_type=MediaTypes.TV.value,
            title="Non Anime Show",
            provider_external_ids={"mal_id": "5"},
        )

        with patch(
            "app.services.mal_ratings.mal_provider.rating",
            side_effect={"1": (9.1, 100), "2": (8.2, 200)}.__getitem__,
        ) as mock_rating:
            updated = mal_ratings.sync_mal_ratings()

        self.assertEqual(updated, 3)
        mock_rating.assert_any_call("1")
        mock_rating.assert_any_call("2")
        self.assertEqual(mock_rating.call_count, 2)

        first.refresh_from_db()
        second.refresh_from_db()
        grouped.refresh_from_db()
        ambiguous.refresh_from_db()
        self.assertEqual((first.mal_rating, first.mal_rating_count), (9.1, 100))
        self.assertEqual((second.mal_rating, second.mal_rating_count), (9.1, 100))
        self.assertEqual((grouped.mal_rating, grouped.mal_rating_count), (8.2, 200))
        self.assertIsNone(ambiguous.mal_rating)
        self.assertIsNone(ambiguous.mal_rating_count)

    def test_provider_failure_preserves_last_successful_rating(self):
        item = Item.objects.create(
            media_id="6",
            source=Sources.MAL.value,
            media_type=MediaTypes.ANIME.value,
            title="Anime With Existing Rating",
            mal_rating=7.2,
            mal_rating_count=50,
        )

        with patch(
            "app.services.mal_ratings.mal_provider.rating",
            side_effect=RuntimeError("temporary outage"),
        ):
            self.assertEqual(mal_ratings.sync_mal_ratings(), 0)

        item.refresh_from_db()
        self.assertEqual((item.mal_rating, item.mal_rating_count), (7.2, 50))

    def test_successful_unrated_response_clears_previous_rating(self):
        item = Item.objects.create(
            media_id="7",
            source=Sources.MAL.value,
            media_type=MediaTypes.ANIME.value,
            title="Previously Rated Anime",
            mal_rating=7.2,
            mal_rating_count=50,
        )

        with patch(
            "app.services.mal_ratings.mal_provider.rating",
            return_value=None,
        ):
            self.assertEqual(mal_ratings.sync_mal_ratings(), 1)

        item.refresh_from_db()
        self.assertIsNone(item.mal_rating)
        self.assertIsNone(item.mal_rating_count)
