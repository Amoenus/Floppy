"""Viewing an artist must not call MusicBrainz on every page load."""

from datetime import UTC, datetime
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse

from app.models import Album, Artist, Item, MediaTypes, Music, Sources, Status


class ArtistViewProviderCostTests(TestCase):
    """Repeat views reuse the last MusicBrainz attempt instead of repeating it."""

    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user(username="artistview")
        cls.user.music_enabled = True
        cls.user.save()
        # An album MusicBrainz could not match keeps its MBIDs empty, which
        # used to force a full discography sync on every view.
        cls.artist = Artist.objects.create(name="Unmatched Artist")
        cls.album = Album.objects.create(title="Unmatched Album", artist=cls.artist)
        played_at = datetime(2026, 1, 15, 20, 0, tzinfo=UTC)
        for index in range(3):
            track = Item.objects.create(
                media_id=f"artist-view-track-{index}",
                source=Sources.MUSICBRAINZ.value,
                media_type=MediaTypes.MUSIC.value,
                title=f"Track {index}",
            )
            Music.objects.create(
                user=cls.user,
                item=track,
                artist=cls.artist,
                album=cls.album,
                status=Status.COMPLETED.value,
                start_date=played_at,
                end_date=played_at,
            )

    def setUp(self):
        cache.clear()
        self.client.force_login(self.user)

    def _view(self):
        return self.client.get(
            reverse("music_artist_details", args=[self.artist.id, "unmatched-artist"]),
        )

    @patch("app.services.music.resolve_artist_mbid", return_value=(None, 0, ""))
    def test_unmatched_artist_is_searched_once_per_day(self, mock_resolve):
        self.assertEqual(self._view().status_code, 200)
        self.assertEqual(self._view().status_code, 200)

        self.assertEqual(mock_resolve.call_count, 1)

    @patch("app.services.music.sync_artist_discography", return_value=0)
    def test_forced_sync_runs_once_across_repeat_views(self, mock_sync):
        Artist.objects.filter(pk=self.artist.pk).update(
            musicbrainz_id="11111111-2222-3333-4444-555555555555",
        )

        self.assertEqual(self._view().status_code, 200)
        self.assertEqual(self._view().status_code, 200)

        self.assertEqual(mock_sync.call_count, 1)
