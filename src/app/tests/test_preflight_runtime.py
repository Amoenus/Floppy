"""Cover the preflight runtime check.

This check is how an operator answers two questions without any access to the
container's internals: which build is running, and how many resident processes
it decided to start. It must never fail a boot -- everything it reports is
informational, so an override or a stale identity is a warning.
"""

import json
import shutil
import tempfile
from pathlib import Path
from unittest.mock import patch

from django.test import SimpleTestCase

from app import preflight
from app.preflight import FAIL, OK, WARN, build_report, check_runtime


class RuntimeCheckTests(SimpleTestCase):
    """The check reports topology and identity, and warns without failing."""

    def setUp(self):
        """Point the file-backed inputs somewhere that does not exist."""
        missing = Path("/nonexistent/floppy-preflight-test")
        patcher = patch.object(preflight, "_BUILD_INFO_PATH", missing)
        patcher.start()
        self.addCleanup(patcher.stop)
        boot = patch.object(preflight, "_BOOT_SIZING_PATH", missing)
        boot.start()
        self.addCleanup(boot.stop)

    def test_reports_topology_without_an_override(self):
        """With nothing overridden the check passes and names the processes."""
        with patch.dict("os.environ", {}, clear=False) as _:
            result = check_runtime()

        self.assertEqual(result.status, OK)
        self.assertFalse(result.failed)
        self.assertEqual(result.facts["web_concurrency_source"], "auto")
        self.assertIn("gunicorn", result.facts["expected_programs"])

    def test_expected_programs_follow_the_queue_plan(self):
        """The process list is derived, so it cannot name a worker that is off.

        celery-discover is never started on any tier; a hand-written list would
        claim it is resident and send someone hunting for a process.
        """
        result = check_runtime()

        self.assertEqual(
            "celery-discover" in result.facts["expected_programs"],
            result.facts["start_discover_worker"],
        )

    def test_explicit_worker_count_warns_but_does_not_fail(self):
        """An override is reported against what the host would have chosen."""
        with patch.dict("os.environ", {"WEB_CONCURRENCY": "2"}, clear=False):
            result = check_runtime()

        self.assertEqual(result.status, WARN)
        self.assertFalse(result.failed)
        self.assertEqual(result.facts["web_concurrency"], 2)
        self.assertEqual(result.facts["web_concurrency_default"], 1)
        self.assertEqual(result.facts["web_concurrency_source"], "override")
        self.assertIn("WEB_CONCURRENCY", result.fix)
        self.assertTrue(build_report([result])["ok"])

    def test_a_recorded_source_beats_an_inherited_value(self):
        """Supervisord's children inherit the value emit_env itself wrote.

        Without the recorded source every supervised process would read its own
        inherited WEB_CONCURRENCY as an operator override.
        """
        environment = {
            "WEB_CONCURRENCY": "1",
            "FLOPPY_WEB_CONCURRENCY_SOURCE": "auto",
        }
        with patch.dict("os.environ", environment, clear=False):
            result = check_runtime()

        self.assertEqual(result.status, OK)
        self.assertEqual(result.facts["web_concurrency_source"], "auto")

    def test_unparseable_worker_count_warns(self):
        """A non-numeric value is silently ignored, so it has to be surfaced."""
        with patch.dict("os.environ", {"WEB_CONCURRENCY": "two"}, clear=False):
            result = check_runtime()

        self.assertEqual(result.status, WARN)
        self.assertEqual(result.facts["web_concurrency_source"], "invalid")
        self.assertEqual(result.facts["web_concurrency"], 1)


class BuildIdentityTests(SimpleTestCase):
    """Identity has to say where it came from, not just what it is."""

    def _write_build_info(self, commit):
        """Point the check at a build-info file carrying this commit."""
        directory = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, directory, True)
        path = Path(directory) / "floppy-build-info"
        path.write_text(f"VERSION=test\nCOMMIT_SHA={commit}\n")
        patcher = patch.object(preflight, "_BUILD_INFO_PATH", path)
        patcher.start()
        self.addCleanup(patcher.stop)
        return path

    def setUp(self):
        """Keep the boot-sizing file out of these cases."""
        patcher = patch.object(
            preflight,
            "_BOOT_SIZING_PATH",
            Path("/nonexistent/floppy-boot-sizing.json"),
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_a_git_checkout_is_reported_as_such(self):
        """Running from source is a different provenance from a built image."""
        self._write_build_info("deadbeef")
        with patch.object(preflight.settings, "LOCAL_COMMIT_SHA", "abc1234"):
            result = check_runtime()

        self.assertEqual(result.facts["identity_source"], "git-checkout")

    def test_image_identity_is_reported_when_there_is_no_checkout(self):
        """A built image has no .git, so the baked file is the only source."""
        self._write_build_info("abc1234")
        with (
            patch.object(preflight.settings, "LOCAL_COMMIT_SHA", None),
            patch.object(preflight.settings, "COMMIT_SHA", "abc1234"),
        ):
            result = check_runtime()

        self.assertEqual(result.facts["identity_source"], "image")
        self.assertTrue(result.facts["build_info_matches_settings"])
        self.assertEqual(result.status, OK)

    def test_shadowed_identity_warns(self):
        """A stale COMMIT_SHA in the environment must not pass unnoticed.

        This is the failure a real deployment hit: an orchestrator's persisted
        environment shadowing the identity baked into the image.
        """
        self._write_build_info("abc1234")
        with (
            patch.object(preflight.settings, "LOCAL_COMMIT_SHA", None),
            patch.object(preflight.settings, "COMMIT_SHA", "stale999"),
        ):
            result = check_runtime()

        self.assertEqual(result.status, WARN)
        self.assertFalse(result.failed)
        self.assertFalse(result.facts["build_info_matches_settings"])


class BootSizingTests(SimpleTestCase):
    """A docker exec re-probes the host; the boot record is the real answer."""

    def _write_boot_sizing(self, payload):
        """Point the check at a recorded boot sizing."""
        directory = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, directory, True)
        path = Path(directory) / "floppy-boot-sizing.json"
        path.write_text(json.dumps(payload))
        patcher = patch.object(preflight, "_BOOT_SIZING_PATH", path)
        patcher.start()
        self.addCleanup(patcher.stop)

    def setUp(self):
        """Keep build info out of these cases."""
        patcher = patch.object(
            preflight,
            "_BUILD_INFO_PATH",
            Path("/nonexistent/floppy-build-info"),
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_matching_boot_sizing_is_reported(self):
        """The recorded decision rides along in the facts when it agrees."""
        self._write_boot_sizing({"tier": "standard", "web_concurrency": 1})
        with patch.dict("os.environ", {"FLOPPY_RESOURCE_TIER": "standard"}):
            result = check_runtime()

        self.assertEqual(result.status, OK)
        self.assertEqual(result.facts["boot_sizing"]["tier"], "standard")

    def test_drifted_tier_warns(self):
        """Booting at one tier and detecting another is worth saying out loud."""
        self._write_boot_sizing({"tier": "minimal", "web_concurrency": 1})
        with patch.dict("os.environ", {"FLOPPY_RESOURCE_TIER": "standard"}):
            result = check_runtime()

        self.assertEqual(result.status, WARN)
        self.assertNotEqual(result.status, FAIL)
        self.assertIn("minimal", result.cause)
