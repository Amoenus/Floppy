import logging
from http import HTTPStatus
from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone
from django_celery_beat.models import PeriodicTask

from app.models import TV, Episode, Item, MediaTypes, Movie, Season, Sources, Status
from integrations.imports import jellyfin
from integrations.imports.helpers import MediaImportError, encrypt
from integrations.models import JellyfinAccount


def setUpModule():
    """Silence importer log noise for this module only."""
    logging.getLogger("integrations.imports.jellyfin").setLevel(logging.CRITICAL)


def tearDownModule():
    """Restore the importer logger level for other modules."""
    logging.getLogger("integrations.imports.jellyfin").setLevel(logging.NOTSET)


MOVIE_METADATA = {
    "media_id": "603",
    "title": "The Matrix",
    "image": "matrix.jpg",
    "max_progress": 1,
}

TV_METADATA = {
    "media_id": "1396",
    "title": "Breaking Bad",
    "image": "bb.jpg",
    "max_progress": 5,
    "details": {"number_of_episodes": 5},
    "season/1": {
        "season_number": 1,
        "name": "Season 1",
        "image": "bb-s1.jpg",
        "poster_path": "/s1.jpg",
        "episodes": [
            {
                "episode_number": 1,
                "name": "Pilot",
                "still_path": "/e1.jpg",
                "air_date": "2008-01-20",
            },
            {
                "episode_number": 2,
                "name": "Cat's in the Bag",
                "still_path": "/e2.jpg",
                "air_date": "2008-01-27",
            },
        ],
    },
}


def _movie(item_id, tmdb_id, *, played=True, last_played=None, rating=None,
           favorite=False, name="The Matrix"):
    return {
        "Id": item_id,
        "Type": "Movie",
        "Name": name,
        "ProviderIds": {"Tmdb": str(tmdb_id)},
        "UserData": {
            "Played": played,
            "LastPlayedDate": last_played,
            "Rating": rating,
            "IsFavorite": favorite,
        },
    }


def _series(series_id, tmdb_id, *, name="Breaking Bad", favorite=False, rating=None):
    return {
        "Id": series_id,
        "Type": "Series",
        "Name": name,
        "ProviderIds": {"Tmdb": str(tmdb_id)},
        "UserData": {"Played": False, "IsFavorite": favorite, "Rating": rating},
    }


def _episode(item_id, series_id, season, episode, *, played=True, last_played=None,
             name="Pilot", series_name="Breaking Bad"):
    # Jellyfin episodes carry episode-level provider ids, never the series id.
    return {
        "Id": item_id,
        "Type": "Episode",
        "Name": name,
        "SeriesId": series_id,
        "SeriesName": series_name,
        "ProviderIds": {"Tvdb": "349232"},
        "ParentIndexNumber": season,
        "IndexNumber": episode,
        "UserData": {"Played": played, "LastPlayedDate": last_played},
    }


def _tmdb_not_found(*args, **kwargs):
    """Raise the 404 ProviderAPIError TMDB raises for an unknown id."""
    from app.providers import services

    response = SimpleNamespace(status_code=HTTPStatus.NOT_FOUND)
    error = SimpleNamespace(response=response)
    raise services.ProviderAPIError(Sources.TMDB.value, error)


class JellyfinImportTestCase(TestCase):
    """Shared fixture: a connected Jellyfin account and patched metadata."""

    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user(username="testuser")
        self.account = JellyfinAccount.objects.create(
            user=self.user,
            base_url="https://jellyfin.local",
            api_key=encrypt("api-key"),
            jellyfin_user_id="user-1",
            jellyfin_username="testuser",
        )

    def _run(self, library_items, *, music_items=None, playback_rows=None,
             mode="new", library="all"):
        """Run the importer with the Jellyfin API fully stubbed out."""
        def fake_iter(item_types="Movie,Episode,Series", fields=None,
                      parent_id=None, filters=None):
            if item_types == "Audio":
                return list(music_items or [])
            return list(library_items)

        with (
            patch.object(
                jellyfin.JellyfinClient, "iter_library_items", side_effect=fake_iter
            ),
            patch.object(
                jellyfin.JellyfinClient,
                "fetch_playback_activity",
                return_value=playback_rows,
            ),
        ):
            return jellyfin.importer(library, self.user, mode)


class TestJellyfinWatchedState(JellyfinImportTestCase):
    """Watched movies and episodes from per-item UserData."""

    @patch("integrations.imports.media_server.services.get_media_metadata")
    def test_played_movie_imports_with_last_played_date(self, mock_metadata):
        mock_metadata.return_value = MOVIE_METADATA

        counts, warnings = self._run(
            [_movie("jf-1", 603, last_played="2026-01-15T20:30:00.0000000Z")],
        )

        movie = Movie.objects.get(user=self.user)
        self.assertEqual(movie.item.media_id, "603")
        self.assertEqual(movie.status, Status.COMPLETED.value)
        self.assertEqual(movie.end_date.year, 2026)
        self.assertEqual(movie.end_date.month, 1)
        self.assertEqual(counts.get(MediaTypes.MOVIE.value), 1)
        # No Playback Reporting plugin -> the user is told why.
        self.assertIn("Playback Reporting", warnings)

    @patch("integrations.imports.media_server.services.get_media_metadata")
    def test_unplayed_movie_is_not_imported(self, mock_metadata):
        mock_metadata.return_value = MOVIE_METADATA

        self._run([_movie("jf-1", 603, played=False)])

        self.assertFalse(Movie.objects.filter(user=self.user).exists())

    @patch("integrations.imports.media_server.app.providers.tvdb.enabled",
           return_value=False)
    @patch("integrations.imports.media_server.services.get_media_metadata")
    def test_episode_inherits_show_level_provider_ids(self, mock_metadata, _tvdb):
        mock_metadata.return_value = TV_METADATA

        self._run(
            [
                _series("series-1", 1396),
                _episode("ep-1", "series-1", 1, 1,
                         last_played="2026-02-01T10:00:00Z"),
            ],
        )

        # The episode's own ProviderIds are a TVDB *episode* id; the show must
        # still resolve via the parent Series item's TMDB id.
        tv = TV.objects.get(user=self.user)
        self.assertEqual(tv.item.media_id, "1396")
        episode = Episode.objects.get(related_season__user=self.user)
        self.assertEqual(episode.item.season_number, 1)
        self.assertEqual(episode.item.episode_number, 1)

    @patch("integrations.imports.media_server.app.providers.tvdb.enabled",
           return_value=False)
    @patch("integrations.imports.media_server.services.get_media_metadata")
    def test_unplayed_episode_is_skipped(self, mock_metadata, _tvdb):
        mock_metadata.return_value = TV_METADATA

        self._run(
            [
                _series("series-1", 1396),
                _episode("ep-1", "series-1", 1, 1, played=False),
            ],
        )

        self.assertFalse(Episode.objects.filter(related_season__user=self.user).exists())


class TestJellyfinPlaybackReporting(JellyfinImportTestCase):
    """Per-play history from the optional Playback Reporting plugin."""

    @patch("integrations.imports.media_server.services.get_media_metadata")
    def test_plugin_rows_date_the_entry_from_the_first_real_play(self, mock_metadata):
        """Plugin rows supply the true first-watch date.

        Floppy models one row per media item, so repeat plays collapse into
        a single entry (the Plex importer behaves the same way). What the
        plugin buys is an accurate date: the earliest real play, instead of
        Jellyfin's LastPlayedDate.
        """
        mock_metadata.return_value = MOVIE_METADATA

        counts, warnings = self._run(
            [_movie("jf-1", 603, last_played="2026-03-01T12:00:00Z")],
            playback_rows=[
                {"ItemId": "jf-1", "DateCreated": "2026-01-02 20:00:00"},
                {"ItemId": "jf-1", "DateCreated": "2026-02-03 21:30:00"},
                {"ItemId": "jf-1", "DateCreated": "2026-03-04 22:45:00"},
            ],
        )

        movie = Movie.objects.get(user=self.user)
        self.assertEqual(movie.end_date.month, 1)
        self.assertEqual(movie.end_date.day, 2)
        self.assertEqual(counts.get(MediaTypes.MOVIE.value), 1)
        # Plugin present -> no fallback warning.
        self.assertNotIn("Playback Reporting", warnings)

    @patch("integrations.imports.media_server.services.get_media_metadata")
    def test_missing_plugin_falls_back_to_last_played(self, mock_metadata):
        mock_metadata.return_value = MOVIE_METADATA

        counts, warnings = self._run(
            [_movie("jf-1", 603, last_played="2026-03-01T12:00:00Z")],
            playback_rows=None,
        )

        movie = Movie.objects.get(user=self.user)
        # Without the plugin the only date available is LastPlayedDate.
        self.assertEqual(movie.end_date.month, 3)
        self.assertEqual(counts.get(MediaTypes.MOVIE.value), 1)
        self.assertIn("Playback Reporting", warnings)

    @patch("integrations.imports.media_server.services.get_media_metadata")
    def test_plugin_availability_is_cached_on_the_account(self, mock_metadata):
        mock_metadata.return_value = MOVIE_METADATA

        self._run([_movie("jf-1", 603)], playback_rows=[])

        self.account.refresh_from_db()
        self.assertTrue(self.account.playback_reporting_available)
        self.assertIsNotNone(self.account.playback_reporting_checked_at)

    @patch("integrations.imports.media_server.services.get_media_metadata")
    def test_plugin_absence_is_recorded(self, mock_metadata):
        mock_metadata.return_value = MOVIE_METADATA

        self._run([_movie("jf-1", 603)], playback_rows=None)

        self.account.refresh_from_db()
        self.assertFalse(self.account.playback_reporting_available)


class TestJellyfinRatingsAndFavorites(JellyfinImportTestCase):
    """User ratings and favorites."""

    @patch("integrations.imports.media_server.services.get_media_metadata")
    def test_rating_is_applied_to_watched_movie(self, mock_metadata):
        mock_metadata.return_value = MOVIE_METADATA

        self._run([_movie("jf-1", 603, rating=8.0)])

        movie = Movie.objects.get(user=self.user)
        self.assertEqual(movie.score, 8.0)

    @patch("integrations.imports.media_server.services.get_media_metadata")
    def test_rating_on_unplayed_movie_does_not_mark_it_completed(self, mock_metadata):
        """A rated-but-unwatched movie must not be imported as watched.

        The Plex importer had this exact regression: library ratings were
        harvested for every item, which then created COMPLETED rows for
        things the user had only rated.
        """
        mock_metadata.return_value = MOVIE_METADATA

        self._run([_movie("jf-1", 603, played=False, rating=9.0)])

        self.assertFalse(
            Movie.objects.filter(
                user=self.user, status=Status.COMPLETED.value
            ).exists(),
        )

    @patch("integrations.imports.media_server.services.get_media_metadata")
    def test_unplayed_favorite_becomes_planning(self, mock_metadata):
        mock_metadata.return_value = MOVIE_METADATA

        self._run([_movie("jf-1", 603, played=False, favorite=True)])

        movie = Movie.objects.get(user=self.user)
        self.assertEqual(movie.status, Status.PLANNING.value)

    @patch("integrations.imports.media_server.services.get_media_metadata")
    def test_played_favorite_stays_completed(self, mock_metadata):
        """A favorite the user already watched must not be downgraded."""
        mock_metadata.return_value = MOVIE_METADATA

        self._run([_movie("jf-1", 603, played=True, favorite=True)])

        movie = Movie.objects.get(user=self.user)
        self.assertEqual(movie.status, Status.COMPLETED.value)

    @patch("integrations.imports.media_server.services.get_media_metadata")
    def test_favorite_resolving_to_watched_item_does_not_duplicate(self, mock_metadata):
        """A favorite whose id resolves to an already-imported item must not
        create a second row.

        TMDB can answer with a different canonical media_id than the one
        requested (redirects, title-search fallback), and media_instances is
        keyed by that resolved id — so the dedupe check has to run on the
        resolved id, not the raw one.
        """
        mock_metadata.return_value = MOVIE_METADATA

        self._run(
            [
                _movie("jf-1", 603, played=True,
                       last_played="2026-01-15T20:30:00Z"),
                # Different Jellyfin id and different raw TMDB id, but TMDB
                # resolves it to the same canonical 603.
                _movie("jf-2", 999, played=False, favorite=True,
                       name="Matrix (dupe)"),
            ],
        )

        self.assertEqual(Movie.objects.filter(user=self.user).count(), 1)
        self.assertEqual(
            Movie.objects.get(user=self.user).status,
            Status.COMPLETED.value,
        )

    @patch("integrations.imports.media_server.services.get_media_metadata")
    def test_favorite_already_tracked_is_skipped(self, mock_metadata):
        mock_metadata.return_value = MOVIE_METADATA
        item = Item.objects.create(
            media_id="603",
            source=Sources.TMDB.value,
            media_type=MediaTypes.MOVIE.value,
            title="The Matrix",
            image="matrix.jpg",
        )
        Movie.objects.create(item=item, user=self.user, status=Status.COMPLETED.value)

        self._run([_movie("jf-1", 603, played=False, favorite=True)])

        self.assertEqual(Movie.objects.filter(user=self.user).count(), 1)
        self.assertEqual(
            Movie.objects.get(user=self.user).status,
            Status.COMPLETED.value,
        )


class TestJellyfinMusic(JellyfinImportTestCase):
    """Played audio items routed through the shared scrobble service."""

    @patch("integrations.imports.jellyfin.music_scrobble.record_music_playback")
    @patch("integrations.imports.media_server.services.get_media_metadata")
    def test_played_track_is_scrobbled(self, mock_metadata, mock_record):
        mock_metadata.return_value = MOVIE_METADATA
        mock_record.return_value = None

        self._run(
            [],
            music_items=[
                {
                    "Id": "track-1",
                    "Type": "Audio",
                    "Name": "Paranoid Android",
                    "Album": "OK Computer",
                    "AlbumArtist": "Radiohead",
                    "IndexNumber": 2,
                    "RunTimeTicks": 3_870_000_000,
                    "ProviderIds": {
                        "MusicBrainzTrack": "rec-123",
                        "MusicBrainzAlbum": "rel-456",
                    },
                    "UserData": {"Played": True, "LastPlayedDate": "2026-04-01T09:00:00Z"},
                },
            ],
        )

        mock_record.assert_called_once()
        event = mock_record.call_args.args[0]
        self.assertEqual(event.track_title, "Paranoid Android")
        self.assertEqual(event.artist_name, "Radiohead")
        self.assertEqual(event.album_title, "OK Computer")
        self.assertEqual(event.track_number, 2)
        self.assertEqual(event.duration_ms, 387000)
        self.assertEqual(event.external_ids["musicbrainz_recording"], "rec-123")
        self.assertEqual(event.external_ids["musicbrainz_release"], "rel-456")
        self.assertTrue(event.completed)

    @patch("integrations.imports.jellyfin.music_scrobble.record_music_playback")
    @patch("integrations.imports.media_server.services.get_media_metadata")
    def test_unplayed_track_is_skipped(self, mock_metadata, mock_record):
        mock_metadata.return_value = MOVIE_METADATA

        self._run(
            [],
            music_items=[
                {
                    "Id": "track-1",
                    "Type": "Audio",
                    "Name": "Paranoid Android",
                    "UserData": {"Played": False},
                },
            ],
        )

        mock_record.assert_not_called()

    @patch("integrations.imports.jellyfin.music_scrobble.record_music_playback")
    @patch("integrations.imports.media_server.services.get_media_metadata")
    def test_track_without_album_artist_falls_back_to_artists(
        self, mock_metadata, mock_record
    ):
        mock_metadata.return_value = MOVIE_METADATA
        mock_record.return_value = None

        self._run(
            [],
            music_items=[
                {
                    "Id": "track-1",
                    "Type": "Audio",
                    "Name": "Track",
                    "Artists": ["Solo Artist"],
                    "UserData": {"Played": True},
                },
            ],
        )

        event = mock_record.call_args.args[0]
        self.assertEqual(event.artist_name, "Solo Artist")

    @patch("integrations.imports.jellyfin.music_scrobble.record_music_playback")
    @patch("integrations.imports.media_server.services.get_media_metadata")
    def test_track_with_empty_artists_list_does_not_crash(
        self, mock_metadata, mock_record
    ):
        mock_metadata.return_value = MOVIE_METADATA
        mock_record.return_value = None

        self._run(
            [],
            music_items=[
                {
                    "Id": "track-1",
                    "Type": "Audio",
                    "Name": "Track",
                    "Artists": [],
                    "UserData": {"Played": True},
                },
            ],
        )

        event = mock_record.call_args.args[0]
        self.assertIsNone(event.artist_name)


class TestJellyfinDedupeAndModes(JellyfinImportTestCase):
    """Replay safety and new/overwrite semantics."""

    @patch("integrations.imports.media_server.services.get_media_metadata")
    def test_rerunning_import_creates_no_duplicates(self, mock_metadata):
        mock_metadata.return_value = MOVIE_METADATA
        items = [_movie("jf-1", 603, last_played="2026-01-15T20:30:00Z")]

        self._run(items)
        self.assertEqual(Movie.objects.filter(user=self.user).count(), 1)

        self._run(items)
        self.assertEqual(Movie.objects.filter(user=self.user).count(), 1)

    @patch("integrations.imports.media_server.services.get_media_metadata")
    def test_overwrite_preserves_rows_when_tmdb_metadata_unavailable(
        self, mock_metadata
    ):
        """Overwrite must never delete a row it cannot rebuild."""
        mock_metadata.return_value = MOVIE_METADATA
        item = Item.objects.create(
            media_id="603",
            source=Sources.TMDB.value,
            media_type=MediaTypes.MOVIE.value,
            title="The Matrix",
            image="matrix.jpg",
        )
        Movie.objects.create(
            item=item,
            user=self.user,
            status=Status.COMPLETED.value,
            score=9.0,
        )
        # Now make TMDB unresolvable for the import run itself. A real
        # unresolvable id raises a 404 ProviderAPIError; returning None
        # would still cache the key and look resolvable.
        mock_metadata.side_effect = _tmdb_not_found

        self._run([_movie("jf-1", 603)], mode="overwrite")

        self.assertTrue(Movie.objects.filter(user=self.user, item=item).exists())

    @patch("integrations.imports.media_server.services.get_media_metadata")
    def test_overwrite_preserves_user_score(self, mock_metadata):
        mock_metadata.return_value = MOVIE_METADATA
        item = Item.objects.create(
            media_id="603",
            source=Sources.TMDB.value,
            media_type=MediaTypes.MOVIE.value,
            title="The Matrix",
            image="matrix.jpg",
        )
        Movie.objects.create(
            item=item,
            user=self.user,
            status=Status.COMPLETED.value,
            score=7.5,
        )

        self._run(
            [_movie("jf-1", 603, last_played="2026-01-15T20:30:00Z")],
            mode="overwrite",
        )

        movie = Movie.objects.get(user=self.user)
        self.assertEqual(movie.score, 7.5)


class TestJellyfinLibrarySelection(JellyfinImportTestCase):
    """The library picker scopes the walk to one Jellyfin view."""

    @patch("integrations.imports.media_server.services.get_media_metadata")
    def test_selected_library_is_passed_as_parent_id(self, mock_metadata):
        mock_metadata.return_value = MOVIE_METADATA
        seen = []

        def fake_iter(item_types="Movie,Episode,Series", fields=None,
                      parent_id=None, filters=None):
            seen.append(parent_id)
            return []

        with (
            patch.object(
                jellyfin.JellyfinClient, "iter_library_items", side_effect=fake_iter
            ),
            patch.object(
                jellyfin.JellyfinClient, "fetch_playback_activity", return_value=None
            ),
        ):
            jellyfin.importer("lib-42", self.user, "new")

        self.assertEqual(set(seen), {"lib-42"})

    @patch("integrations.imports.media_server.services.get_media_metadata")
    def test_all_libraries_passes_no_parent_id(self, mock_metadata):
        mock_metadata.return_value = MOVIE_METADATA
        seen = []

        def fake_iter(item_types="Movie,Episode,Series", fields=None,
                      parent_id=None, filters=None):
            seen.append(parent_id)
            return []

        with (
            patch.object(
                jellyfin.JellyfinClient, "iter_library_items", side_effect=fake_iter
            ),
            patch.object(
                jellyfin.JellyfinClient, "fetch_playback_activity", return_value=None
            ),
        ):
            jellyfin.importer("all", self.user, "new")

        self.assertEqual(set(seen), {None})


class TestJellyfinConnectionErrors(TestCase):
    """Connection and configuration failures surface as MediaImportError."""

    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user(username="testuser")

    def test_import_without_account_raises(self):
        with self.assertRaises(MediaImportError):
            jellyfin.importer("all", self.user, "new")


class TestJellyfinDateParsing(TestCase):
    """Jellyfin emits 7-digit fractional seconds, which datetime rejects."""

    def test_parses_seven_digit_fractional_seconds(self):
        parsed = jellyfin._parse_jellyfin_date("2026-01-15T20:30:00.1234567Z")
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed.year, 2026)
        self.assertTrue(timezone.is_aware(parsed))

    def test_parses_plugin_space_separated_format(self):
        parsed = jellyfin._parse_jellyfin_date("2026-01-02 20:00:00")
        self.assertIsNotNone(parsed)
        self.assertTrue(timezone.is_aware(parsed))

    def test_returns_none_for_garbage(self):
        self.assertIsNone(jellyfin._parse_jellyfin_date("not a date"))
        self.assertIsNone(jellyfin._parse_jellyfin_date(None))
        self.assertIsNone(jellyfin._parse_jellyfin_date(""))


class TestJellyfinImportView(TestCase):
    """The Import Data POST endpoint."""

    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user(username="testuser", password="pw12345!")
        self.client.force_login(self.user)
        JellyfinAccount.objects.create(
            user=self.user,
            base_url="https://jellyfin.local",
            api_key=encrypt("api-key"),
            jellyfin_user_id="user-1",
            jellyfin_username="testuser",
        )

    @patch("integrations.tasks.import_jellyfin.delay")
    def test_one_shot_import_queues_task(self, mock_delay):
        response = self.client.post(
            "/import/jellyfin",
            {"library": "lib-1", "mode": "new", "frequency": "once"},
        )

        self.assertEqual(response.status_code, 302)
        mock_delay.assert_called_once_with(
            library="lib-1",
            user_id=self.user.id,
            mode="new",
        )

    @patch("integrations.tasks.import_jellyfin.delay")
    def test_recurring_import_creates_periodic_task(self, mock_delay):
        response = self.client.post(
            "/import/jellyfin",
            {
                "library": "all",
                "mode": "new",
                "frequency": "daily",
                "time": "03:00",
            },
        )

        self.assertEqual(response.status_code, 302)
        mock_delay.assert_not_called()
        self.assertTrue(
            PeriodicTask.objects.filter(task="Import from Jellyfin").exists(),
        )

    def test_import_without_account_redirects(self):
        JellyfinAccount.objects.all().delete()

        response = self.client.post("/import/jellyfin", {"library": "all"})

        self.assertEqual(response.status_code, 302)


class TestJellyfinImportProbes(TestCase):
    """The Import Data page's async status/library probes."""

    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user(username="testuser", password="pw12345!")
        self.client.force_login(self.user)

    def _connect(self):
        return JellyfinAccount.objects.create(
            user=self.user,
            base_url="https://jellyfin.local",
            api_key=encrypt("api-key"),
            jellyfin_user_id="user-1",
        )

    def test_status_reports_disconnected_without_account(self):
        response = self.client.get("/settings/import/jellyfin-status")

        self.assertEqual(response.json()["state"], "disconnected")

    @patch("integrations.jellyfin_client.JellyfinClient.healthcheck")
    def test_status_reports_connected(self, mock_health):
        self._connect()
        mock_health.return_value = {"Version": "10.9"}

        response = self.client.get("/settings/import/jellyfin-status")

        self.assertEqual(response.json()["state"], "connected")

    @patch("integrations.jellyfin_client.JellyfinClient.healthcheck")
    def test_status_reports_error_on_bad_key(self, mock_health):
        from integrations.jellyfin_client import JellyfinAuthError

        self._connect()
        mock_health.side_effect = JellyfinAuthError("bad key")

        response = self.client.get("/settings/import/jellyfin-status")

        data = response.json()
        self.assertEqual(data["state"], "error")
        self.assertIn("invalid", data["error"])

    @patch("integrations.jellyfin_client.JellyfinClient.get_views")
    def test_libraries_are_cached_on_the_account(self, mock_views):
        account = self._connect()
        mock_views.return_value = [
            {"Id": "lib-1", "Name": "Movies", "CollectionType": "movies"},
            {"Id": "lib-2", "Name": "Shows", "CollectionType": "tvshows"},
        ]

        response = self.client.get("/settings/import/jellyfin-libraries")

        libraries = response.json()["libraries"]
        self.assertEqual([lib["id"] for lib in libraries], ["lib-1", "lib-2"])
        account.refresh_from_db()
        self.assertEqual(len(account.libraries), 2)
        self.assertIsNotNone(account.libraries_refreshed_at)

    @patch("integrations.jellyfin_client.JellyfinClient.get_views")
    def test_fresh_cache_is_not_refetched(self, mock_views):
        account = self._connect()
        account.libraries = [{"id": "lib-1", "title": "Movies", "type": "movies"}]
        account.libraries_refreshed_at = timezone.now()
        account.save()

        response = self.client.get("/settings/import/jellyfin-libraries")

        mock_views.assert_not_called()
        self.assertEqual(len(response.json()["libraries"]), 1)

    @patch("integrations.jellyfin_client.JellyfinClient.get_views")
    def test_library_fetch_failure_returns_cached_values(self, mock_views):
        from integrations.jellyfin_client import JellyfinClientError

        account = self._connect()
        account.libraries = [{"id": "lib-1", "title": "Movies", "type": "movies"}]
        account.save()
        mock_views.side_effect = JellyfinClientError("server down")

        response = self.client.get("/settings/import/jellyfin-libraries")

        data = response.json()
        self.assertEqual(len(data["libraries"]), 1)
        self.assertIn("server down", data["error"])


class TestJellyfinTaskRegistration(TestCase):
    """The Celery tasks must be registered under their scheduled names."""

    def test_tasks_are_registered(self):
        from integrations import tasks

        self.assertEqual(tasks.import_jellyfin.name, "Import from Jellyfin")
        self.assertEqual(
            tasks.import_jellyfin_recurring.name,
            "Import from Jellyfin (Recurring)",
        )

    def test_import_run_appears_in_import_activity(self):
        """get_import_tasks drives the Import Activity panel.

        Without a "jellyfin" entry in its task-name map, a completed
        Jellyfin import would never be shown back to the user.
        """
        from django_celery_results.models import TaskResult

        User = get_user_model()
        user = User.objects.create_user(username="listuser")
        TaskResult.objects.create(
            task_id="jellyfin-task",
            task_name="Import from Jellyfin",
            task_kwargs=f"{{'user_id': {user.id}}}",
            status="SUCCESS",
            date_done=timezone.now(),
            result="{}",
        )

        import_tasks = user.get_import_tasks()

        self.assertTrue(
            any(entry["source"] == "jellyfin" for entry in import_tasks["results"]),
        )


class TestJellyfinSeasonRollup(JellyfinImportTestCase):
    """Episodes roll up into Season and TV rows."""

    @patch("integrations.imports.media_server.app.providers.tvdb.enabled",
           return_value=False)
    @patch("integrations.imports.media_server.services.get_media_metadata")
    def test_multiple_episodes_create_one_season(self, mock_metadata, _tvdb):
        mock_metadata.return_value = TV_METADATA

        self._run(
            [
                _series("series-1", 1396),
                _episode("ep-1", "series-1", 1, 1,
                         last_played="2026-02-01T10:00:00Z"),
                _episode("ep-2", "series-1", 1, 2, name="Cat's in the Bag",
                         last_played="2026-02-02T10:00:00Z"),
            ],
        )

        self.assertEqual(TV.objects.filter(user=self.user).count(), 1)
        self.assertEqual(Season.objects.filter(user=self.user).count(), 1)
        self.assertEqual(
            Episode.objects.filter(related_season__user=self.user).count(),
            2,
        )
