import io
import sqlite3
from contextlib import redirect_stderr
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from config.sqlite_integrity import check_database


class SQLiteIntegrityTests(SimpleTestCase):
    """Verify the startup integrity decision without changing a database."""

    def test_exact_ok_result_succeeds_and_closes_connection(self):
        connection = MagicMock()
        connection.execute.return_value.fetchone.return_value = ("ok",)
        database_path = Path("db.sqlite3").resolve()

        with patch(
            "config.sqlite_integrity.sqlite3.connect", return_value=connection
        ) as connect:
            status = check_database(database_path)

        self.assertEqual(status, 0)
        connect.assert_called_once_with(f"{database_path.as_uri()}?mode=ro", uri=True)
        connection.close.assert_called_once()

    def test_missing_result_fails_and_closes_connection(self):
        connection = MagicMock()
        connection.execute.return_value.fetchone.return_value = None
        stderr = io.StringIO()

        with (
            patch(
                "config.sqlite_integrity.sqlite3.connect",
                return_value=connection,
            ),
            redirect_stderr(stderr),
        ):
            status = check_database("db.sqlite3")

        self.assertEqual(status, 1)
        self.assertIn("returned None", stderr.getvalue())
        connection.close.assert_called_once()

    def test_non_ok_result_fails_and_reports_result(self):
        connection = MagicMock()
        connection.execute.return_value.fetchone.return_value = (
            "*** in database main ***",
        )
        stderr = io.StringIO()

        with (
            patch(
                "config.sqlite_integrity.sqlite3.connect",
                return_value=connection,
            ),
            redirect_stderr(stderr),
        ):
            status = check_database("db.sqlite3")

        self.assertEqual(status, 1)
        self.assertIn("*** in database main ***", stderr.getvalue())
        self.assertIn("Migrations did not run", stderr.getvalue())
        connection.close.assert_called_once()

    def test_database_error_fails_and_closes_connection(self):
        connection = MagicMock()
        connection.execute.side_effect = sqlite3.DatabaseError("damaged")
        stderr = io.StringIO()

        with (
            patch(
                "config.sqlite_integrity.sqlite3.connect",
                return_value=connection,
            ),
            redirect_stderr(stderr),
        ):
            status = check_database("db.sqlite3")

        self.assertEqual(status, 1)
        self.assertIn("Database integrity check failed", stderr.getvalue())
        self.assertIn("network filesystem caveat", stderr.getvalue())
        connection.close.assert_called_once()

    def test_missing_database_is_not_created(self):
        with TemporaryDirectory() as temp_dir:
            database_path = Path(temp_dir) / "missing.sqlite3"
            stderr = io.StringIO()

            with redirect_stderr(stderr):
                status = check_database(database_path)

            self.assertEqual(status, 1)
            self.assertFalse(database_path.exists())
