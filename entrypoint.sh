#!/bin/sh

set -e

# Fail fast with a clear message if the SQLite file is already corrupt,
# instead of burning through the migrate retry loop below to arrive at an
# opaque "file is not a database" traceback (issue #508). Corruption here
# often means the db directory sits on a network filesystem that doesn't
# support SQLite's WAL locking - see README's SQLite persistence note.
if [ -z "$DB_HOST" ] && [ -f /floppy/db/db.sqlite3 ]; then
    python -c "
import sqlite3
import sys

try:
    conn = sqlite3.connect('/floppy/db/db.sqlite3')
    conn.execute('PRAGMA quick_check').fetchone()
except sqlite3.DatabaseError as e:
    print(f'[entrypoint] Database integrity check failed: {e}', file=sys.stderr)
    print(
        '[entrypoint] The SQLite file may be corrupt (see README: SQLite '
        'network filesystem caveat)',
        file=sys.stderr,
    )
    sys.exit(1)
" || exit 1
fi

# Bounded, retrying migrate: a blocked migration must fail loudly and retry
# instead of wedging the container as "unhealthy" forever (issue #341).
# lock_timeout is libpq-only (ignored on SQLite) and fires only while waiting
# on a lock, so long data migrations are unaffected. Retries escalate to
# verbosity 2 so Django names each pre/post-migrate handler phase in the logs.
migrate_attempts=0
migrate_verbosity=1
until echo "[entrypoint] Applying database migrations (attempt $((migrate_attempts + 1)))" >&2 && \
      DB_POOL_ENABLED=false PGOPTIONS="-c lock_timeout=120s" \
      timeout 900 python manage.py migrate --noinput -v "$migrate_verbosity"; do
    migrate_attempts=$((migrate_attempts + 1))
    migrate_verbosity=2
    if [ "$migrate_attempts" -ge 5 ]; then
        echo "[entrypoint] Migrations failed after ${migrate_attempts} attempts, exiting" >&2
        exit 1
    fi
    echo "[entrypoint] Migrations blocked or failed (attempt ${migrate_attempts}), retrying in 15s" >&2
    sleep 15
done

PUID=${PUID:-1000}
PGID=${PGID:-1000}

echo "[entrypoint] Fixing file ownership (PUID=${PUID} PGID=${PGID})" >&2

groupmod -o -g "$PGID" abc
usermod -o -u "$PUID" abc

chown abc:abc /floppy

# Bound each recursive chown: a stalled bind mount (e.g. network storage)
# must degrade to a warning instead of hanging the boot silently (issue #341).
for dir in db staticfiles /var/log/nginx /var/lib/nginx; do
    timeout 600 chown -R abc:abc "$dir" || \
        echo "[entrypoint] WARNING: chown of ${dir} failed or timed out (stalled mount?); continuing" >&2
done

echo "[entrypoint] Starting services" >&2
exec /usr/local/bin/supervisord -c /etc/supervisord.conf
