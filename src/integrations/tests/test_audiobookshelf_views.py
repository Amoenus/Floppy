# FORK: recurring-schedule coverage for the Audiobookshelf connect/import views.
from unittest.mock import Mock, patch

import requests
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from django_celery_beat.models import CrontabSchedule, IntervalSchedule, PeriodicTask

from integrations import audiobookshelf_cover
from integrations.imports import helpers
from integrations.models import AudiobookshelfAccount

BASE_URL = "https://audiobookshelf.example.com"
API_TOKEN = "abs-secret-token"


class AudiobookshelfScheduleTests(TestCase):
    """Connecting/importing keeps a minute-based recurring schedule in sync."""

    def setUp(self):
        """Create an authenticated user for Audiobookshelf view requests."""
        self.user = get_user_model().objects.create_user(username="abs-connect")
        self.client.force_login(self.user)

    @patch("integrations.views.tasks.import_audiobookshelf.delay")
    @patch("integrations.views.AudiobookshelfClient.get_me", return_value={})
    def test_connect_creates_interval_schedule_immediately(
        self, mock_get_me, mock_import
    ):
        """Connecting (not just a manual import) schedules the recurring poll."""
        response = self.client.post(
            reverse("audiobookshelf_connect"),
            {"base_url": BASE_URL, "api_token": API_TOKEN},
        )

        self.assertEqual(response.status_code, 302)
        self.assertTrue(
            AudiobookshelfAccount.objects.filter(user=self.user).exists()
        )
        mock_import.assert_called_once()

        task = PeriodicTask.objects.get(
            task="Import from Audiobookshelf (Recurring)",
            kwargs__contains=f'"user_id": {self.user.id}',
        )
        self.assertIsNotNone(task.interval)
        self.assertIsNone(task.crontab)
        self.assertEqual(task.interval.every, 15)
        self.assertEqual(task.interval.period, IntervalSchedule.MINUTES)
        self.assertTrue(task.enabled)

    @override_settings(AUDIOBOOKSHELF_POLL_INTERVAL_MINUTES=5)
    @patch("integrations.views.tasks.import_audiobookshelf.delay")
    @patch("integrations.views.AudiobookshelfClient.get_me", return_value={})
    def test_connect_honors_configured_interval(self, mock_get_me, mock_import):
        """The polling cadence respects AUDIOBOOKSHELF_POLL_INTERVAL_MINUTES."""
        self.client.post(
            reverse("audiobookshelf_connect"),
            {"base_url": BASE_URL, "api_token": API_TOKEN},
        )

        task = PeriodicTask.objects.get(
            task="Import from Audiobookshelf (Recurring)",
            kwargs__contains=f'"user_id": {self.user.id}',
        )
        self.assertEqual(task.interval.every, 5)

    @patch("integrations.views.tasks.import_audiobookshelf.delay")
    def test_manual_import_migrates_legacy_crontab_schedule(self, mock_import):
        """A pre-existing 2-hour crontab schedule is converted, not duplicated."""
        AudiobookshelfAccount.objects.create(
            user=self.user, base_url=BASE_URL, api_token="encrypted"
        )
        crontab, _ = CrontabSchedule.objects.get_or_create(
            minute=0,
            hour="*/2",
            day_of_week="*",
            day_of_month="*",
            month_of_year="*",
        )
        PeriodicTask.objects.create(
            name=f"Import from Audiobookshelf for {self.user.username} (every 2 hours)",
            task="Import from Audiobookshelf (Recurring)",
            crontab=crontab,
            kwargs=f'{{"user_id": {self.user.id}}}',
            enabled=True,
        )

        response = self.client.post(reverse("import_audiobookshelf"))
        self.assertEqual(response.status_code, 302)

        tasks_for_user = PeriodicTask.objects.filter(
            task="Import from Audiobookshelf (Recurring)",
            kwargs__contains=f'"user_id": {self.user.id}',
        )
        self.assertEqual(tasks_for_user.count(), 1)
        task = tasks_for_user.get()
        self.assertIsNone(task.crontab)
        self.assertIsNotNone(task.interval)
        self.assertEqual(task.interval.every, 15)

    def test_disconnect_removes_schedule(self):
        """Disconnecting deletes the recurring periodic task."""
        AudiobookshelfAccount.objects.create(
            user=self.user, base_url=BASE_URL, api_token="encrypted"
        )
        interval, _ = IntervalSchedule.objects.get_or_create(
            every=15, period=IntervalSchedule.MINUTES
        )
        PeriodicTask.objects.create(
            name="Import from Audiobookshelf for abs-connect (every 15 minutes)",
            task="Import from Audiobookshelf (Recurring)",
            interval=interval,
            kwargs=f'{{"user_id": {self.user.id}}}',
            enabled=True,
        )

        response = self.client.post(reverse("audiobookshelf_disconnect"))

        self.assertEqual(response.status_code, 302)
        self.assertFalse(
            AudiobookshelfAccount.objects.filter(user=self.user).exists()
        )
        self.assertFalse(
            PeriodicTask.objects.filter(
                task="Import from Audiobookshelf (Recurring)",
                kwargs__contains=f'"user_id": {self.user.id}',
            ).exists()
        )


class AudiobookshelfCoverProxyTests(TestCase):
    """The cover proxy authenticates to ABS server-side (see issue #861)."""

    def setUp(self):
        """Create a connected Audiobookshelf account to proxy covers for."""
        self.user = get_user_model().objects.create_user(username="abs-cover")
        self.account = AudiobookshelfAccount.objects.create(
            user=self.user,
            base_url=BASE_URL,
            api_token=helpers.encrypt(API_TOKEN),
        )

    def _cover_url(self, library_item_id="item-1"):
        return audiobookshelf_cover.build_cover_proxy_url(
            self.account.id,
            library_item_id,
        )

    @patch("integrations.views.requests.get")
    def test_streams_cover_with_valid_token(self, mock_get):
        """A valid signed token fetches the upstream cover with the stored token."""
        mock_get.return_value = Mock(
            status_code=200,
            content=b"fake-image-bytes",
            headers={"Content-Type": "image/webp"},
        )

        response = self.client.get(self._cover_url("item-1"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, b"fake-image-bytes")
        self.assertEqual(response["Content-Type"], "image/webp")

        mock_get.assert_called_once_with(
            f"{BASE_URL}/api/items/item-1/cover",
            headers={"Authorization": f"Bearer {API_TOKEN}"},
            timeout=15,
        )

    def test_returns_404_for_invalid_token(self):
        """A tampered or malformed token never reaches the ABS request."""
        response = self.client.get(
            reverse("audiobookshelf_cover", kwargs={"token": "not-a-real-token"}),
        )
        self.assertEqual(response.status_code, 404)

    def test_returns_404_when_account_no_longer_exists(self):
        """A signed token for a deleted account 404s instead of erroring."""
        url = audiobookshelf_cover.build_cover_proxy_url(999_999, "item-1")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 404)

    @patch("integrations.views.requests.get")
    def test_returns_404_on_upstream_error_status(self, mock_get):
        """An ABS-side auth failure surfaces as a 404, not a broken image."""
        mock_get.return_value = Mock(status_code=401, content=b"", headers={})

        response = self.client.get(self._cover_url())

        self.assertEqual(response.status_code, 404)

    @patch("integrations.views.requests.get")
    def test_returns_404_on_request_exception(self, mock_get):
        """A network failure talking to ABS surfaces as a 404."""
        mock_get.side_effect = requests.ConnectionError("boom")

        response = self.client.get(self._cover_url())

        self.assertEqual(response.status_code, 404)
