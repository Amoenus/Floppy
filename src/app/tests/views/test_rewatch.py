from datetime import UTC, datetime
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from app.models import (
    TV,
    Episode,
    Item,
    MediaTypes,
    Season,
    Sources,
    Status,
)

METADATA_PATH = "app.providers.services.get_media_metadata"

SEASON_METADATA = {
    "episodes": [{"episode_number": 1}, {"episode_number": 2}],
    "max_progress": 2,
    "image": "s.jpg",
    "season/1": {"episodes": [{"episode_number": 1}, {"episode_number": 2}]},
}


@patch(METADATA_PATH, return_value=SEASON_METADATA)
class RewatchViewTests(TestCase):
    """Starting and stopping a rewatch from the tracker."""

    def setUp(self):
        """Log in with a show whose only season has been fully watched."""
        self.credentials = {"username": "test", "password": "12345"}
        self.user = get_user_model().objects.create_user(**self.credentials)
        self.client.login(**self.credentials)

        tv_item = Item.objects.create(
            media_id="123",
            source=Sources.TMDB.value,
            media_type=MediaTypes.TV.value,
            title="Show",
        )
        self.tv = TV.objects.create(
            item=tv_item,
            user=self.user,
            status=Status.IN_PROGRESS.value,
        )
        season_item = Item.objects.create(
            media_id="123",
            source=Sources.TMDB.value,
            media_type=MediaTypes.SEASON.value,
            title="Show",
            season_number=1,
        )
        self.season = Season.objects.create(
            item=season_item,
            user=self.user,
            related_tv=self.tv,
            status=Status.IN_PROGRESS.value,
        )
        for episode_number in (1, 2):
            item = Item.objects.create(
                media_id="123",
                source=Sources.TMDB.value,
                media_type=MediaTypes.EPISODE.value,
                title="Show",
                season_number=1,
                episode_number=episode_number,
            )
            with patch(METADATA_PATH, return_value=SEASON_METADATA):
                Episode.objects.create(
                    item=item,
                    related_season=self.season,
                    end_date=datetime(2023, 6, episode_number, tzinfo=UTC),
                )

        # The last play completes the season, which is the state a rewatch
        # starts from.
        self.season.refresh_from_db()
        self.assertEqual(self.season.status, Status.COMPLETED.value)

    def test_start_rewatch_reopens_the_season(self, _mock_metadata):
        """Starting a rewatch opens a pass and reopens the season."""
        self.client.post(
            reverse("media_rewatch"),
            data={
                "instance_id": self.season.id,
                "media_type": MediaTypes.SEASON.value,
                "action": "start",
            },
        )

        self.season.refresh_from_db()
        self.assertIsNotNone(self.season.rewatch_started_at)
        self.assertEqual(self.season.status, Status.IN_PROGRESS.value)

    def test_stop_rewatch_closes_the_pass(self, _mock_metadata):
        """Stopping a rewatch clears the pass and restores Completed."""
        self.season.start_rewatch()

        self.client.post(
            reverse("media_rewatch"),
            data={
                "instance_id": self.season.id,
                "media_type": MediaTypes.SEASON.value,
                "action": "stop",
            },
        )

        self.season.refresh_from_db()
        self.assertIsNone(self.season.rewatch_started_at)
        self.assertEqual(self.season.status, Status.COMPLETED.value)

    def test_stop_rewatch_accepts_the_action_from_the_query_string(
        self,
        _mock_metadata,
    ):
        """The modal button carries the action in the URL, like the other actions."""
        self.season.start_rewatch()

        self.client.post(
            f"{reverse('media_rewatch')}?action=stop",
            data={
                "instance_id": self.season.id,
                "media_type": MediaTypes.SEASON.value,
            },
        )

        self.season.refresh_from_db()
        self.assertIsNone(self.season.rewatch_started_at)

    def test_start_rewatch_for_a_show_covers_its_seasons(self, _mock_metadata):
        """Rewatching a show opens a pass on each season."""
        self.client.post(
            reverse("media_rewatch"),
            data={
                "instance_id": self.tv.id,
                "media_type": MediaTypes.TV.value,
                "action": "start",
            },
        )

        self.season.refresh_from_db()
        self.assertIsNotNone(self.season.rewatch_started_at)
        self.assertEqual(
            TV.objects.get(pk=self.tv.pk).status,
            Status.IN_PROGRESS.value,
        )

    def test_another_users_entry_is_not_touched(self, _mock_metadata):
        """A rewatch may only be started on the requester's own entry."""
        other = get_user_model().objects.create_user(username="other", password="x")
        self.client.force_login(other)

        response = self.client.post(
            reverse("media_rewatch"),
            data={
                "instance_id": self.season.id,
                "media_type": MediaTypes.SEASON.value,
                "action": "start",
            },
        )

        self.season.refresh_from_db()
        self.assertIsNone(self.season.rewatch_started_at)
        self.assertEqual(response.status_code, 404)

    def _track_modal(self):
        """Open the season's track modal."""
        return self.client.get(
            reverse(
                "track_modal",
                kwargs={
                    "source": Sources.TMDB.value,
                    "media_type": MediaTypes.SEASON.value,
                    "media_id": "123",
                },
            ),
            {"season_number": 1, "instance_id": self.season.id},
        )

    def test_track_modal_offers_a_rewatch_for_a_completed_season(self, _mock_metadata):
        """A finished season can be rewatched from its track modal."""
        response = self._track_modal()

        self.assertContains(response, reverse("media_rewatch"))
        self.assertContains(response, "Rewatch")

    def test_track_modal_offers_to_end_an_open_rewatch(self, _mock_metadata):
        """An open pass can be ended from the same place it was started."""
        self.season.start_rewatch()

        response = self._track_modal()

        self.assertContains(response, "End rewatch")

    def test_track_modal_hides_rewatch_for_an_unfinished_season(self, _mock_metadata):
        """A season still being watched for the first time is not a rewatch."""
        Season.objects.filter(pk=self.season.pk).update(
            status=Status.IN_PROGRESS.value,
        )

        response = self._track_modal()

        self.assertNotContains(response, reverse("media_rewatch"))
