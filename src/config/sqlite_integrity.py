from __future__ import annotations

import sqlite3
import sys

_CORRUPTION_HINT = (
    "[entrypoint] The SQLite file may be corrupt (see README: SQLite "
    "network filesystem caveat)"
)


def check_database_integrity(db_path: str) -> None:
    """Run PRAGMA quick_check and exit(1) if the database is not OK."""
    conn = None
    try:
        conn = sqlite3.connect(db_path)
        result = conn.execute("PRAGMA quick_check").fetchone()
    except sqlite3.DatabaseError as e:
        print(f"[entrypoint] Database integrity check failed: {e}", file=sys.stderr)  # noqa: T201
        print(_CORRUPTION_HINT, file=sys.stderr)  # noqa: T201
        sys.exit(1)
    finally:
        if conn is not None:
            conn.close()

    status = result[0] if result else None
    if status != "ok":
        print(  # noqa: T201
            f"[entrypoint] Database integrity check failed: quick_check returned {status!r}",
            file=sys.stderr,
        )
        print(_CORRUPTION_HINT, file=sys.stderr)  # noqa: T201
        sys.exit(1)
