"""A web worker must be bounded by what it holds, not only by what it served.

``max_requests`` counts requests. Floppy's expensive pages cost hundreds of
times an ordinary one, so a worker can grow for hours without reaching the
count: production showed a worker at 567 MiB of private memory after three
hours, never recycled, because real traffic had not served 500 requests yet.
"""

import importlib
import os
import sys
from pathlib import Path
from unittest import skipUnless
from unittest.mock import patch

from django.conf import settings
from django.test import SimpleTestCase

sys.path.insert(0, str(Path(settings.BASE_DIR)))


def load_config(tier="standard", **environment):
    """Import config.gunicorn fresh under a given tier and environment."""
    values = {"FLOPPY_RESOURCE_TIER": tier, **environment}
    with patch.dict(os.environ, values, clear=False):
        for module in ("config.runtime_profile", "config.gunicorn"):
            sys.modules.pop(module, None)
        return importlib.import_module("config.gunicorn")


class Worker:
    """The single attribute gunicorn's arbiter reads to retire a worker."""

    def __init__(self):
        """Start alive, as the arbiter's own worker does."""
        self.alive = True


class WorkerMemoryCeilingTests(SimpleTestCase):
    """The ceiling exists, scales with the host, and only fires when crossed."""

    def tearDown(self):
        """Leave no patched module behind for the next test to import."""
        for module in ("config.runtime_profile", "config.gunicorn"):
            sys.modules.pop(module, None)

    def test_every_tier_bounds_worker_memory(self):
        """No tier may leave a web worker free to grow without limit."""
        for tier in ("minimal", "constrained", "standard"):
            with self.subTest(tier=tier):
                self.assertGreater(load_config(tier).max_worker_memory_bytes, 0)

    def test_smaller_hosts_recycle_sooner(self):
        """The ceiling must rise with the tier, never fall."""
        minimal = load_config("minimal").max_worker_memory_bytes
        constrained = load_config("constrained").max_worker_memory_bytes
        standard = load_config("standard").max_worker_memory_bytes

        self.assertLess(minimal, constrained)
        self.assertLess(constrained, standard)

    def test_the_ceiling_clears_a_preloaded_worker(self):
        """A ceiling near a fresh worker's size would retire it immediately.

        With preload_app a fresh worker's RSS counts the shared application
        image, roughly 100 MiB, so the ceiling must sit well above it or the
        first request would retire the worker that served it.
        """
        preloaded_worker_bytes = 100 * 1024 * 1024
        for tier in ("minimal", "constrained", "standard"):
            with self.subTest(tier=tier):
                self.assertGreater(
                    load_config(tier).max_worker_memory_bytes,
                    preloaded_worker_bytes * 1.4,
                )

    def test_a_worker_under_the_ceiling_keeps_serving(self):
        """The common case must not touch the worker."""
        module = load_config("standard")
        worker = Worker()
        with patch.object(module, "_worker_rss_bytes", return_value=1024):
            module.post_request(worker, None, None, None)

        self.assertTrue(worker.alive)

    def test_a_worker_over_the_ceiling_is_retired(self):
        """Crossing the ceiling marks the worker for a graceful exit."""
        module = load_config("standard")
        worker = Worker()
        over = module.max_worker_memory_bytes + 1
        with patch.object(module, "_worker_rss_bytes", return_value=over):
            module.post_request(worker, None, None, None)

        self.assertFalse(worker.alive)

    def test_an_unreadable_rss_never_retires_a_worker(self):
        """Where /proc is absent the ceiling must not fire on a guess."""
        module = load_config("standard")
        worker = Worker()
        with patch.object(module, "_worker_rss_bytes", return_value=None):
            module.post_request(worker, None, None, None)

        self.assertTrue(worker.alive)

    def test_the_ceiling_can_be_turned_off(self):
        """An operator must be able to opt out without editing the image."""
        module = load_config(
            "standard",
            FLOPPY_GUNICORN_MAX_WORKER_MEMORY_BYTES="0",
        )
        worker = Worker()
        with patch.object(module, "_worker_rss_bytes", return_value=1 << 40):
            module.post_request(worker, None, None, None)

        self.assertEqual(module.max_worker_memory_bytes, 0)
        self.assertTrue(worker.alive)

    @skipUnless(sys.platform == "linux", "reads /proc/self/statm")
    def test_the_reported_rss_is_this_process(self):
        """The hook must read a real resident size, not a constant."""
        module = load_config("standard")
        resident = module._worker_rss_bytes()

        self.assertIsNotNone(resident)
        self.assertGreater(resident, 1024 * 1024)
