from datetime import UTC, datetime
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

# Patch the provider lookup used by app.models.tv (imported there as `providers`).
METADATA_PATH = "app.providers.services.get_media_metadata"

SEASON_METADATA = {
    "episodes": [{"episode_number": 1}, {"episode_number": 2}],
    "max_progress": 2,
    "image": "s.jpg",
    # Episode.save() asks for "tv_with_seasons" and reads this key.
    "season/1": {"episodes": [{"episode_number": 1}, {"episode_number": 2}]},
}


@patch(METADATA_PATH, return_value=SEASON_METADATA)
class SeasonRewatch(TestCase):
    """Rewatching a season that has already been watched to the end."""

    def setUp(self):
        """Create a two-episode season with both episodes watched."""
        self.user = get_user_model().objects.create_user(
            username="test",
            password="12345",
        )

        item_tv = Item.objects.create(
            media_id="123",
            source=Sources.TMDB.value,
            media_type=MediaTypes.TV.value,
            title="Show",
        )
        self.tv = TV.objects.create(
            item=item_tv,
            user=self.user,
            status=Status.IN_PROGRESS.value,
        )

        item_season = Item.objects.create(
            media_id="123",
            source=Sources.TMDB.value,
            media_type=MediaTypes.SEASON.value,
            title="Show",
            season_number=1,
        )
        self.season = Season.objects.create(
            item=item_season,
            user=self.user,
            related_tv=self.tv,
            status=Status.IN_PROGRESS.value,
        )

        self.episode_items = []
        for episode_number in (1, 2):
            item = Item.objects.create(
                media_id="123",
                source=Sources.TMDB.value,
                media_type=MediaTypes.EPISODE.value,
                title="Show",
                season_number=1,
                episode_number=episode_number,
            )
            self.episode_items.append(item)
            with patch(METADATA_PATH, return_value=SEASON_METADATA):
                Episode.objects.create(
                    item=item,
                    related_season=self.season,
                    end_date=datetime(2023, 6, episode_number, tzinfo=UTC),
                )

    def _set_status(self, status):
        """Set the season status without going through save() side effects."""
        Season.objects.filter(pk=self.season.pk).update(status=status)
        self.season.refresh_from_db()

    def _watch(self, episode_item, end_date):
        """Log a play of an episode."""
        return Episode.objects.create(
            item=episode_item,
            related_season=self.season,
            end_date=end_date,
        )

    def test_repeat_play_keeps_manual_in_progress(self, _mock_metadata):
        """A repeat play must not reset a manually reopened season to Completed."""
        self._set_status(Status.IN_PROGRESS.value)

        self._watch(self.episode_items[0], datetime(2026, 8, 18, tzinfo=UTC))

        self.assertEqual(
            Season.objects.get(pk=self.season.pk).status,
            Status.IN_PROGRESS.value,
        )

    def test_final_first_watch_still_completes(self, _mock_metadata):
        """Guard: finishing a season for the first time must still complete it."""
        self.season.episodes.filter(item=self.episode_items[1]).delete()
        self._set_status(Status.IN_PROGRESS.value)

        self._watch(self.episode_items[1], datetime(2023, 6, 2, tzinfo=UTC))

        self.assertEqual(
            Season.objects.get(pk=self.season.pk).status,
            Status.COMPLETED.value,
        )

    def test_rewatch_resets_progress_to_the_start_of_the_season(
        self,
        _mock_metadata,
    ):
        """Starting a rewatch makes the season read as unwatched again."""
        self.season.start_rewatch()

        self.assertEqual(self.season.progress, 0)
        self.assertEqual(self.season.completed_episode_count, 0)
        self.assertEqual(self.season.next_episode_number(), 1)
        self.assertEqual(self.season.status, Status.IN_PROGRESS.value)

    def test_play_during_rewatch_advances_progress(self, _mock_metadata):
        """Only plays inside the pass count towards it."""
        self.season.start_rewatch()

        self._watch(self.episode_items[0], timezone.now())

        self.season.refresh_from_db()
        self.assertEqual(self.season.progress, 1)
        self.assertEqual(self.season.completed_episode_count, 1)
        self.assertEqual(self.season.next_episode_number(), 2)

    def test_play_without_end_date_counts_towards_the_pass(self, _mock_metadata):
        """A play logged with no date still belongs to the open pass."""
        self.season.start_rewatch()

        self._watch(self.episode_items[0], None)

        self.season.refresh_from_db()
        self.assertEqual(self.season.completed_episode_count, 1)

    def test_finishing_the_rewatch_completes_and_clears_the_pass(
        self,
        _mock_metadata,
    ):
        """The pass ends itself once every episode has been played again."""
        self.season.start_rewatch()

        for episode_item in self.episode_items:
            self._watch(episode_item, timezone.now())

        self.season.refresh_from_db()
        self.assertEqual(self.season.status, Status.COMPLETED.value)
        self.assertIsNone(self.season.rewatch_started_at)

    def test_stopping_a_rewatch_restores_the_completed_status(self, _mock_metadata):
        """Abandoning a pass falls back to what the full history implies."""
        self.season.start_rewatch()

        self.season.stop_rewatch()

        self.season.refresh_from_db()
        self.assertIsNone(self.season.rewatch_started_at)
        self.assertEqual(self.season.status, Status.COMPLETED.value)

    def test_completing_a_season_mid_rewatch_logs_the_missing_plays(
        self,
        _mock_metadata,
    ):
        """Marking the season complete fills in the episodes the pass missed."""
        self.season.start_rewatch()
        self._watch(self.episode_items[0], timezone.now())

        self.season.status = Status.COMPLETED.value
        self.season.save()

        self.assertEqual(
            self.season.episodes.filter(item=self.episode_items[1]).count(),
            2,
        )
        self.season.refresh_from_db()
        self.assertIsNone(self.season.rewatch_started_at)

    def test_show_rewatch_starts_a_pass_on_every_season(self, _mock_metadata):
        """Rewatching a show opens a pass on each of its seasons."""
        self.tv.start_rewatch()

        self.season.refresh_from_db()
        self.assertIsNotNone(self.season.rewatch_started_at)
        self.assertEqual(self.season.status, Status.IN_PROGRESS.value)
        self.assertTrue(self.tv.is_rewatching)

    def test_show_is_not_rewatching_without_an_open_pass(self, _mock_metadata):
        """A show with no season in a pass is not being rewatched."""
        self.assertFalse(self.tv.is_rewatching)

    def test_show_stop_rewatch_closes_every_open_pass(self, _mock_metadata):
        """Ending a show rewatch closes the pass on each of its seasons."""
        self.tv.start_rewatch()

        self.tv.stop_rewatch()

        self.season.refresh_from_db()
        self.assertIsNone(self.season.rewatch_started_at)
        self.assertFalse(self.tv.is_rewatching)

    def test_replaying_an_episode_keeps_its_rating(self, _mock_metadata):
        """A rating belongs to the episode, so a new play carries it too."""
        self.season.episodes.filter(item=self.episode_items[0]).update(score=8)
        self.season.start_rewatch()

        self._watch(self.episode_items[0], timezone.now())

        scores = list(
            self.season.episodes.filter(item=self.episode_items[0]).values_list(
                "score",
                flat=True,
            ),
        )
        self.assertEqual([str(score) for score in scores], ["8.0", "8.0"])

    def test_an_explicit_rating_on_a_play_wins(self, _mock_metadata):
        """Rating the new play directly still takes precedence."""
        self.season.episodes.filter(item=self.episode_items[0]).update(score=8)

        self.season.watch(1, timezone.now(), score=5)

        newest = (
            self.season.episodes.filter(item=self.episode_items[0])
            .order_by("-created_at")
            .first()
        )
        self.assertEqual(str(newest.score), "5.0")
