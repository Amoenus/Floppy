from datetime import UTC, datetime
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.template.loader import render_to_string
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


class RewatchRatingVisibility(TestCase):
    """The episode rating stays reachable while a rewatch is under way."""

    def setUp(self):
        """Build the episode payload a season page renders mid-pass."""
        with patch(METADATA_PATH, return_value=SEASON_METADATA):
            self.user = get_user_model().objects.create_user(username="t", password="x")
            tv_item = Item.objects.create(
                media_id="123",
                source=Sources.TMDB.value,
                media_type=MediaTypes.TV.value,
                title="Show",
            )
            tv = TV.objects.create(item=tv_item, user=self.user)
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
                related_tv=tv,
                status=Status.IN_PROGRESS.value,
            )
            self.episode_item = Item.objects.create(
                media_id="123",
                source=Sources.TMDB.value,
                media_type=MediaTypes.EPISODE.value,
                title="Show",
                season_number=1,
                episode_number=1,
            )
            self.play = Episode.objects.create(
                item=self.episode_item,
                related_season=self.season,
                end_date=datetime(2023, 6, 1, tzinfo=UTC),
                score=8,
            )

    def _payload(self, history, all_history):
        """Mimic one entry of what process_episodes() hands the template."""
        return {
            "media_id": "123",
            "media_type": MediaTypes.EPISODE.value,
            "source": Sources.TMDB.value,
            "season_number": 1,
            "episode_number": 1,
            "item": self.episode_item,
            "history": history,
            "all_history": all_history,
        }

    def _render(self, episode_payload):
        return render_to_string(
            "app/components/detail_row_actions.html",
            {
                "episode": episode_payload,
                "action_media_type": MediaTypes.EPISODE.value,
                "track_button_variant": "row",
                "current_instance": self.season,
                "history_item": self.episode_item,
                "user": self.user,
                "MediaTypes": MediaTypes,
                "media_type": MediaTypes.SEASON.value,
            },
        )

    def test_rating_is_offered_for_an_episode_not_yet_replayed(self):
        """Mid-pass the episode has no play in the window, but it is still rated."""
        html = self._render(self._payload([], [self.play]))

        self.assertIn("Rate episode", html)

    def test_row_renders_no_leaked_template_comment(self):
        """A `{# #}` comment only spans one line; a longer one renders as text."""
        html = self._render(self._payload([], [self.play]))

        self.assertNotIn("{#", html)

    def test_rating_is_hidden_for_an_episode_never_watched(self):
        """An untouched episode still offers no rating."""
        html = self._render(self._payload([], []))

        self.assertNotIn("Rate episode", html)
