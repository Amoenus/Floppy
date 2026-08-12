#!/bin/sh

set -e

# Fail fast with a clear message if the SQLite file is already corrupt,
# instead of burning through the migrate retry loop below to arrive at an
# opaque "file is not a database" traceback (issue #508). Corruption here
# often means the db directory sits on a network filesystem that doesn't
# support SQLite's WAL locking - see README's SQLite persistence note.
# Rejects a non-"ok" quick_check result even when SQLite doesn't raise an
# exception for it (issue #593).
if [ -z "$DB_HOST" ] && [ -f /floppy/db/db.sqlite3 ]; then
    echo "[entrypoint] Checking SQLite integrity (PRAGMA quick_check)" >&2
    python -c "from config.sqlite_integrity import check_database_integrity; check_database_integrity('/floppy/db/db.sqlite3')" &
    integrity_pid=$!

    # Report actual bytes read from /proc rather than a bare "still going" -
    # cheap to read (no python instrumentation needed) and gives the user
    # something concrete instead of a repeating, uninformative message.
    elapsed=0
    while kill -0 "$integrity_pid" 2>/dev/null; do
        if [ "$elapsed" -ge 600 ]; then
            echo "[entrypoint] WARNING: SQLite integrity check exceeded 600s (slow storage?); continuing" >&2
            kill "$integrity_pid" 2>/dev/null
            break
        fi
        sleep 30
        elapsed=$((elapsed + 30))
        read_mb=$(awk '/^rchar:/ {printf "%.0f", $2/1048576}' "/proc/${integrity_pid}/io" 2>/dev/null)
        if [ -n "$read_mb" ]; then
            echo "[entrypoint] Still checking SQLite integrity (${elapsed}s elapsed, ~${read_mb}MB read so far)" >&2
        else
            echo "[entrypoint] Still checking SQLite integrity (${elapsed}s elapsed)" >&2
        fi
    done

    integrity_status=0
    wait "$integrity_pid" || integrity_status=$?
    if [ "$elapsed" -ge 600 ] && [ "$integrity_status" -ne 0 ]; then
        integrity_status=124
    fi
    if [ "$integrity_status" -ne 0 ] && [ "$integrity_status" -ne 124 ]; then
        exit 1
    fi
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

# "logs" holds the rotating file handler every process configures at import time
# (settings.LOG_FILE). settings.py creates the directory, so whichever process
# imports settings first as root leaves it root-owned and every abc-owned
# process then dies with "Unable to configure handler 'file'" -- taking gunicorn
# with it, so the container serves 502s while reporting healthy.
#
# Bound each recursive chown: a stalled bind mount (e.g. network storage)
# must degrade to a warning instead of hanging the boot silently (issue #341).
for dir in db logs staticfiles /var/log/nginx /var/lib/nginx; do
    echo "[entrypoint] Chowning ${dir}" >&2
    timeout 600 chown -R abc:abc "$dir" || \
        echo "[entrypoint] WARNING: chown of ${dir} failed or timed out (stalled mount?); continuing" >&2
done

# Probe the host once, here, and export the sizing decision for supervisord to
# expand into each program's command line. Doing it per-process would let the
# six supervised processes disagree about the tier if the host's free memory
# moved between their startups (issue #521). Values already set by the user are
# echoed back untouched, so an explicit WEB_CONCURRENCY always wins.
if resource_env=$(python -c 'from config.runtime_profile import emit_env; emit_env()'); then
    eval "$resource_env"
else
    echo "[entrypoint] WARNING: resource detection failed; using built-in defaults" >&2
fi
export FLOPPY_RESOURCE_TIER="${FLOPPY_RESOURCE_TIER:-standard}"
export FLOPPY_CELERY_QUEUES="${FLOPPY_CELERY_QUEUES:-celery}"
export FLOPPY_CELERY_ROLE="${FLOPPY_CELERY_ROLE:-background}"
export FLOPPY_START_INTERACTIVE_WORKER="${FLOPPY_START_INTERACTIVE_WORKER:-true}"
export FLOPPY_START_DISCOVER_WORKER="${FLOPPY_START_DISCOVER_WORKER:-true}"

echo "[entrypoint] Starting services" >&2
exec supervisord -c /etc/supervisord.conf
