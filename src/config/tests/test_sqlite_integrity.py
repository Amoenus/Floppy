"""Tests for the SQLite startup integrity guard (issue #593)."""

import sqlite3
import tempfile
from pathlib import Path
from unittest import mock

from django.test import SimpleTestCase

from config.sqlite_integrity import check_database_integrity


class SqliteIntegrityTests(SimpleTestCase):
    def test_healthy_database_passes(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = str(Path(tmp_dir) / "db.sqlite3")
            conn = sqlite3.connect(db_path)
            conn.execute("CREATE TABLE t (id INTEGER)")
            conn.commit()
            conn.close()

            check_database_integrity(db_path)

    def test_non_ok_result_without_exception_exits(self):
        fake_conn = mock.MagicMock()
        fake_conn.execute.return_value.fetchone.return_value = (
            "*** in database main ***\ncorruption found",
        )

        with (
            mock.patch("sqlite3.connect", return_value=fake_conn),
            self.assertRaises(SystemExit) as ctx,
            mock.patch("sys.stderr"),
        ):
            check_database_integrity("irrelevant.sqlite3")

        self.assertEqual(ctx.exception.code, 1)
        fake_conn.close.assert_called_once()

    def test_missing_result_treated_as_failure(self):
        fake_conn = mock.MagicMock()
        fake_conn.execute.return_value.fetchone.return_value = None

        with (
            mock.patch("sqlite3.connect", return_value=fake_conn),
            self.assertRaises(SystemExit) as ctx,
            mock.patch("sys.stderr"),
        ):
            check_database_integrity("irrelevant.sqlite3")

        self.assertEqual(ctx.exception.code, 1)
        fake_conn.close.assert_called_once()

    def test_database_error_still_handled(self):
        with (
            mock.patch("sqlite3.connect", side_effect=sqlite3.DatabaseError("bad")),
            self.assertRaises(SystemExit) as ctx,
            mock.patch("sys.stderr"),
        ):
            check_database_integrity("irrelevant.sqlite3")

        self.assertEqual(ctx.exception.code, 1)

    def test_connection_closed_on_ok_path(self):
        fake_conn = mock.MagicMock()
        fake_conn.execute.return_value.fetchone.return_value = ("ok",)

        with mock.patch("sqlite3.connect", return_value=fake_conn):
            check_database_integrity("irrelevant.sqlite3")

        fake_conn.close.assert_called_once()
