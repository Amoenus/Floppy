"""Tests for the read-only calendar sentinel audit command."""

from datetime import UTC, datetime
from io import StringIO
from unittest.mock import patch

from django.core.management import CommandError, call_command
from django.db import DatabaseError, connection
from django.test import TestCase

from app.models import Item, MediaTypes, Sources
from events.models import (
    LEGACY_UNKNOWN_RELEASED_DATETIME,
    LEGACY_UNKNOWN_UNRELEASED_DATETIME,
    UNKNOWN_RELEASED_DATETIME,
    UNKNOWN_UNRELEASED_DATETIME,
    Event,
)


class AuditCalendarSentinelsTests(TestCase):
    """Verify deterministic, privacy-safe sentinel inventory output."""

    normal_datetime = datetime(2026, 1, 1, tzinfo=UTC)
    upstream_released_datetime = datetime(
        1,
        1,
        1,
        11,
        59,
        59,
        999999,
        tzinfo=UTC,
    )
    upstream_unreleased_datetime = datetime(
        9999,
        12,
        31,
        11,
        59,
        59,
        999999,
        tzinfo=UTC,
    )

    def _add_event(self, event_datetime, release_datetime, media_type, number):
        item = Item.objects.create(
            media_id=f"PRIVATE-ID-{number}",
            source=Sources.TMDB.value,
            media_type=media_type,
            title=f"PRIVATE TITLE {number}",
            release_datetime=release_datetime,
        )
        event = Event.objects.create(item=item, datetime=event_datetime)
        return item, event

    def _run(self, *args):
        output = StringIO()
        call_command("audit_calendar_sentinels", *args, stdout=output)
        return output.getvalue()

    def test_reports_known_and_ambiguous_boundaries_for_events_and_items(self):
        """Known placeholder shapes stay separate from ambiguous boundary dates."""
        rows = [
            (
                LEGACY_UNKNOWN_RELEASED_DATETIME,
                self.upstream_released_datetime,
                MediaTypes.MOVIE.value,
            ),
            (
                self.upstream_released_datetime,
                UNKNOWN_RELEASED_DATETIME,
                MediaTypes.ANIME.value,
            ),
            (
                UNKNOWN_RELEASED_DATETIME,
                LEGACY_UNKNOWN_RELEASED_DATETIME,
                MediaTypes.MOVIE.value,
            ),
            (
                datetime(1, 6, 1, tzinfo=UTC),
                datetime(1, 7, 1, tzinfo=UTC),
                MediaTypes.BOOK.value,
            ),
            (
                LEGACY_UNKNOWN_UNRELEASED_DATETIME,
                self.upstream_unreleased_datetime,
                MediaTypes.COMIC.value,
            ),
            (
                self.upstream_unreleased_datetime,
                UNKNOWN_UNRELEASED_DATETIME,
                MediaTypes.GAME.value,
            ),
            (
                UNKNOWN_UNRELEASED_DATETIME,
                LEGACY_UNKNOWN_UNRELEASED_DATETIME,
                MediaTypes.COMIC.value,
            ),
            (
                datetime(9999, 6, 1, tzinfo=UTC),
                datetime(9999, 7, 1, tzinfo=UTC),
                MediaTypes.TV.value,
            ),
        ]
        identifiers = [
            self._add_event(event_date, item_date, media_type, number)
            for number, (event_date, item_date, media_type) in enumerate(rows, 1)
        ]
        Item.objects.create(
            media_id="PRIVATE-UNLINKED-ID",
            source=Sources.TMDB.value,
            media_type=MediaTypes.MOVIE.value,
            title="PRIVATE UNLINKED TITLE",
            release_datetime=LEGACY_UNKNOWN_RELEASED_DATETIME,
        )

        output = self._run()

        event_pks = [event.pk for _item, event in identifiers]
        item_pks = [item.pk for item, _event in identifiers]
        self.assertIn(
            f"backend={connection.vendor} sample_limit=10",
            output,
        )
        expected = (
            ("event", "datetime", "legacy_min", "movie", event_pks[0]),
            ("event", "datetime", "upstream_safe_min", "anime", event_pks[1]),
            ("event", "datetime", "floppy_safe_min", "movie", event_pks[2]),
            ("event", "datetime", "ambiguous_year_1", "book", event_pks[3]),
            ("event", "datetime", "legacy_max", "comic", event_pks[4]),
            ("event", "datetime", "upstream_safe_max", "game", event_pks[5]),
            ("event", "datetime", "floppy_safe_max", "comic", event_pks[6]),
            ("event", "datetime", "ambiguous_year_9999", "tv", event_pks[7]),
            ("item", "release_datetime", "upstream_safe_min", "movie", item_pks[0]),
            ("item", "release_datetime", "floppy_safe_min", "anime", item_pks[1]),
            ("item", "release_datetime", "legacy_min", "movie", item_pks[2]),
            ("item", "release_datetime", "ambiguous_year_1", "book", item_pks[3]),
            ("item", "release_datetime", "upstream_safe_max", "comic", item_pks[4]),
            ("item", "release_datetime", "floppy_safe_max", "game", item_pks[5]),
            ("item", "release_datetime", "legacy_max", "comic", item_pks[6]),
            ("item", "release_datetime", "ambiguous_year_9999", "tv", item_pks[7]),
        )
        for record, field, category, media_type, pk in expected:
            self.assertIn(
                f"record={record} field={field} category={category} total=1 "
                f"media_types={media_type}:1 sample_pks={pk}",
                output,
            )

    def test_prints_zero_categories_and_limits_samples_without_private_data(self):
        """Every category prints and samples expose only the first ten PKs."""
        empty_output = self._run()
        self.assertEqual(empty_output.count(" total=0 media_types=- sample_pks=-"), 16)

        events = [
            self._add_event(
                UNKNOWN_RELEASED_DATETIME,
                self.normal_datetime,
                MediaTypes.MOVIE.value,
                number,
            )[1]
            for number in range(12)
        ]

        output = self._run()

        expected_samples = ",".join(str(event.pk) for event in events[:10])
        known_released_line = next(
            line
            for line in output.splitlines()
            if line.startswith(
                "record=event field=datetime category=floppy_safe_min ",
            )
        )
        self.assertEqual(
            known_released_line,
            "record=event field=datetime category=floppy_safe_min total=12 "
            f"media_types=movie:12 sample_pks={expected_samples}",
        )
        self.assertNotIn("PRIVATE TITLE", output)
        self.assertNotIn("PRIVATE-ID", output)

    def test_findings_exit_zero_without_mutating_rows(self):
        """A populated audit succeeds and leaves event and item dates unchanged."""
        item, event = self._add_event(
            LEGACY_UNKNOWN_RELEASED_DATETIME,
            LEGACY_UNKNOWN_UNRELEASED_DATETIME,
            MediaTypes.MOVIE.value,
            1,
        )

        self._run()

        item.refresh_from_db()
        event.refresh_from_db()
        self.assertEqual(item.release_datetime, LEGACY_UNKNOWN_UNRELEASED_DATETIME)
        self.assertEqual(event.datetime, LEGACY_UNKNOWN_RELEASED_DATETIME)

    def test_rejects_write_options(self):
        """The audit exposes no apply or write mode."""
        with self.assertRaises(CommandError):
            self._run("--apply")

    def test_database_errors_propagate(self):
        """Operational database failures remain nonzero command failures."""
        with (
            patch(
                "django.db.models.query.QuerySet.count",
                side_effect=DatabaseError("database unavailable"),
            ),
            self.assertRaisesMessage(DatabaseError, "database unavailable"),
        ):
            self._run()
