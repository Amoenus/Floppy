import os
from importlib import import_module
from unittest.mock import patch

from django.conf import settings
from django.core.cache import cache
from django.test import TestCase, override_settings

from app.apps import AppConfig as FloppyAppConfig
from app.tasks import GENRE_BACKFILL_VERSION, WATCH_PROVIDERS_BACKFILL_VERSION


class AppStartupTests(TestCase):
    @override_settings(
        TESTING=False,
        DISCOVER_WARMUP_ON_STARTUP=False,
        RUNTIME_POPULATION_ON_STARTUP=False,
    )
    @patch("app.apps.sys.argv", ["gunicorn"])
    @patch("app.apps._is_celery_worker_process", return_value=False)
    def test_app_ready_schedules_genre_backfill_reconcile(
        self,
        _mock_is_celery_worker,
    ):
        config = FloppyAppConfig("app", import_module("app"))

        with (
            patch.object(config, "_repair_celery_redis_bindings"),
            patch.object(config, "_schedule_history_day_coverage_warmup"),
            patch.object(config, "_schedule_imdb_game_person_profile_backfill"),
            patch.object(config, "_schedule_genre_backfill_reconcile") as mock_schedule,
            patch.object(config, "_schedule_trakt_popularity_reconcile"),
            patch.object(config, "_schedule_igdb_rating_backfill_reconcile"),
            patch.object(config, "_schedule_provider_backfill_reconcile"),
        ):
            config.ready()

        mock_schedule.assert_called_once_with()

    @override_settings(
        TESTING=False,
        DISCOVER_WARMUP_ON_STARTUP=False,
        RUNTIME_POPULATION_ON_STARTUP=False,
    )
    @patch.dict(os.environ, {"RUN_MAIN": "false"}, clear=False)
    @patch("app.apps.sys.argv", ["manage.py", "runserver"])
    @patch("app.apps._is_celery_worker_process", return_value=False)
    def test_app_ready_skips_startup_scheduling_in_runserver_parent(
        self,
        _mock_is_celery_worker,
    ):
        config = FloppyAppConfig("app", import_module("app"))

        with (
            patch.object(config, "_repair_celery_redis_bindings"),
            patch.object(
                config, "_schedule_history_day_coverage_warmup"
            ) as mock_history,
            patch.object(
                config, "_schedule_imdb_game_person_profile_backfill"
            ) as mock_imdb,
            patch.object(config, "_schedule_genre_backfill_reconcile") as mock_genre,
            patch.object(config, "_schedule_trakt_popularity_reconcile") as mock_trakt,
        ):
            config.ready()

        mock_history.assert_not_called()
        mock_imdb.assert_not_called()
        mock_genre.assert_not_called()
        mock_trakt.assert_not_called()

    @override_settings(
        TESTING=False,
        DISCOVER_WARMUP_ON_STARTUP=False,
        RUNTIME_POPULATION_ON_STARTUP=False,
    )
    @patch("app.apps.sys.argv", ["manage.py", "migrate", "--noinput"])
    @patch("app.apps._is_celery_worker_process", return_value=False)
    def test_app_ready_skips_startup_scheduling_in_management_command(
        self,
        _mock_is_celery_worker,
    ):
        cache.delete("history_day_coverage_startup_scheduled")
        config = FloppyAppConfig("app", import_module("app"))

        with (
            patch.object(config, "_repair_celery_redis_bindings") as mock_repair,
            patch.object(
                config,
                "_schedule_history_day_coverage_warmup",
            ) as mock_history,
            patch.object(
                config,
                "_schedule_imdb_game_person_profile_backfill",
            ) as mock_imdb,
            patch.object(config, "_schedule_genre_backfill_reconcile") as mock_genre,
            patch.object(config, "_schedule_trakt_popularity_reconcile") as mock_trakt,
        ):
            config.ready()

        mock_repair.assert_not_called()
        mock_history.assert_not_called()
        mock_imdb.assert_not_called()
        mock_genre.assert_not_called()
        mock_trakt.assert_not_called()
        # The once-per-day startup cache keys must remain available for the
        # serving process that starts afterwards.
        self.assertIsNone(cache.get("history_day_coverage_startup_scheduled"))

    def test_is_management_command_process_detection(self):
        from app.apps import _is_management_command_process

        cases = [
            (["manage.py", "migrate", "--noinput"], True),
            (["manage.py", "check"], True),
            (["manage.py", "shell"], True),
            (["/floppy/manage.py", "collectstatic"], True),
            (["manage.py", "runserver"], False),
            (["manage.py", "runserver", "0.0.0.0:8000"], False),
            (["gunicorn", "config.wsgi:application"], False),
            (["celery", "-A", "config", "worker"], False),
            ([], False),
        ]
        for argv, expected in cases:
            with patch("app.apps.sys.argv", argv):
                self.assertEqual(_is_management_command_process(), expected, argv)

    @patch(
        "app.tasks_imdb.schedule_imdb_game_person_profile_backfill_if_needed.apply_async"
    )
    def test_schedule_imdb_game_person_profile_backfill_uses_background_priority(
        self,
        mock_apply_async,
    ):
        # The missing-profile count check must not run in AppConfig.ready(),
        # since preload_app executes it pre-fork in the Gunicorn master
        # (issue #335); it belongs inside the Celery task instead.
        config = FloppyAppConfig("app", import_module("app"))

        config._schedule_imdb_game_person_profile_backfill()

        mock_apply_async.assert_called_once_with(
            countdown=0,
            priority=settings.CELERY_TASK_PRIORITY_BACKGROUND,
        )

    @patch(
        "app.services.imdb_game_credits.count_people_missing_profiles", return_value=12
    )
    @patch("app.tasks_imdb.refresh_imdb_game_credits_from_datasets.apply_async")
    def test_schedule_imdb_game_person_profile_backfill_task_queues_refresh_when_missing(
        self,
        mock_apply_async,
        _mock_missing_count,
    ):
        from app.tasks_imdb import (
            schedule_imdb_game_person_profile_backfill_if_needed,
        )

        schedule_imdb_game_person_profile_backfill_if_needed()

        mock_apply_async.assert_called_once_with()

    @patch(
        "app.services.imdb_game_credits.count_people_missing_profiles", return_value=0
    )
    @patch("app.tasks_imdb.refresh_imdb_game_credits_from_datasets.apply_async")
    def test_schedule_imdb_game_person_profile_backfill_task_skips_when_nothing_missing(
        self,
        mock_apply_async,
        _mock_missing_count,
    ):
        from app.tasks_imdb import (
            schedule_imdb_game_person_profile_backfill_if_needed,
        )

        schedule_imdb_game_person_profile_backfill_if_needed()

        mock_apply_async.assert_not_called()

    @patch("app.tasks.reconcile_genre_backfill.apply_async")
    def test_schedule_genre_backfill_reconcile_marks_pending_until_worker_runs(
        self,
        mock_apply_async,
    ):
        version_key = f"genre_backfill_reconciled_v{GENRE_BACKFILL_VERSION}"
        cache.delete(version_key)
        config = FloppyAppConfig("app", import_module("app"))

        config._schedule_genre_backfill_reconcile()
        config._schedule_genre_backfill_reconcile()

        mock_apply_async.assert_called_once_with(
            kwargs={"strategy_version": GENRE_BACKFILL_VERSION},
            countdown=0,
            priority=settings.CELERY_TASK_PRIORITY_BACKGROUND,
        )
        self.assertEqual(cache.get(version_key), "pending")

        cache.set(version_key, "done", timeout=None)
        config._schedule_genre_backfill_reconcile()

        mock_apply_async.assert_called_once()

    @patch("app.tasks.is_genre_backfill_reconcile_complete")
    @patch("app.tasks.reconcile_genre_backfill.apply_async")
    def test_schedule_genre_backfill_reconcile_skips_done_cache_without_db_check(
        self,
        mock_apply_async,
        mock_is_complete,
    ):
        version_key = f"genre_backfill_reconciled_v{GENRE_BACKFILL_VERSION}"
        cache.set(version_key, "done", timeout=None)
        config = FloppyAppConfig("app", import_module("app"))

        config._schedule_genre_backfill_reconcile()

        mock_apply_async.assert_not_called()
        mock_is_complete.assert_not_called()

    @patch("app.tasks.reconcile_provider_backfill.apply_async")
    def test_schedule_provider_backfill_reconcile_marks_pending_until_worker_runs(
        self,
        mock_apply_async,
    ):
        version_key = (
            f"watch_providers_backfill_reconciled_v{WATCH_PROVIDERS_BACKFILL_VERSION}"
        )
        cache.delete(version_key)
        config = FloppyAppConfig("app", import_module("app"))

        config._schedule_provider_backfill_reconcile()
        config._schedule_provider_backfill_reconcile()

        mock_apply_async.assert_called_once_with(
            kwargs={"strategy_version": WATCH_PROVIDERS_BACKFILL_VERSION},
            countdown=30,
            priority=settings.CELERY_TASK_PRIORITY_BACKGROUND,
        )
        self.assertEqual(cache.get(version_key), "pending")

        cache.set(version_key, "done", timeout=None)
        config._schedule_provider_backfill_reconcile()

        mock_apply_async.assert_called_once()

    @patch("app.tasks.is_provider_backfill_reconcile_complete")
    @patch("app.tasks.reconcile_provider_backfill.apply_async")
    def test_schedule_provider_backfill_reconcile_skips_done_cache_without_db_check(
        self,
        mock_apply_async,
        mock_is_complete,
    ):
        version_key = (
            f"watch_providers_backfill_reconciled_v{WATCH_PROVIDERS_BACKFILL_VERSION}"
        )
        cache.set(version_key, "done", timeout=None)
        config = FloppyAppConfig("app", import_module("app"))

        config._schedule_provider_backfill_reconcile()

        mock_apply_async.assert_not_called()
        mock_is_complete.assert_not_called()

    def test_settings_include_provider_backfill_reconcile_fallback_schedule(self):
        schedule = settings.CELERY_BEAT_SCHEDULE["ensure_provider_backfill_reconcile"]

        self.assertEqual(schedule["task"], "Ensure watch provider backfill reconcile")
        self.assertEqual(schedule["schedule"], 60 * 5)
        self.assertEqual(schedule["kwargs"]["batch_size"], 1500)
        self.assertEqual(
            schedule["options"]["priority"],
            settings.CELERY_TASK_PRIORITY_BACKGROUND,
        )

    def test_settings_include_genre_backfill_reconcile_fallback_schedule(self):
        schedule = settings.CELERY_BEAT_SCHEDULE["ensure_genre_backfill_reconcile"]

        self.assertEqual(schedule["task"], "Ensure genre backfill reconcile")
        self.assertEqual(schedule["schedule"], 60 * 5)
        self.assertEqual(schedule["kwargs"]["batch_size"], 1500)
        self.assertEqual(
            schedule["options"]["priority"],
            settings.CELERY_TASK_PRIORITY_BACKGROUND,
        )

    def test_celery_background_routes_and_prefetch_are_enabled(self):
        self.assertEqual(settings.CELERY_WORKER_PREFETCH_MULTIPLIER, 1)
        self.assertEqual(
            settings.CELERY_TASK_ROUTES["app.tasks.populate_*"]["priority"],
            settings.CELERY_TASK_PRIORITY_BACKGROUND,
        )
        self.assertEqual(
            settings.CELERY_TASK_ROUTES["Backfill item metadata"]["priority"],
            settings.CELERY_TASK_PRIORITY_BACKGROUND,
        )
        self.assertEqual(
            settings.CELERY_TASK_ROUTES["Warm History Day Cache Coverage"]["priority"],
            settings.CELERY_TASK_PRIORITY_BACKGROUND,
        )
        self.assertEqual(
            settings.CELERY_TASK_ROUTES["Repair History Day Cache Coverage"][
                "priority"
            ],
            settings.CELERY_TASK_PRIORITY_BACKGROUND,
        )

    @patch("app.tasks.warm_history_day_cache_coverage.apply_async")
    def test_schedule_history_day_coverage_warmup_uses_background_priority(
        self,
        mock_apply_async,
    ):
        config = FloppyAppConfig("app", import_module("app"))

        config._schedule_history_day_coverage_warmup()

        mock_apply_async.assert_called_once_with(
            countdown=300,
            priority=settings.CELERY_TASK_PRIORITY_BACKGROUND,
        )

    def test_settings_include_history_day_coverage_fallback_schedule(self):
        schedule = settings.CELERY_BEAT_SCHEDULE["warm_history_day_cache_coverage"]

        self.assertEqual(schedule["task"], "Warm History Day Cache Coverage")
        self.assertEqual(schedule["schedule"], 60 * 60 * 2)
        self.assertEqual(
            schedule["options"]["priority"],
            settings.CELERY_TASK_PRIORITY_BACKGROUND,
        )
