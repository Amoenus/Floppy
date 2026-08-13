from __future__ import annotations

import sqlite3
import sys

_CORRUPTION_HINT = (
    "[entrypoint] The SQLite file may be corrupt (see README: SQLite "
    "network filesystem caveat)"
)
_ALBUM_ARTIST_TABLE = "app_albumartist"


def _check_foreign_keys(conn: sqlite3.Connection) -> None:
    violations = list(conn.execute("PRAGMA foreign_key_check").fetchall())
    if not violations:
        return

    if {violation[0] for violation in violations} == {_ALBUM_ARTIST_TABLE}:
        row_ids = {violation[1] for violation in violations}
        if None not in row_ids:
            row_ids = sorted(row_ids)
            placeholders = ", ".join("?" for _ in row_ids)
            with conn:
                conn.execute(
                    f"DELETE FROM {_ALBUM_ARTIST_TABLE} "  # noqa: S608  # fixed table name
                    f"WHERE rowid IN ({placeholders})",
                    row_ids,
                )
            print(  # noqa: T201
                f"[entrypoint] Removed {len(row_ids)} orphaned album artist "
                "credit row(s) before migrations",
                file=sys.stderr,
            )
            violations = list(conn.execute("PRAGMA foreign_key_check").fetchall())
            if not violations:
                return

    for table, row_id, parent, _foreign_key_id in violations[:10]:
        print(  # noqa: T201
            "[entrypoint] Database foreign key check failed: "
            f"table={table!r}, row={row_id!r}, parent={parent!r}",
            file=sys.stderr,
        )
    print(_CORRUPTION_HINT, file=sys.stderr)  # noqa: T201
    sys.exit(1)


def check_database_integrity(db_path: str) -> None:
    """Check SQLite storage and foreign keys before migrations."""
    conn = None
    try:
        conn = sqlite3.connect(db_path)
        result = conn.execute("PRAGMA quick_check").fetchone()
        status = result[0] if result else None
        if status != "ok":
            print(  # noqa: T201
                "[entrypoint] Database integrity check failed: "
                f"quick_check returned {status!r}",
                file=sys.stderr,
            )
            print(_CORRUPTION_HINT, file=sys.stderr)  # noqa: T201
            sys.exit(1)

        _check_foreign_keys(conn)
    except sqlite3.DatabaseError as e:
        print(f"[entrypoint] Database integrity check failed: {e}", file=sys.stderr)  # noqa: T201
        print(_CORRUPTION_HINT, file=sys.stderr)  # noqa: T201
        sys.exit(1)
    finally:
        if conn is not None:
            conn.close()
