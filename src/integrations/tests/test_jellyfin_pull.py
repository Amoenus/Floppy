from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase

from integrations.models import ImportRun, JellyfinAccount
from integrations.tasks._jellyfin_pull import pull_jellyfin_history


class PullJellyfinHistoryTaskTests(TestCase):
    """Cover tier selection and cursor handling in the automatic pull task."""

    def setUp(self):
        self.user = get_user_model().objects.create_user(username="pull-task-user")
        self.account = JellyfinAccount.objects.create(
            user=self.user,
            base_url="https://jellyfin.example",
            api_key="encrypted",
            jellyfin_user_id="jf-user",
        )

    @patch(
        "integrations.imports.jellyfin_playback_reporting.decrypt_or_raise",
        return_value="api-key",
    )
    @patch(
        "integrations.tasks._jellyfin_pull.decrypt_or_raise",
        return_value="api-key",
    )
    @patch("integrations.jellyfin_client.JellyfinClient.iter_library_items")
    @patch("integrations.jellyfin_client.JellyfinClient.fetch_playback_activity")
    @patch("integrations.jellyfin_client.JellyfinClient.probe_playback_reporting")
    def test_uses_playback_reporting_tier_when_available(
        self,
        mock_probe,
        mock_fetch,
        mock_library,
        mock_decrypt_task,
        mock_decrypt_importer,
    ):
        mock_probe.return_value = True
        mock_fetch.return_value = []
        mock_library.return_value = []

        pull_jellyfin_history(self.user.id)

        self.account.refresh_from_db()
        self.assertTrue(self.account.playback_reporting_available)
        self.assertEqual(self.account.playback_reporting_last_rowid, 0)
        self.assertIsNotNone(self.account.last_pull_at)
        mock_fetch.assert_called_once_with(0, 2000)

    @patch(
        "integrations.imports.jellyfin_playback_reporting.decrypt_or_raise",
        return_value="api-key",
    )
    @patch(
        "integrations.tasks._jellyfin_pull.decrypt_or_raise",
        return_value="api-key",
    )
    @patch("integrations.jellyfin_client.JellyfinClient.iter_library_items")
    @patch("integrations.jellyfin_client.JellyfinClient.probe_playback_reporting")
    def test_falls_back_to_library_backfill_when_unavailable(
        self,
        mock_probe,
        mock_library,
        mock_decrypt_task,
        mock_decrypt_importer,
    ):
        mock_probe.return_value = False
        mock_library.return_value = []

        message = pull_jellyfin_history(self.user.id)

        self.account.refresh_from_db()
        self.assertFalse(self.account.playback_reporting_available)
        self.assertIsNotNone(self.account.library_backfill_completed_at)
        self.assertIn("current watched state", message)

    @patch(
        "integrations.imports.jellyfin_playback_reporting.decrypt_or_raise",
        return_value="api-key",
    )
    @patch(
        "integrations.tasks._jellyfin_pull.decrypt_or_raise",
        return_value="api-key",
    )
    @patch("integrations.jellyfin_client.JellyfinClient.iter_library_items")
    @patch("integrations.jellyfin_client.JellyfinClient.fetch_max_playback_activity_rowid")
    @patch("integrations.jellyfin_client.JellyfinClient.fetch_playback_activity")
    @patch("integrations.jellyfin_client.JellyfinClient.probe_playback_reporting")
    def test_skips_full_backfill_after_prior_manual_import(
        self,
        mock_probe,
        mock_fetch,
        mock_max_rowid,
        mock_library,
        mock_decrypt_task,
        mock_decrypt_importer,
    ):
        """A prior manual TSV import means the first API pull starts fresh, not from 0."""
        ImportRun.objects.create(
            user=self.user,
            source="jellyfin_playback_reporting",
            status=ImportRun.Status.COMPLETED,
        )
        mock_probe.return_value = True
        mock_max_rowid.return_value = 42
        mock_fetch.return_value = []
        mock_library.return_value = []

        pull_jellyfin_history(self.user.id)

        mock_max_rowid.assert_called_once()
        mock_fetch.assert_called_once_with(42, 2000)

    @patch(
        "integrations.imports.jellyfin_playback_reporting.decrypt_or_raise",
        return_value="api-key",
    )
    @patch(
        "integrations.tasks._jellyfin_pull.decrypt_or_raise",
        return_value="api-key",
    )
    @patch("integrations.jellyfin_client.JellyfinClient.probe_playback_reporting")
    def test_auth_error_marks_connection_broken(
        self,
        mock_probe,
        mock_decrypt_task,
        mock_decrypt_importer,
    ):
        from integrations.jellyfin_client import JellyfinAuthError

        mock_probe.side_effect = JellyfinAuthError("bad key")

        with self.assertRaises(JellyfinAuthError):
            pull_jellyfin_history(self.user.id)

        self.account.refresh_from_db()
        self.assertTrue(self.account.connection_broken)
        self.assertIn("bad key", self.account.last_pull_error_message)
