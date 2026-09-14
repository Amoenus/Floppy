"""Regressions for terminal-failure churn in the metadata backfill.

Production evidence (2026-09-14): one startup pass processed 150 items in 144
seconds and 148 of them failed, overwhelmingly MusicBrainz 400/404 for
recording ids that do not exist. Those items can never grow a release date or
a status, so they sorted to the front of both backfill queues - which order by
oldest ``metadata_fetched_at`` - and were re-fetched on every cycle forever.
"""

from unittest.mock import patch

from django.core.cache import cache
from django.test import TestCase
from django.utils import timezone

from app import tasks
from app.interactive_requests import INTERACTIVE_REQUEST_CACHE_KEY
from app.models import (
    Item,
    MediaTypes,
    MetadataBackfillField,
    MetadataBackfillState,
    Sources,
)
from app.providers.services import ProviderAPIError
from app.tasks_backfill_state import (
    RELEASE_BACKFILL_VERSION,
    is_terminal_backfill_error,
    reset_backfill_state_for_identity_change,
)


class _Response:
    def __init__(self, status_code):
        self.status_code = status_code


def _provider_error(status_code):
    error = Exception("provider said no")
    error.response = _Response(status_code)
    return ProviderAPIError(Sources.MUSICBRAINZ.value, error)


def _music_item(media_id="mbid-dead"):
    """A music item that has been fetched once and has no release date."""
    return Item.objects.create(
        media_id=media_id,
        source=Sources.MUSICBRAINZ.value,
        media_type=MediaTypes.MUSIC.value,
        title="Unresolvable Recording",
        metadata_fetched_at=timezone.now(),
    )


class TerminalErrorClassificationTests(TestCase):
    def test_provider_404_is_terminal(self):
        self.assertTrue(is_terminal_backfill_error(_provider_error(404)))

    def test_provider_400_is_terminal(self):
        self.assertTrue(is_terminal_backfill_error(_provider_error(400)))

    def test_provider_5xx_is_transient(self):
        self.assertFalse(is_terminal_backfill_error(_provider_error(503)))

    def test_provider_429_is_transient(self):
        self.assertFalse(is_terminal_backfill_error(_provider_error(429)))

    def test_missing_credentials_is_transient(self):
        """A 401/403 is usually a key the operator can still fix."""
        self.assertFalse(is_terminal_backfill_error(_provider_error(401)))
        self.assertFalse(is_terminal_backfill_error(_provider_error(403)))

    def test_unreachable_provider_is_transient(self):
        self.assertFalse(is_terminal_backfill_error(_provider_error(None)))

    def test_invalid_identifier_is_terminal(self):
        """A season row with no season number is bad data, not an outage."""
        self.assertTrue(
            is_terminal_backfill_error(ValueError("season item missing season_number")),
        )


class ReleaseBackfillChurnTests(TestCase):
    def setUp(self):
        cache.delete(INTERACTIVE_REQUEST_CACHE_KEY)
        super().setUp()

    def tearDown(self):
        cache.delete(INTERACTIVE_REQUEST_CACHE_KEY)
        super().tearDown()

    def test_terminal_failure_drops_out_of_the_release_queue(self):
        item = _music_item()
        self.assertIn(item, tasks._release_items_queryset())

        with patch(
            "app.tasks._fetch_item_metadata",
            side_effect=_provider_error(404),
        ) as fetch:
            tasks.backfill_item_metadata_task(batch_size=5)
            self.assertEqual(fetch.call_count, 1)

            tasks.backfill_item_metadata_task(batch_size=5)
            self.assertEqual(fetch.call_count, 1)

        state = MetadataBackfillState.objects.get(
            item=item,
            field=MetadataBackfillField.RELEASE.value,
        )
        self.assertTrue(state.give_up)
        self.assertNotIn(item, tasks._release_items_queryset())

    def test_transient_failure_stays_retryable(self):
        item = _music_item()

        with patch(
            "app.tasks._fetch_item_metadata",
            side_effect=_provider_error(503),
        ) as fetch:
            tasks.backfill_item_metadata_task(batch_size=5)
            self.assertEqual(fetch.call_count, 1)

            # Backed off, not given up.
            tasks.backfill_item_metadata_task(batch_size=5)
            self.assertEqual(fetch.call_count, 1)

        state = MetadataBackfillState.objects.get(
            item=item,
            field=MetadataBackfillField.RELEASE.value,
        )
        self.assertFalse(state.give_up)
        self.assertIsNotNone(state.next_retry_at)

        MetadataBackfillState.objects.filter(pk=state.pk).update(
            next_retry_at=timezone.now() - timezone.timedelta(minutes=1),
        )
        self.assertIn(item, tasks._release_items_queryset())

    def test_successful_fetch_without_a_release_date_backs_off_rather_than_repeats(
        self,
    ):
        """The provider answered; it simply has no date. That can change later."""
        item = _music_item()

        with patch("app.tasks._fetch_item_metadata", return_value={}) as fetch:
            tasks.backfill_item_metadata_task(batch_size=5)
            tasks.backfill_item_metadata_task(batch_size=5)

        self.assertEqual(fetch.call_count, 1)
        state = MetadataBackfillState.objects.get(
            item=item,
            field=MetadataBackfillField.RELEASE.value,
        )
        self.assertFalse(state.give_up)
        self.assertIsNotNone(state.next_retry_at)

    def test_backfill_version_bump_reopens_a_terminal_item(self):
        item = _music_item()

        with patch("app.tasks._fetch_item_metadata", side_effect=_provider_error(404)):
            tasks.backfill_item_metadata_task(batch_size=5)

        self.assertNotIn(item, tasks._release_items_queryset())

        with patch(
            "app.tasks.RELEASE_BACKFILL_VERSION",
            RELEASE_BACKFILL_VERSION + 1,
        ):
            self.assertIn(item, tasks._release_items_queryset())

    def test_source_id_change_reopens_a_terminal_item(self):
        item = _music_item()

        with patch("app.tasks._fetch_item_metadata", side_effect=_provider_error(404)):
            tasks.backfill_item_metadata_task(batch_size=5)

        self.assertNotIn(item, tasks._release_items_queryset())

        Item.objects.filter(pk=item.pk).update(media_id="mbid-relinked")
        reset_backfill_state_for_identity_change([item])

        self.assertIn(item, tasks._release_items_queryset())


class StatusBackfillChurnTests(TestCase):
    def setUp(self):
        cache.delete(INTERACTIVE_REQUEST_CACHE_KEY)
        super().setUp()

    def tearDown(self):
        cache.delete(INTERACTIVE_REQUEST_CACHE_KEY)
        super().tearDown()

    def test_terminal_failure_drops_out_of_the_status_queue(self):
        item = Item.objects.create(
            media_id="999999999",
            source=Sources.TMDB.value,
            media_type=MediaTypes.MOVIE.value,
            title="Deleted Upstream",
            release_datetime=timezone.now(),
            metadata_fetched_at=timezone.now(),
        )
        self.assertIn(item, tasks._status_items_queryset())

        with patch("app.tasks._fetch_item_metadata", side_effect=_provider_error(404)):
            tasks.backfill_item_metadata_task(batch_size=5)

        self.assertNotIn(item, tasks._status_items_queryset())
