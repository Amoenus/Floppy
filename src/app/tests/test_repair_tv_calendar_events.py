"""Tests for the repair_tv_calendar_events management command."""

from io import StringIO
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase, override_settings

from app.models import TV, Item, MediaTypes, Season, Sources, Status
from events.calendar.helpers import date_parser
from events.models import Event


class RepairTVCalendarEventsTests(TestCase):
    """Verify candidate detection and provider-backed event repair."""

    def setUp(self):
        """Create a tracked TMDB show with a legacy fabricated event."""
        self.user = get_user_model().objects.create_user(
            username="repair-tv-user",
            password="12345",
        )
        self.tv_item = Item.objects.create(
            media_id="38052",
            source=Sources.TMDB.value,
            media_type=MediaTypes.TV.value,
            title="Silo",
            image="http://example.com/show.jpg",
        )
        self.tv = TV.objects.create(
            item=self.tv_item,
            user=self.user,
            status=Status.IN_PROGRESS.value,
        )
        self.season_item = Item.objects.create(
            media_id="38052",
            source=Sources.TMDB.value,
            media_type=MediaTypes.SEASON.value,
            title="Silo",
            image="http://example.com/season.jpg",
            season_number=3,
        )
        self.season = Season.objects.create(
            item=self.season_item,
            related_tv=self.tv,
            user=self.user,
            status=Status.IN_PROGRESS.value,
        )
        self.event = Event.objects.create(
            item=self.season_item,
            content_number=4,
            datetime=date_parser("2026-07-24").replace(
                hour=12,
                minute=0,
                second=0,
                microsecond=0,
            ),
        )

    def _run(self, *args):
        """Run the command and capture stdout."""
        output = StringIO()
        call_command("repair_tv_calendar_events", *args, stdout=output)
        return output.getvalue()

    @override_settings(TIME_ZONE="America/Chicago")
    def test_dry_run_reports_candidates_without_provider_or_database_changes(self):
        """The default command mode only reports matching shows."""
        with patch(
            "app.management.commands.repair_tv_calendar_events.process_tv",
        ) as mock_process:
            output = self._run("--username", self.user.username)

        self.assertIn("DRY RUN", output)
        self.assertIn("Silo (38052): S3", output)
        mock_process.assert_not_called()
        self.event.refresh_from_db()
        self.assertEqual(self.event.datetime.hour, 12)
        self.assertEqual(self.event.datetime.minute, 0)

    def test_apply_refreshes_only_affected_seasons(self):
        """Apply mode uses the forced season path and persists its result."""

        def fake_process(_tv_item, events_bulk, force_seasons):
            self.assertEqual(force_seasons, [3])
            events_bulk.append(
                Event(
                    item=self.season_item,
                    content_number=4,
                    datetime=date_parser("2026-07-24"),
                ),
            )
            return True

        with (
            patch(
                "app.management.commands.repair_tv_calendar_events.process_tv",
                side_effect=fake_process,
            ) as mock_process,
            patch(
                "app.management.commands.repair_tv_calendar_events.cleanup_invalid_events",
            ) as mock_cleanup,
            patch(
                "app.management.commands.repair_tv_calendar_events.record_calendar_checks",
            ) as mock_record,
        ):
            output = self._run("--apply", "--media-id", self.tv_item.media_id)

        self.assertIn("APPLYING", output)
        self.assertIn("1 event(s) changed", output)
        mock_process.assert_called_once()
        mock_cleanup.assert_called_once()
        mock_record.assert_called_once_with([self.tv_item])
        self.event.refresh_from_db()
        self.assertTrue(self.event.is_sentinel_time)
