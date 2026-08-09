from pathlib import Path

from django.test import SimpleTestCase

ENTRYPOINT = Path(__file__).resolve().parents[3] / "entrypoint.sh"


class EntrypointSQLiteIntegrityContractTests(SimpleTestCase):
    """Keep the SQLite startup gate ahead of database migrations."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.script = ENTRYPOINT.read_text()

    def test_checker_runs_only_for_an_existing_sqlite_database(self):
        self.assertIn(
            'if [ -z "$DB_HOST" ] && [ -f /floppy/db/db.sqlite3 ]; then',
            self.script,
        )

    def test_failed_check_exits_before_migrations(self):
        checker = "python -m config.sqlite_integrity /floppy/db/db.sqlite3"
        migration = "python manage.py migrate"

        self.assertLess(self.script.index(checker), self.script.index(migration))
        self.assertIn('exit "$integrity_status"', self.script)

    def test_checker_timeout_is_bounded_and_reported(self):
        self.assertIn(
            "timeout 600 python -m config.sqlite_integrity /floppy/db/db.sqlite3",
            self.script,
        )
        self.assertIn("124|143)", self.script)
        self.assertIn("Database integrity check exceeded 600 seconds", self.script)
