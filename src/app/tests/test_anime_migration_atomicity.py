from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from unittest import skipUnless
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.db import close_old_connections, connection
from django.db.utils import OperationalError
from django.test import TransactionTestCase
from django.utils import timezone

from app.models import (
    TV,
    Anime,
    Episode,
    Item,
    ItemProviderLink,
    MediaTypes,
    MetadataProviderPreference,
    Season,
    Sources,
    Status,
)
from app.services import anime_migration


class AnimeMigrationAtomicityTests(TransactionTestCase):
    reset_sequences = True

    def setUp(self):
        self.user = get_user_model().objects.create_user(username="atomic-migrate")
        self.flat_item = Item.objects.create(
            media_id="52991",
            source=Sources.MAL.value,
            media_type=MediaTypes.ANIME.value,
            title="Frieren",
            image="https://example.com/frieren.jpg",
        )
        self.flat_entry = Anime.objects.create(
            item=self.flat_item,
            user=self.user,
            status=Status.IN_PROGRESS.value,
            progress=2,
            score=9,
            notes="Great adaptation",
            start_date=timezone.now(),
            end_date=timezone.now(),
        )
        self.grouped_item = Item.objects.create(
            media_id="9350138",
            source=Sources.TVDB.value,
            media_type=MediaTypes.TV.value,
            library_media_type=MediaTypes.ANIME.value,
            title="Frieren: Beyond Journey's End",
            image="https://example.com/grouped.jpg",
        )
        self.mapping = {
            "mal_id": "52991",
            "tvdb_id": "9350138",
            "tvdb_season": 1,
            "tvdb_epoffset": 0,
        }
        self.provider_patches = (
            patch(
                "app.services.anime_migration.anime_mapping.resolve_provider_series_id",
                return_value="9350138",
            ),
            patch(
                "app.services.anime_migration.anime_mapping.find_entries_for_mal_id",
                return_value=[self.mapping],
            ),
            patch(
                "app.services.anime_migration.services.get_media_metadata",
                side_effect=self._metadata,
            ),
        )
        for provider_patch in self.provider_patches:
            provider_patch.start()
            self.addCleanup(provider_patch.stop)

    def _metadata(self, media_type, *_args, **_kwargs):
        episodes = [
            {"episode_number": 1, "air_date": "2023-09-29", "runtime": 24},
            {"episode_number": 2, "air_date": "2023-10-06", "runtime": 24},
            {"episode_number": 3, "air_date": "2023-10-13", "runtime": 24},
        ]
        if media_type == MediaTypes.ANIME.value:
            return {
                "title": "Frieren: Beyond Journey's End",
                "image": "https://example.com/grouped.jpg",
                "related": {"seasons": [{"season_number": 1}]},
            }
        if media_type == "tv_with_seasons":
            return {
                "related": {"seasons": [{"season_number": 1}]},
                "season/1": {
                    "title": "Frieren: Beyond Journey's End",
                    "image": "https://example.com/season1.jpg",
                    "season_number": 1,
                    "episodes": episodes,
                },
            }
        raise AssertionError(f"Unexpected provider request: {media_type}")

    def _preflight(self):
        return anime_migration.preflight_flat_anime_to_grouped(
            self.user,
            self.flat_item,
            Sources.TVDB.value,
        )

    def _table_snapshot(self):
        return {
            "items": list(Item.objects.order_by("id").values()),
            "tv": list(TV.objects.order_by("id").values()),
            "seasons": list(Season.objects.order_by("id").values()),
            "episodes": list(Episode.objects.order_by("id").values()),
            "links": list(ItemProviderLink.objects.order_by("id").values()),
            "preferences": list(
                MetadataProviderPreference.objects.order_by("id").values()
            ),
            "anime": list(Anime.all_objects.order_by("id").values()),
            "historical_tv": list(TV.history.order_by("history_id").values()),
            "historical_seasons": list(
                Season.history.order_by("history_id").values()
            ),
            "historical_episodes": list(
                Episode.history.order_by("history_id").values()
            ),
        }

    def test_preflight_is_immutable_and_does_not_write_tables(self):
        before = self._table_snapshot()

        preflight = self._preflight()

        self.assertEqual(preflight.state, anime_migration.AnimeMigrationState.READY)
        self.assertEqual(self._table_snapshot(), before)
        with self.assertRaises(TypeError):
            preflight.series_metadata["title"] = "Changed"
        with self.assertRaises(TypeError):
            preflight.entries[0].season_metadata["episodes"] = []

    def test_persistence_makes_no_provider_or_episode_save_call(self):
        preflight = self._preflight()

        with (
            patch(
                "app.services.anime_migration.services.get_media_metadata",
                side_effect=AssertionError("provider call inside persistence"),
            ),
            patch(
                "app.services.anime_migration.providers.tmdb.get_tvdb_episode_image_map",
                side_effect=AssertionError("provider call inside persistence"),
            ),
            patch(
                "app.services.anime_migration.anime_mapping.resolve_provider_series_id",
                side_effect=AssertionError("mapping call inside persistence"),
            ),
            patch(
                "app.services.anime_migration.anime_mapping.find_entries_for_mal_id",
                side_effect=AssertionError("mapping call inside persistence"),
            ),
            patch.object(
                Episode,
                "save",
                side_effect=AssertionError("Episode.save inside persistence"),
            ),
            patch.object(
                anime_migration.signals,
                "_invalidate_episode_history_changes",
            ) as invalidate,
        ):
            result = anime_migration.persist_flat_anime_migration(preflight)

        self.assertEqual(result.grouped_tv.item_id, self.grouped_item.id)
        self.assertEqual(Episode.objects.count(), 2)
        invalidate.assert_called_once()
        self.assertEqual(set(invalidate.call_args.args[0]), {self.user.id})

    def test_late_failure_rolls_back_every_migration_write(self):
        preflight = self._preflight()
        before = self._table_snapshot()

        with (
            patch.object(
                MetadataProviderPreference.objects,
                "update_or_create",
                side_effect=RuntimeError("late failure"),
            ),
            self.assertRaisesRegex(RuntimeError, "late failure"),
        ):
            anime_migration.persist_flat_anime_migration(preflight)

        self.assertEqual(self._table_snapshot(), before)

    def test_retry_after_lock_uses_fresh_transaction(self):
        preflight = self._preflight()
        persist_once = anime_migration._persist_preflight_once
        attempts = 0

        def locked_once(payload):
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                raise OperationalError("database is locked")
            return persist_once(payload)

        with patch.object(
            anime_migration,
            "_persist_preflight_once",
            side_effect=locked_once,
        ):
            result = anime_migration.persist_flat_anime_migration(preflight)

        self.assertEqual(attempts, 2)
        self.assertEqual(result.grouped_tv.item_id, self.grouped_item.id)
        self.assertEqual(Episode.objects.count(), 2)

    def test_completed_retry_is_a_noop(self):
        first = anime_migration.migrate_flat_anime_to_grouped(
            self.user,
            self.flat_item,
            Sources.TVDB.value,
        )
        first_episode_ids = list(Episode.objects.values_list("id", flat=True))

        second = anime_migration.migrate_flat_anime_to_grouped(
            self.user,
            self.flat_item,
            Sources.TVDB.value,
        )

        self.assertEqual(second.grouped_tv.id, first.grouped_tv.id)
        self.assertEqual(
            list(Episode.objects.values_list("id", flat=True)), first_episode_ids
        )
        self.assertEqual(
            anime_migration.preflight_flat_anime_to_grouped(
                self.user,
                self.flat_item,
                Sources.TVDB.value,
            ).state,
            anime_migration.AnimeMigrationState.COMPLETE,
        )

    def test_stale_preflight_aborts_without_mutation(self):
        preflight = self._preflight()
        Anime.all_objects.filter(pk=self.flat_entry.pk).update(progress=1)

        with self.assertRaises(anime_migration.AnimeMigrationError) as raised:
            anime_migration.persist_flat_anime_migration(preflight)

        self.assertEqual(raised.exception.state, anime_migration.AnimeMigrationState.STALE)
        self.assertEqual(raised.exception.code, anime_migration.STALE_CODE)
        self.assertFalse(TV.objects.exists())
        self.assertFalse(Episode.objects.exists())

    def test_inconsistent_marker_is_provably_partial_and_not_repaired(self):
        Anime.all_objects.filter(pk=self.flat_entry.pk).update(
            migrated_to_item=self.grouped_item,
            migrated_at=None,
        )
        before = self._table_snapshot()

        with self.assertRaises(anime_migration.AnimeMigrationError) as raised:
            self._preflight()

        self.assertEqual(
            raised.exception.state,
            anime_migration.AnimeMigrationState.PROVABLY_PARTIAL,
        )
        self.assertEqual(raised.exception.code, anime_migration.PARTIAL_CODE)
        self.assertEqual(self._table_snapshot(), before)

    def test_grouped_rewatches_are_ambiguous_and_preserved(self):
        grouped_tv = TV.objects.create(
            item=self.grouped_item,
            user=self.user,
            status=Status.IN_PROGRESS.value,
        )
        season_item = Item.objects.create(
            media_id="9350138",
            source=Sources.TVDB.value,
            media_type=MediaTypes.SEASON.value,
            library_media_type=MediaTypes.ANIME.value,
            season_number=1,
            title="Frieren",
            image="https://example.com/season.jpg",
        )
        season = Season.objects.create(
            item=season_item,
            user=self.user,
            related_tv=grouped_tv,
            status=Status.IN_PROGRESS.value,
        )
        episode_item = Item.objects.create(
            media_id="9350138",
            source=Sources.TVDB.value,
            media_type=MediaTypes.EPISODE.value,
            library_media_type=MediaTypes.ANIME.value,
            season_number=1,
            episode_number=1,
            title="Episode 1",
            image="https://example.com/episode.jpg",
        )
        Episode.objects.bulk_create(
            [
                Episode(item=episode_item, related_season=season, end_date=timezone.now()),
                Episode(item=episode_item, related_season=season, end_date=timezone.now()),
            ]
        )
        before = self._table_snapshot()

        with self.assertRaises(anime_migration.AnimeMigrationError) as raised:
            self._preflight()

        self.assertEqual(
            raised.exception.state,
            anime_migration.AnimeMigrationState.AMBIGUOUS,
        )
        self.assertEqual(raised.exception.code, anime_migration.AMBIGUOUS_CODE)
        self.assertEqual(self._table_snapshot(), before)

    def _concurrent_submit(self, preflight):
        barrier = Barrier(2)

        def migrate():
            close_old_connections()
            try:
                barrier.wait(timeout=5)
                return anime_migration.persist_flat_anime_migration(preflight)
            finally:
                close_old_connections()

        with (
            patch.object(
                signals := anime_migration.signals,
                "_invalidate_episode_history_changes",
            ),
            ThreadPoolExecutor(max_workers=2) as executor,
        ):
            results = list(executor.map(lambda _index: migrate(), range(2)))
        self.assertIsNotNone(signals)
        return results

    @skipUnless(connection.vendor == "sqlite", "SQLite concurrency coverage")
    def test_sqlite_double_submit_returns_one_completed_migration(self):
        results = self._concurrent_submit(self._preflight())

        self.assertEqual(
            {result.grouped_tv.id for result in results},
            {results[0].grouped_tv.id},
        )
        self.assertEqual(TV.objects.count(), 1)
        self.assertEqual(Episode.objects.count(), 2)

    @skipUnless(connection.vendor == "postgresql", "PostgreSQL locking coverage")
    def test_postgresql_double_submit_waits_on_source_row_lock(self):
        results = self._concurrent_submit(self._preflight())

        self.assertEqual(
            {result.grouped_tv.id for result in results},
            {results[0].grouped_tv.id},
        )
        self.assertEqual(TV.objects.count(), 1)
        self.assertEqual(Episode.objects.count(), 2)
