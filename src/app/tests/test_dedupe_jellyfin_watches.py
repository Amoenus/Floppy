"""Tests for the dedupe_jellyfin_watches repair command."""

from datetime import UTC, datetime, timedelta
from datetime import timezone as dt_timezone
from io import StringIO

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase

from app.models import (
    TV,
    Episode,
    Item,
    MediaTypes,
    Movie,
    MoviePlay,
    Season,
    Sources,
    Status,
)


class DedupeJellyfinWatchesTests(TestCase):
    """The command collapses near-duplicate webhook/import watch entries."""

    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="watcher",
            password="12345",
        )

    def _run(self, *args):
        out = StringIO()
        call_command("dedupe_jellyfin_watches", *args, stdout=out)
        return out.getvalue()

    def _episode_setup(self):
        tv_item = Item.objects.create(
            media_id="series-1",
            source=Sources.TVDB.value,
            media_type=MediaTypes.TV.value,
            title="Show",
        )
        tv = TV.objects.create(
            user=self.user,
            item=tv_item,
            status=Status.IN_PROGRESS.value,
        )
        season_item = Item.objects.create(
            media_id="series-1",
            source=Sources.TVDB.value,
            media_type=MediaTypes.SEASON.value,
            title="Season 1",
            season_number=1,
        )
        season = Season.objects.create(
            user=self.user,
            item=season_item,
            related_tv=tv,
            status=Status.IN_PROGRESS.value,
        )
        episode_item = Item.objects.create(
            media_id="series-1",
            source=Sources.TVDB.value,
            media_type=MediaTypes.EPISODE.value,
            title="Episode",
            season_number=1,
            episode_number=1,
        )
        return season, episode_item

    def test_dry_run_reports_without_deleting(self):
        season, episode_item = self._episode_setup()
        webhook_time = datetime(2024, 1, 2, 3, 34, 0, tzinfo=UTC)
        import_time = webhook_time - timedelta(minutes=30)
        Episode.objects.create(
            item=episode_item,
            related_season=season,
            end_date=webhook_time,
            watch_operation_id=None,
        )
        Episode.objects.create(
            item=episode_item,
            related_season=season,
            end_date=import_time,
            watch_operation_id="11111111-1111-1111-1111-111111111111",
        )

        output = self._run()

        self.assertIn("DRY RUN", output)
        self.assertEqual(Episode.objects.count(), 2)
        self.assertIn("to remove", output)

    def test_apply_collapses_episode_duplicates_keeping_provenance(self):
        season, episode_item = self._episode_setup()
        webhook_time = datetime(2024, 1, 2, 3, 34, 0, tzinfo=UTC)
        import_time = webhook_time - timedelta(minutes=30)
        webhook_episode = Episode.objects.create(
            item=episode_item,
            related_season=season,
            end_date=webhook_time,
        )
        import_episode = Episode.objects.create(
            item=episode_item,
            related_season=season,
            end_date=import_time,
            watch_operation_id="11111111-1111-1111-1111-111111111111",
        )

        self._run("--apply")

        self.assertEqual(Episode.objects.count(), 1)
        remaining = Episode.objects.get()
        self.assertEqual(remaining.pk, import_episode.pk)
        self.assertFalse(Episode.objects.filter(pk=webhook_episode.pk).exists())

    def test_apply_leaves_genuine_rewatch_outside_window_alone(self):
        season, episode_item = self._episode_setup()
        first_watch = datetime(2024, 1, 2, 3, 34, 0, tzinfo=UTC)
        rewatch = first_watch + timedelta(days=30)
        Episode.objects.create(
            item=episode_item,
            related_season=season,
            end_date=first_watch,
        )
        Episode.objects.create(
            item=episode_item,
            related_season=season,
            end_date=rewatch,
        )

        self._run("--apply")

        self.assertEqual(Episode.objects.count(), 2)

    def test_apply_collapses_movie_play_duplicates(self):
        item = Item.objects.create(
            media_id="movie-1",
            source=Sources.TMDB.value,
            media_type=MediaTypes.MOVIE.value,
            title="A Movie",
        )
        movie = Movie.objects.create(
            item=item,
            user=self.user,
            status=Status.COMPLETED.value,
        )
        webhook_time = datetime(2024, 1, 2, 3, 34, 0, tzinfo=UTC)
        import_time = webhook_time - timedelta(minutes=20)
        webhook_play = MoviePlay.objects.create(movie=movie, end_date=webhook_time)
        import_play = MoviePlay.objects.create(
            movie=movie,
            end_date=import_time,
            external_id="jellyfin-playback-reporting:hash:abc",
        )

        self._run("--apply")

        self.assertEqual(MoviePlay.objects.filter(movie=movie).count(), 1)
        remaining = MoviePlay.objects.get(movie=movie)
        self.assertEqual(remaining.pk, import_play.pk)
        self.assertFalse(MoviePlay.objects.filter(pk=webhook_play.pk).exists())

    def test_username_filter_scopes_to_one_user(self):
        other_user = get_user_model().objects.create_user(
            username="other",
            password="12345",
        )
        season, episode_item = self._episode_setup()
        webhook_time = datetime(2024, 1, 2, 3, 34, 0, tzinfo=UTC)
        Episode.objects.create(
            item=episode_item,
            related_season=season,
            end_date=webhook_time,
        )
        Episode.objects.create(
            item=episode_item,
            related_season=season,
            end_date=webhook_time - timedelta(minutes=10),
        )

        self._run("--apply", "--username", other_user.username)

        self.assertEqual(Episode.objects.count(), 2)
