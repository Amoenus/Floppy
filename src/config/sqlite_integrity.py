"""Check SQLite integrity before Django runs migrations."""

from __future__ import annotations

import sqlite3
import sys
from contextlib import closing
from pathlib import Path


def _write_error(message: str) -> None:
    sys.stderr.write(f"{message}\n")


def check_database(database_path: str | Path) -> int:
    """Return zero only when SQLite reports an exact ``ok`` result."""
    path = Path(database_path).resolve()
    database_uri = f"{path.as_uri()}?mode=ro"

    try:
        with closing(sqlite3.connect(database_uri, uri=True)) as connection:
            row = connection.execute("PRAGMA quick_check").fetchone()
    except sqlite3.DatabaseError as exc:
        _write_error(f"[entrypoint] Database integrity check failed for {path}: {exc}")
        _write_error(
            "[entrypoint] The SQLite file may be corrupt "
            "(see README: SQLite network filesystem caveat)"
        )
        return 1

    if not row or row[0] != "ok":
        _write_error(
            "[entrypoint] Database integrity check failed for "
            f"{path}: PRAGMA quick_check returned {row!r}"
        )
        _write_error(
            "[entrypoint] Migrations did not run. Restore a known-good backup. "
            "Keep SQLite on local or block storage."
        )
        return 1

    return 0


def main() -> int:
    """Run the check for the database path on the command line."""
    arguments = sys.argv[1:]
    if len(arguments) != 1:
        _write_error("Usage: python -m config.sqlite_integrity DATABASE_PATH")
        return 2
    return check_database(arguments[0])


if __name__ == "__main__":
    raise SystemExit(main())
