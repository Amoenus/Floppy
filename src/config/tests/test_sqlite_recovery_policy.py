import json
import os
import tempfile
import unittest
from pathlib import Path

from django.test import SimpleTestCase

from config import sqlite_integrity, sqlite_recovery_policy


class SqliteRecoveryPolicyTests(SimpleTestCase):
    """A keep-rows decision must not become a permanent integrity bypass."""

    @staticmethod
    def _incident():
        return {
            "affected": [{"count": 3, "season": None, "title": "Affected Show"}],
            "can_quarantine": True,
            "fingerprint": "a" * 64,
            "groups": [
                {
                    "count": 3,
                    "foreign_key_id": 0,
                    "parent": "parent",
                    "table": "child",
                },
            ],
            "other_titles": 2,
            "other_titles_count": 4,
            "samples": [],
            "total_conflicts": 3,
            "unidentified": 1,
            "unsafe_reasons": [],
        }

    def test_previous_acceptance_reopens_with_new_incident_token(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = str(Path(tmp_dir) / "db.sqlite3")
            Path(db_path).touch()
            sqlite_integrity._write_incident_report(
                db_path,
                self._incident(),
                status="accepted",
                resolution="accept",
            )

            reopened = sqlite_recovery_policy.reopen_previous_acceptance(db_path)

            self.assertTrue(reopened)
            report = json.loads(Path(f"{db_path}.integrity.json").read_text())
            self.assertEqual(report["status"], "blocked")
            self.assertEqual(report["resolution"], "accept-retired")
            self.assertEqual(report["fingerprint"], "a" * 64)
            self.assertEqual(len(report["incident_token"]), 32)
            self.assertIn("accept", report["actions"])
            self.assertIn("quarantine", report["actions"])
            self.assertEqual(
                report["affected"],
                [{"count": 3, "season": None, "title": "Affected Show"}],
            )
            self.assertEqual(report["affected_other_titles"], 2)
            self.assertEqual(report["affected_other_titles_count"], 4)
            self.assertEqual(report["affected_unidentified"], 1)

    def test_nonaccepted_incident_is_left_unchanged(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = str(Path(tmp_dir) / "db.sqlite3")
            Path(db_path).touch()
            sqlite_integrity._write_incident_report(
                db_path,
                self._incident(),
                status="blocked",
                incident_token="b" * 32,
            )
            report_path = Path(f"{db_path}.integrity.json")
            before = report_path.read_text()

            reopened = sqlite_recovery_policy.reopen_previous_acceptance(db_path)

            self.assertFalse(reopened)
            self.assertEqual(report_path.read_text(), before)

    def test_progress_metadata_resets_at_phase_boundaries(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = str(Path(tmp_dir) / "db.sqlite3")
            Path(db_path).touch()
            emit = sqlite_recovery_policy._status_emitter(db_path)

            emit(
                "running",
                "quick_check",
                progress_callbacks=22,
                progress_at="2026-08-20T01:49:00+00:00",
            )
            quick_status = sqlite_integrity.read_startup_status(db_path)

            emit("running", "foreign_key_check", progress_callbacks=0)
            foreign_key_status = sqlite_integrity.read_startup_status(db_path)

            self.assertEqual(quick_status["phase"], "quick_check")
            self.assertEqual(quick_status["progress_callbacks"], 22)
            self.assertEqual(
                quick_status["last_progress_at"],
                "2026-08-20T01:49:00+00:00",
            )
            self.assertEqual(foreign_key_status["phase"], "foreign_key_check")
            self.assertEqual(foreign_key_status["progress_callbacks"], 0)
            self.assertIsNone(foreign_key_status["last_progress_at"])
            self.assertNotEqual(
                quick_status["phase_started_at"],
                foreign_key_status["phase_started_at"],
            )

    @unittest.skipUnless(
        hasattr(os, "mkfifo") and hasattr(os, "O_NONBLOCK"),
        "requires POSIX FIFO support",
    )
    def test_non_regular_decision_file_is_rejected_without_blocking(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = str(Path(tmp_dir) / "db.sqlite3")
            Path(db_path).touch()
            decision_path = sqlite_recovery_policy._decision_path(db_path)
            os.mkfifo(decision_path)
            report = {
                "fingerprint": "a" * 64,
                "incident_token": "b" * 32,
            }

            decision = sqlite_recovery_policy._read_policy_decision(db_path, report)

            self.assertIsNone(decision)
            self.assertFalse(decision_path.exists())
