"""Tests for per-process DB_POOL_MAX sizing (issue #548)."""

from django.test import SimpleTestCase

from config.settings import _DB_POOL_MAX_FLOOR, _db_pool_max_default


class DbPoolMaxDefaultTests(SimpleTestCase):
    """Deriving DB_POOL_MAX's default from the current process's own role."""

    def test_minimal_tier_gunicorn_is_unchanged(self):
        """Gunicorn's formula must stay byte-identical to the #341 fix."""
        result = _db_pool_max_default(
            is_celery=False,
            gunicorn_threads=2,
            celery_concurrency=1,
            pool_min=2,
        )
        self.assertEqual(result, 3)

    def test_standard_tier_gunicorn_is_unchanged(self):
        """A generous host's gunicorn pool sizing is untouched by this fix."""
        result = _db_pool_max_default(
            is_celery=False,
            gunicorn_threads=4,
            celery_concurrency=1,
            pool_min=2,
        )
        self.assertEqual(result, 5)

    def test_minimal_tier_celery_gets_the_historical_floor(self):
        """The #548 regression: Celery/beat must not be squeezed to 3."""
        result = _db_pool_max_default(
            is_celery=True,
            gunicorn_threads=2,
            celery_concurrency=1,
            pool_min=2,
        )
        self.assertEqual(result, _DB_POOL_MAX_FLOOR)

    def test_celery_scales_up_with_worker_concurrency(self):
        """Raising CELERY_WORKER_CONCURRENCY must raise its own pool size."""
        result = _db_pool_max_default(
            is_celery=True,
            gunicorn_threads=2,
            celery_concurrency=8,
            pool_min=2,
        )
        self.assertEqual(result, 9)
