"""Tests for the SQLite startup integrity guard (issue #593)."""

import sqlite3
import tempfile
from pathlib import Path
from unittest import mock

from django.test import SimpleTestCase

from config.sqlite_integrity import check_database_integrity


class SqliteIntegrityTests(SimpleTestCase):
    def test_orphaned_album_artist_credit_is_removed(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = str(Path(tmp_dir) / "db.sqlite3")
            conn = sqlite3.connect(db_path)
            conn.executescript(
                """
                PRAGMA foreign_keys=ON;
                CREATE TABLE app_album (id INTEGER PRIMARY KEY);
                CREATE TABLE app_artist (id INTEGER PRIMARY KEY);
                CREATE TABLE app_albumartist (
                    id INTEGER PRIMARY KEY,
                    album_id INTEGER NOT NULL REFERENCES app_album(id),
                    artist_id INTEGER NOT NULL REFERENCES app_artist(id)
                );
                INSERT INTO app_album VALUES (345);
                INSERT INTO app_artist VALUES (12);
                INSERT INTO app_albumartist VALUES (1, 345, 12);
                """
            )
            conn.commit()
            conn.execute("PRAGMA foreign_keys=OFF")
            conn.execute("DELETE FROM app_album WHERE id = 345")
            conn.commit()
            conn.close()

            with mock.patch("sys.stderr"):
                check_database_integrity(db_path)

            conn = sqlite3.connect(db_path)
            self.assertEqual(
                conn.execute("SELECT COUNT(*) FROM app_albumartist").fetchone()[0],
                0,
            )
            self.assertEqual(conn.execute("PRAGMA foreign_key_check").fetchall(), [])
            conn.close()

    def test_unknown_foreign_key_violation_stops_startup(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = str(Path(tmp_dir) / "db.sqlite3")
            conn = sqlite3.connect(db_path)
            conn.executescript(
                """
                PRAGMA foreign_keys=ON;
                CREATE TABLE parent (id INTEGER PRIMARY KEY);
                CREATE TABLE child (
                    id INTEGER PRIMARY KEY,
                    parent_id INTEGER NOT NULL REFERENCES parent(id)
                );
                INSERT INTO parent VALUES (1);
                INSERT INTO child VALUES (1, 1);
                """
            )
            conn.commit()
            conn.execute("PRAGMA foreign_keys=OFF")
            conn.execute("DELETE FROM parent WHERE id = 1")
            conn.commit()
            conn.close()

            with (
                self.assertRaises(SystemExit) as ctx,
                mock.patch("sys.stderr"),
            ):
                check_database_integrity(db_path)

            self.assertEqual(ctx.exception.code, 1)
            conn = sqlite3.connect(db_path)
            self.assertEqual(
                conn.execute("SELECT COUNT(*) FROM child").fetchone()[0], 1
            )
            conn.close()

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
