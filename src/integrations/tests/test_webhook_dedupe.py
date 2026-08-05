"""Tests for collapsing repeated media-server webhooks (issue #521)."""

import json
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import Client, SimpleTestCase, TestCase
from django.urls import reverse

from app import cache_safety
from integrations.webhook_dedupe import should_process_webhook, webhook_dedupe_key


class FingerprintTests(SimpleTestCase):
    """What counts as "the same webhook"."""

    def test_playback_position_is_not_part_of_the_identity(self):
        """Otherwise every progress event looks new and queues its own task."""
        first = {
            "Event": "Progress",
            "Item": {"Id": "abc", "Name": "Ep", "RunTimeTicks": 1000},
            "PlaybackInfo": {"PositionTicks": 500},
        }
        second = {
            "Event": "Progress",
            "Item": {"Id": "abc", "Name": "Ep", "RunTimeTicks": 1000},
            "PlaybackInfo": {"PositionTicks": 9000},
        }

        self.assertEqual(
            webhook_dedupe_key("jellyfin", 1, first),
            webhook_dedupe_key("jellyfin", 1, second),
        )

    def test_event_type_is_part_of_the_identity(self):
        """A Stop after a Play means something different and must be processed."""
        play = {"Event": "Play", "Item": {"Id": "abc"}}
        stop = {"Event": "Stop", "Item": {"Id": "abc"}}

        self.assertNotEqual(
            webhook_dedupe_key("jellyfin", 1, play),
            webhook_dedupe_key("jellyfin", 1, stop),
        )

    def test_different_episodes_are_different_webhooks(self):
        """Bingeing must not collapse into one scrobble."""
        first = {"Event": "Stop", "Item": {"Id": "a", "IndexNumber": 1}}
        second = {"Event": "Stop", "Item": {"Id": "b", "IndexNumber": 2}}

        self.assertNotEqual(
            webhook_dedupe_key("jellyfin", 1, first),
            webhook_dedupe_key("jellyfin", 1, second),
        )

    def test_different_users_never_share_a_key(self):
        """Two people watching the same thing must both be recorded."""
        payload = {"Event": "Stop", "Item": {"Id": "abc"}}

        self.assertNotEqual(
            webhook_dedupe_key("jellyfin", 1, payload),
            webhook_dedupe_key("jellyfin", 2, payload),
        )

    def test_unrecognized_shape_has_no_key(self):
        """A provider changing its JSON must degrade to no deduplication."""
        self.assertIsNone(webhook_dedupe_key("jellyfin", 1, {}))
        self.assertIsNone(webhook_dedupe_key("unknown_provider", 1, {"a": 1}))
        self.assertIsNone(webhook_dedupe_key("jellyfin", 1, "not a dict"))

    def test_media_titles_do_not_appear_verbatim_in_the_key(self):
        """Titles are hashed, not interpolated into the cache key."""
        payload = {"Event": "Stop", "Item": {"SeriesName": "Some Private Show"}}
        key = webhook_dedupe_key("jellyfin", 1, payload)
        self.assertNotIn("Some Private Show", key)


class ThrottleTests(TestCase):
    """The throttle itself."""

    def setUp(self):
        """Start from a clean cache."""
        cache.clear()

    def test_the_first_webhook_is_processed_and_the_second_is_not(self):
        """The point of the exercise."""
        payload = {"Event": "Progress", "Item": {"Id": "abc"}}

        self.assertTrue(should_process_webhook("jellyfin", 1, payload))
        self.assertFalse(should_process_webhook("jellyfin", 1, payload))

    def test_an_unrecognized_payload_is_always_processed(self):
        """Never drop a scrobble to save work."""
        for _ in range(3):
            self.assertTrue(should_process_webhook("jellyfin", 1, {}))

    def test_an_unavailable_cache_fails_open(self):
        """A dropped scrobble is unrecoverable; a duplicate one is not.

        This is the opposite of the background scheduling locks, which fail
        closed - see app/cache_safety.py.
        """
        payload = {"Event": "Stop", "Item": {"Id": "abc"}}

        with patch.object(cache_safety, "cache_add", return_value=None):
            self.assertTrue(should_process_webhook("jellyfin", 1, payload))
            self.assertTrue(should_process_webhook("jellyfin", 1, payload))


class WebhookViewThrottleTests(TestCase):
    """End to end through the views."""

    def setUp(self):
        """Create a user and client, and clear the throttle."""
        cache.clear()
        self.client = Client()
        self.user = get_user_model().objects.create_user(
            username="dedupeuser",
            password="12345",  # test fixture
            token="dedupe-token",
        )

    @patch("integrations.tasks.process_webhook.delay")
    def test_repeated_jellyfin_progress_events_queue_one_task(self, mock_delay):
        """Five progress events for one episode used to queue five tasks."""
        url = reverse("jellyfin_webhook", kwargs={"token": "dedupe-token"})
        payload = {"Event": "Progress", "Item": {"Id": "ep-1", "Type": "Episode"}}

        for _ in range(5):
            response = self.client.post(
                url,
                data=json.dumps(payload),
                content_type="application/json",
            )
            self.assertEqual(response.status_code, 200)

        mock_delay.assert_called_once_with("jellyfin", payload, self.user.id)

    @patch("integrations.tasks.process_webhook.delay")
    def test_a_different_episode_still_queues_its_own_task(self, mock_delay):
        """The throttle must not swallow a genuine second play."""
        url = reverse("jellyfin_webhook", kwargs={"token": "dedupe-token"})

        for item_id in ("ep-1", "ep-2"):
            self.client.post(
                url,
                data=json.dumps({"Event": "Stop", "Item": {"Id": item_id}}),
                content_type="application/json",
            )

        self.assertEqual(mock_delay.call_count, 2)

    @patch("integrations.tasks.process_webhook.delay")
    def test_repeated_plex_events_queue_one_task(self, mock_delay):
        """Plex sends several events per play too."""
        url = reverse("plex_webhook", kwargs={"token": "dedupe-token"})
        payload = {
            "event": "media.scrobble",
            "Metadata": {"ratingKey": "1234", "type": "episode"},
        }

        for _ in range(3):
            self.client.post(url, data={"payload": json.dumps(payload)})

        mock_delay.assert_called_once()
