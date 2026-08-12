from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from app.models import (
    TV,
    Episode,
    Item,
    MediaTypes,
    Season,
    Sources,
    Status,
)
from app.providers.services import ProviderAPIError
from events.models import Event

mock_path = Path(__file__).resolve().parent.parent / "mock_data"


class EpisodeModel(TestCase):
    """Test the custom save of the Episode model."""

    def setUp(self):
        """Create a user and a season."""
        credits_patcher = patch("app.signals._schedule_credits_backfill_if_needed")
        credits_patcher.start()
        self.addCleanup(credits_patcher.stop)
        self.credentials = {"username": "test", "password": "12345"}
        self.user = get_user_model().objects.create_user(**self.credentials)

        item_season = Item.objects.create(
            media_id="1668",
            source=Sources.TMDB.value,
            media_type=MediaTypes.SEASON.value,
            title="Friends",
            image="http://example.com/image.jpg",
            season_number=1,
        )

        tv_item = Item.objects.create(
            media_id="1668",
            source=Sources.TMDB.value,
            media_type=MediaTypes.TV.value,
            title="Friends",
            image="http://example.com/image.jpg",
        )
        tv = TV.objects.create(
            item=tv_item,
            user=self.user,
            status=Status.IN_PROGRESS.value,
        )

        self.season = Season.objects.create(
            item=item_season,
            user=self.user,
            related_tv=tv,
            status=Status.IN_PROGRESS.value,
            notes="",
        )

    @patch("app.models.providers.services.get_media_metadata")
    def test_episode_save(self, mock_get_metadata):
        """Test the custom save method of the Episode model."""
        mock_get_metadata.return_value = {
            "season/1": {
                "episodes": [
                    {"episode_number": episode_number}
                    for episode_number in range(1, 25)
                ],
            },
            "related": {
                "seasons": [{"season_number": 1}],
            },
        }

        for i in range(1, 25):
            Event.objects.create(
                item=self.season.item,
                content_number=i,
                datetime=datetime(2023, 5, i, 0, 0, tzinfo=UTC),
            )
            item_episode = Item.objects.create(
                media_id="1668",
                source=Sources.TMDB.value,
                media_type=MediaTypes.EPISODE.value,
                title="Friends",
                image="http://example.com/image.jpg",
                season_number=1,
                episode_number=i,
            )
            Episode.objects.create(
                item=item_episode,
                related_season=self.season,
                end_date=datetime(2023, 6, i, 0, 0, tzinfo=UTC),
            )

        self.assertEqual(self.season.status, Status.COMPLETED.value)


class EpisodeStatusTests(TestCase):
    """Test how Episode model affects Season and TV statuses."""

    def setUp(self):
        """Create test data."""
        credits_patcher = patch("app.signals._schedule_credits_backfill_if_needed")
        credits_patcher.start()
        self.addCleanup(credits_patcher.stop)
        self.credentials = {"username": "test", "password": "12345"}
        self.user = get_user_model().objects.create_user(**self.credentials)

        self.tv_item = Item.objects.create(
            media_id="123",
            source=Sources.TMDB.value,
            media_type=MediaTypes.TV.value,
            title="Test Show",
            image="http://example.com/image.jpg",
        )

        self.tv = TV.objects.create(
            item=self.tv_item,
            user=self.user,
            status=Status.PLANNING.value,
        )

        self.season_item = Item.objects.create(
            media_id="123",
            source=Sources.TMDB.value,
            media_type=MediaTypes.SEASON.value,
            title="Test Show",
            image="http://example.com/image.jpg",
            season_number=1,
        )

        self.season = Season.objects.create(
            item=self.season_item,
            user=self.user,
            related_tv=self.tv,
            status=Status.PLANNING.value,
        )

        self.episode_item = Item.objects.create(
            media_id="123",
            source=Sources.TMDB.value,
            media_type=MediaTypes.EPISODE.value,
            title="Test Episode",
            image="http://example.com/image.jpg",
            season_number=1,
            episode_number=1,
        )

    @patch("app.models.providers.services.get_media_metadata")
    def test_first_episode_sets_season_in_progress(self, mock_get_metadata):
        """Test first episode sets season to IN_PROGRESS."""
        mock_metadata = {
            "season/1": {
                "episodes": [{"episode_number": 1}, {"episode_number": 2}],
            },
            "related": {
                "seasons": [{"season_number": 1}],
            },
        }
        mock_get_metadata.return_value = mock_metadata

        Episode.objects.create(
            item=self.episode_item,
            related_season=self.season,
            end_date=timezone.now(),
        )

        self.season.refresh_from_db()
        self.assertEqual(self.season.status, Status.IN_PROGRESS.value)

        self.tv.refresh_from_db()
        self.assertEqual(self.tv.status, Status.IN_PROGRESS.value)

    @patch("app.models.providers.services.get_media_metadata")
    def test_last_episode_sets_season_completed(self, mock_get_metadata):
        """Test last episode sets season to COMPLETED."""
        mock_metadata = {
            "season/1": {
                "episodes": [{"episode_number": 1}],
            },
            "related": {
                "seasons": [{"season_number": 1}],
            },
        }
        mock_get_metadata.return_value = mock_metadata
        Event.objects.create(
            item=self.season_item,
            content_number=1,
            datetime=timezone.now(),
        )

        Episode.objects.create(
            item=self.episode_item,
            related_season=self.season,
            end_date=timezone.now(),
        )

        self.season.refresh_from_db()
        self.assertEqual(self.season.status, Status.COMPLETED.value)

        self.tv.refresh_from_db()
        self.assertEqual(self.tv.status, Status.COMPLETED.value)

    @patch("app.models.providers.services.get_media_metadata")
    def test_provider_failure_keeps_local_completion(self, mock_get_metadata):
        """A failed next-season lookup must not fail the completed episode save."""
        provider_error = ProviderAPIError(
            "tmdb",
            Exception("boom"),
        )
        provider_error.args = (
            "https://api.example.test/show?api_key=super-secret raw provider failure",
        )
        mock_get_metadata.side_effect = provider_error
        Event.objects.create(
            item=self.season_item,
            content_number=1,
            datetime=timezone.now(),
        )

        with self.assertLogs("app.models.tv", level="WARNING") as captured:
            Episode.objects.create(
                item=self.episode_item,
                related_season=self.season,
                end_date=timezone.now(),
            )

        warning = "\n".join(captured.output)
        self.assertIn(
            "Skipping next-season sync due to missing metadata for 123 S1: "
            "ProviderAPIError",
            warning,
        )
        self.assertNotIn("api_key=", warning)
        self.assertNotIn("super-secret", warning)
        self.assertNotIn("raw provider failure", warning)

        self.assertTrue(
            Episode.objects.filter(
                item=self.episode_item,
                related_season=self.season,
            ).exists(),
        )
        self.season.refresh_from_db()
        self.assertEqual(self.season.status, Status.COMPLETED.value)
        self.tv.refresh_from_db()
        self.assertEqual(self.tv.status, Status.IN_PROGRESS.value)
        mock_get_metadata.assert_called_once_with(
            MediaTypes.TV.value,
            self.tv_item.media_id,
            self.tv_item.source,
        )

    @patch("app.models.providers.services.get_media_metadata")
    def test_completed_season_without_release_evidence_stays_completed(
        self,
        mock_get_metadata,
    ):
        """Missing release evidence must not reopen an explicit completion."""
        Season.objects.filter(pk=self.season.pk).update(
            status=Status.COMPLETED.value,
        )
        TV.objects.filter(pk=self.tv.pk).update(status=Status.COMPLETED.value)
        self.season.refresh_from_db()

        Episode.objects.create(
            item=self.episode_item,
            related_season=self.season,
            end_date=timezone.now(),
        )

        self.season.refresh_from_db()
        self.assertEqual(self.season.status, Status.COMPLETED.value)
        self.tv.refresh_from_db()
        self.assertEqual(self.tv.status, Status.COMPLETED.value)
        mock_get_metadata.assert_not_called()

    @patch("app.models.providers.services.get_media_metadata")
    def test_completion_discovers_untracked_next_season(self, mock_get_metadata):
        """Completion still discovers and starts a provider-only next season."""
        mock_get_metadata.return_value = {
            "related": {
                "seasons": [
                    {"season_number": 1},
                    {"season_number": 2, "image": "https://example.com/s2.jpg"},
                ],
            },
        }
        Event.objects.create(
            item=self.season_item,
            content_number=1,
            datetime=timezone.now(),
        )

        Episode.objects.create(
            item=self.episode_item,
            related_season=self.season,
            end_date=timezone.now(),
        )

        next_season = Season.objects.get(
            related_tv=self.tv,
            item__season_number=2,
        )
        self.assertEqual(next_season.status, Status.IN_PROGRESS.value)
        self.tv.refresh_from_db()
        self.assertEqual(self.tv.status, Status.IN_PROGRESS.value)
        mock_get_metadata.assert_called_once_with(
            MediaTypes.TV.value,
            self.tv_item.media_id,
            self.tv_item.source,
        )

    @patch("app.models.providers.services.get_media_metadata")
    def test_middle_episode_does_not_change_status(self, mock_get_metadata):
        """Test middle episode doesn't change season/TV status."""
        mock_metadata = {
            "season/1": {
                "episodes": [
                    {"episode_number": 1},
                    {"episode_number": 2},
                    {"episode_number": 3},
                ],
            },
            "related": {
                "seasons": [{"season_number": 1}, {"season_number": 2}],
            },
        }
        mock_get_metadata.return_value = mock_metadata

        Episode.objects.create(
            item=self.episode_item,
            related_season=self.season,
            end_date=timezone.now(),
        )

        ep_item2 = Item.objects.create(
            media_id="123",
            source=Sources.TMDB.value,
            media_type=MediaTypes.EPISODE.value,
            title="Test Episode 2",
            image="http://example.com/image.jpg",
            season_number=1,
            episode_number=2,
        )

        with patch("app.models.tv.bulk_update_with_history") as mock_bulk_update:
            Episode.objects.create(
                item=ep_item2,
                related_season=self.season,
                end_date=timezone.now(),
            )

            mock_bulk_update.assert_not_called()

    @patch("app.models.providers.services.get_media_metadata")
    def test_last_season_completes_tv_show(self, mock_get_metadata):
        """Test last season completion also completes TV show."""
        mock_metadata = {
            "season/1": {
                "episodes": [{"episode_number": 1}],
            },
            "related": {
                "seasons": [{"season_number": 1}],  # Only one season
            },
        }
        mock_get_metadata.return_value = mock_metadata
        Event.objects.create(
            item=self.season_item,
            content_number=1,
            datetime=timezone.now(),
        )

        Episode.objects.create(
            item=self.episode_item,
            related_season=self.season,
            end_date=timezone.now(),
        )

        self.tv.refresh_from_db()
        self.assertEqual(self.tv.status, Status.COMPLETED.value)

    @patch("app.models.providers.services.get_media_metadata")
    def test_non_last_season_starts_next_season(self, mock_get_metadata):
        """Test non-last season completion starts the next season."""
        next_season_item = Item.objects.create(
            media_id="123",
            source=Sources.TMDB.value,
            media_type=MediaTypes.SEASON.value,
            title="Test Show",
            image="http://example.com/image2.jpg",
            season_number=2,
        )
        next_season = Season.objects.create(
            item=next_season_item,
            user=self.user,
            related_tv=self.tv,
            status=Status.PLANNING.value,
        )

        mock_metadata = {
            "season/1": {
                "episodes": [{"episode_number": 1}],
            },
            "related": {
                "seasons": [{"season_number": 1}, {"season_number": 2}],
            },
        }
        mock_get_metadata.return_value = mock_metadata
        Event.objects.create(
            item=self.season_item,
            content_number=1,
            datetime=timezone.now(),
        )

        Episode.objects.create(
            item=self.episode_item,
            related_season=self.season,
            end_date=timezone.now(),
        )

        next_season.refresh_from_db()
        self.assertEqual(next_season.status, Status.IN_PROGRESS.value)

        self.tv.refresh_from_db()
        self.assertEqual(self.tv.status, Status.IN_PROGRESS.value)

    @patch("app.models.providers.services.get_media_metadata")
    def test_new_release_advances_stale_completed_season(self, mock_get_metadata):
        """Finishing a newly released episode must start the next season."""
        next_season_item = Item.objects.create(
            media_id="123",
            source=Sources.TMDB.value,
            media_type=MediaTypes.SEASON.value,
            title="Test Show",
            image="http://example.com/image2.jpg",
            season_number=2,
        )
        next_season = Season.objects.create(
            item=next_season_item,
            user=self.user,
            related_tv=self.tv,
            status=Status.PLANNING.value,
        )
        second_episode_item = Item.objects.create(
            media_id="123",
            source=Sources.TMDB.value,
            media_type=MediaTypes.EPISODE.value,
            title="Test Episode 2",
            season_number=1,
            episode_number=2,
        )
        Event.objects.bulk_create(
            [
                Event(
                    item=self.season_item,
                    content_number=episode_number,
                    datetime=timezone.now(),
                )
                for episode_number in (1, 2)
            ],
        )
        Episode.objects.bulk_create(
            [
                Episode(
                    item=self.episode_item,
                    related_season=self.season,
                    end_date=timezone.now(),
                ),
            ],
        )
        Season.objects.filter(pk=self.season.pk).update(
            status=Status.COMPLETED.value,
        )
        TV.objects.filter(pk=self.tv.pk).update(status=Status.COMPLETED.value)
        self.season.refresh_from_db()

        Episode.objects.create(
            item=second_episode_item,
            related_season=self.season,
            end_date=timezone.now(),
        )

        next_season.refresh_from_db()
        self.assertEqual(next_season.status, Status.IN_PROGRESS.value)
        mock_get_metadata.assert_not_called()

    @patch("app.models.providers.services.get_media_metadata")
    def test_earlier_episode_after_finale_keeps_completed_season_completed(
        self,
        mock_get_metadata,
    ):
        """Adding earlier episodes after the finale should not reopen the season."""
        mock_get_metadata.return_value = {
            "season/1": {
                "episodes": [
                    {"episode_number": 1},
                    {"episode_number": 2},
                    {"episode_number": 3},
                ],
            },
            "related": {
                "seasons": [{"season_number": 1}],
            },
        }
        for episode_number in range(1, 4):
            Event.objects.create(
                item=self.season_item,
                content_number=episode_number,
                datetime=timezone.now(),
            )

        final_episode_item = Item.objects.create(
            media_id="123",
            source=Sources.TMDB.value,
            media_type=MediaTypes.EPISODE.value,
            title="Test Episode 3",
            image="http://example.com/image.jpg",
            season_number=1,
            episode_number=3,
        )
        second_episode_item = Item.objects.create(
            media_id="123",
            source=Sources.TMDB.value,
            media_type=MediaTypes.EPISODE.value,
            title="Test Episode 2",
            image="http://example.com/image.jpg",
            season_number=1,
            episode_number=2,
        )

        Episode.objects.create(
            item=final_episode_item,
            related_season=self.season,
            end_date=timezone.now(),
        )
        self.season.refresh_from_db()
        self.assertEqual(self.season.status, Status.IN_PROGRESS.value)

        Episode.objects.create(
            item=self.episode_item,
            related_season=self.season,
            end_date=timezone.now(),
        )
        Episode.objects.create(
            item=second_episode_item,
            related_season=self.season,
            end_date=timezone.now(),
        )

        self.season.refresh_from_db()
        self.assertEqual(self.season.status, Status.COMPLETED.value)

        self.tv.refresh_from_db()
        self.assertEqual(self.tv.status, Status.COMPLETED.value)

    @patch("app.models.providers.services.get_media_metadata")
    def test_duplicate_rewatch_keeps_manual_in_progress_status(
        self,
        mock_get_metadata,
    ):
        """A duplicate play must not end a manually started rewatch."""
        mock_get_metadata.return_value = {
            "related": {"seasons": [{"season_number": 1}]},
        }
        Event.objects.create(
            item=self.season_item,
            content_number=1,
            datetime=timezone.now(),
        )
        Episode.objects.create(
            item=self.episode_item,
            related_season=self.season,
            end_date=timezone.now(),
        )
        Season.objects.filter(pk=self.season.pk).update(
            status=Status.IN_PROGRESS.value,
        )

        Episode.objects.create(
            item=self.episode_item,
            related_season=self.season,
            end_date=timezone.now(),
        )

        self.season.refresh_from_db()
        self.assertEqual(self.season.status, Status.IN_PROGRESS.value)
