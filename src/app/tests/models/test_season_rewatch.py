from datetime import UTC, datetime
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase

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
