import json
import logging
from datetime import UTC, datetime
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.messages import get_messages
from django.test import TestCase
from django.urls import reverse
from django_celery_beat.models import PeriodicTask

from app.models import Movie
from integrations import tasks
from integrations.imports import plex
from integrations.models import PlexAccount

CHECKPOINT_TS = 1700000000


def setUpModule():
    """Silence importer log noise for this module only."""
    logging.getLogger("integrations.imports.plex").setLevel(logging.CRITICAL)


def tearDownModule():
    """Restore the importer logger level for other modules."""
    logging.getLogger("integrations.imports.plex").setLevel(logging.NOTSET)


def _movie_entry(tmdb_id, viewed_at):
    return {
        "type": "movie",
        "title": f"Movie {tmdb_id}",
        "guid": f"tmdb://{tmdb_id}",
        "viewedAt": viewed_at,
        "accountID": "1",
        "ratingKey": f"rk{tmdb_id}",
        "key": f"/library/metadata/rk{tmdb_id}",
    }


def _movie_metadata(media_type, media_id, source=None, **_kwargs):
    return {
        "title": f"Movie {media_id}",
        "media_id": media_id,
        "media_type": "movie",
        "max_progress": 1,
        "image": "/p.jpg",
        "details": {"release_date": "2021-12-24", "runtime": "1h 30m"},
    }


@patch("integrations.imports.plex.PlexHistoryImporter._import_ratings_from_library")
@patch("integrations.imports.plex.plex_api.list_users", return_value=[])
@patch("integrations.imports.plex.services.get_media_metadata", _movie_metadata)
@patch("integrations.imports.plex.plex_api.fetch_history")
@patch(
    "integrations.imports.plex.plex_api.list_resources",
    return_value=[
        {"machine_identifier": "machine", "connections": [{"uri": "http://plex"}]}
    ],
)
class PlexMarkWatchedImporterTests(TestCase):
    """The poll only imports Plex history newer than its checkpoint."""

    def setUp(self):
        """Connect a Plex account whose checkpoint sits at CHECKPOINT_TS."""
        self.user = get_user_model().objects.create_user(username="plexuser")
        self.user.plex_usernames = "plexuser"
        self.user.save(update_fields=["plex_usernames"])
        self.account = PlexAccount.objects.create(
            user=self.user,
            plex_token="token",
            plex_username="plexuser",
            plex_account_id="1",
            sections=[
                {"id": "1", "machine_identifier": "machine", "type": "movie"},
            ],
            mark_watched_checkpoint=datetime.fromtimestamp(CHECKPOINT_TS, tz=UTC),
        )

    def test_imports_only_entries_after_checkpoint(self, _res, mock_fetch, *_):
        """A manual mark after the checkpoint lands; older history does not."""
        mock_fetch.return_value = (
            [
                _movie_entry("200", CHECKPOINT_TS + 60),
                _movie_entry("100", CHECKPOINT_TS - 60),
            ],
            2,
        )

        plex.mark_watched_importer(["all"], self.user, "new")

        movies = Movie.objects.filter(user=self.user)
        self.assertEqual(list(movies.values_list("item__media_id", flat=True)), ["200"])
        self.account.refresh_from_db()
        self.assertEqual(
            self.account.mark_watched_checkpoint,
            datetime.fromtimestamp(CHECKPOINT_TS + 60, tz=UTC),
        )

    def test_stops_paging_at_checkpoint(self, _res, mock_fetch, *_):
        """Reaching an entry at or before the checkpoint ends the fetch."""
        mock_fetch.return_value = (
            [_movie_entry("100", CHECKPOINT_TS)],
            5000,
        )

        plex.mark_watched_importer(["all"], self.user, "new")

        self.assertEqual(mock_fetch.call_count, 1)
        self.assertFalse(Movie.objects.filter(user=self.user).exists())
        self.account.refresh_from_db()
        self.assertEqual(
            self.account.mark_watched_checkpoint,
            datetime.fromtimestamp(CHECKPOINT_TS, tz=UTC),
        )

    def test_skips_library_ratings_pass(self, _res, mock_fetch, _users, mock_ratings):
        """The poll never walks every library item for ratings."""
        mock_fetch.return_value = ([], 0)

        plex.mark_watched_importer(["all"], self.user, "new")

        mock_ratings.assert_not_called()

    def test_replayed_entry_is_not_a_second_play(self, _res, mock_fetch, *_):
        """An entry already recorded (by a webhook or an earlier poll) is skipped."""
        mock_fetch.return_value = ([_movie_entry("200", CHECKPOINT_TS + 60)], 1)

        plex.mark_watched_importer(["all"], self.user, "new")
        PlexAccount.objects.filter(pk=self.account.pk).update(
            mark_watched_checkpoint=datetime.fromtimestamp(CHECKPOINT_TS, tz=UTC),
        )
        plex.mark_watched_importer(["all"], self.user, "new")

        self.assertEqual(Movie.objects.filter(user=self.user).count(), 1)


class PlexMarkWatchedScheduleTests(TestCase):
    """Turning the sync on and off manages one periodic task."""

    def setUp(self):
        """Connect a Plex account and log in."""
        self.credentials = {"username": "plexuser", "password": "12345"}
        self.user = get_user_model().objects.create_user(**self.credentials)
        self.client.login(**self.credentials)

    def _connect(self):
        return PlexAccount.objects.create(
            user=self.user, plex_token="token", plex_username="plexuser"
        )

    def _tasks(self):
        return PeriodicTask.objects.filter(task=plex.MARK_WATCHED_TASK_NAME)

    def test_enable_creates_task_and_starts_checkpoint_now(self):
        """Enabling schedules the poll and never replays older history."""
        account = self._connect()

        response = self.client.post(
            reverse("update_plex_mark_watched"),
            {"plex_mark_watched_enabled": "on"},
        )

        self.assertRedirects(
            response, reverse("integrations"), fetch_redirect_response=False
        )
        account.refresh_from_db()
        self.assertTrue(account.mark_watched_sync_enabled)
        self.assertIsNotNone(account.mark_watched_checkpoint)
        task = self._tasks().get()
        self.assertEqual(json.loads(task.kwargs), {"user_id": self.user.id})
        self.assertEqual(task.interval.every, plex.MARK_WATCHED_INTERVAL_MINUTES)

    def test_saving_again_keeps_checkpoint_and_one_task(self):
        """Re-saving while enabled does not skip marks made since the last poll."""
        account = self._connect()
        plex.set_mark_watched_sync(account, enabled=True)
        checkpoint = datetime.fromtimestamp(CHECKPOINT_TS, tz=UTC)
        PlexAccount.objects.filter(pk=account.pk).update(
            mark_watched_checkpoint=checkpoint,
        )

        self.client.post(
            reverse("update_plex_mark_watched"),
            {"plex_mark_watched_enabled": "on"},
        )

        account.refresh_from_db()
        self.assertEqual(account.mark_watched_checkpoint, checkpoint)
        self.assertEqual(self._tasks().count(), 1)

    def test_disable_deletes_task(self):
        """Unticking removes the schedule."""
        account = self._connect()
        plex.set_mark_watched_sync(account, enabled=True)

        self.client.post(reverse("update_plex_mark_watched"), {})

        account.refresh_from_db()
        self.assertFalse(account.mark_watched_sync_enabled)
        self.assertFalse(self._tasks().exists())

    def test_disconnect_deletes_task(self):
        """Disconnecting Plex leaves no poll behind."""
        account = self._connect()
        plex.set_mark_watched_sync(account, enabled=True)

        self.client.post(reverse("plex_disconnect"))

        self.assertFalse(self._tasks().exists())

    def test_requires_plex_connection(self):
        """Without a Plex account nothing is scheduled."""
        response = self.client.post(
            reverse("update_plex_mark_watched"),
            {"plex_mark_watched_enabled": "on"},
        )

        self.assertRedirects(
            response, reverse("integrations"), fetch_redirect_response=False
        )
        self.assertFalse(self._tasks().exists())
        messages = [str(m) for m in get_messages(response.wsgi_request)]
        self.assertIn("Connect Plex before changing this setting.", messages)

    @patch("integrations.imports.plex.mark_watched_importer")
    def test_task_skips_when_disabled(self, mock_importer):
        """A leftover task for a disabled account does nothing."""
        self._connect()

        result = tasks.sync_plex_mark_watched(user_id=self.user.id)

        self.assertIn("Skipped", result)
        mock_importer.assert_not_called()
