#!/bin/sh

set -e

reject_unsafe_managed_directory() {
    managed_name=$1
    managed_dir=$2
    case "$managed_dir" in
        /|/bin|/boot|/dev|/etc|/home|/lib|/lib32|/lib64|/libx32|/media|/mnt|/opt|/proc|/root|/run|/sbin|/srv|/sys|/tmp|/usr|/var|/usr/bin|/usr/include|/usr/lib|/usr/lib32|/usr/lib64|/usr/libx32|/usr/local|/usr/sbin|/usr/share|/usr/src|/var/backups|/var/cache|/var/lib|/var/local|/var/lock|/var/log|/var/mail|/var/opt|/var/spool|/var/tmp)
            echo "[entrypoint] ${managed_name} must resolve to a dedicated directory, not system directory ${managed_dir}." >&2
            exit 1
            ;;
    esac
}

DATA_DIR_INPUT=${FLOPPY_DATA_DIR:-/floppy/db}
DATA_DIR=$(python -c 'from pathlib import Path; import sys; print(Path(sys.argv[1]).resolve())' "$DATA_DIR_INPUT")
LOG_DIR_INPUT=${LOG_DIR:-/floppy/logs}
LOG_DIR_PATH=$(python -c 'from pathlib import Path; import sys; print(Path(sys.argv[1]).resolve())' "$LOG_DIR_INPUT")

reject_unsafe_managed_directory FLOPPY_DATA_DIR "$DATA_DIR"
reject_unsafe_managed_directory LOG_DIR "$LOG_DIR_PATH"

if [ -z "$DB_HOST" ]; then
    DB_FILE_INPUT=${FLOPPY_DB_PATH:-"${DATA_DIR_INPUT}/db.sqlite3"}
    DB_FILE=$(python -c 'from pathlib import Path; import sys; print(Path(sys.argv[1]).resolve())' "$DB_FILE_INPUT")
    DB_PARENT=$(python -c 'from pathlib import Path; import sys; print(Path(sys.argv[1]).parent)' "$DB_FILE")

    reject_unsafe_managed_directory FLOPPY_DB_PATH "$DB_PARENT"

    # Fail fast with a clear message if the SQLite file is already corrupt,
    # instead of burning through the migrate retry loop below to arrive at an
    # opaque "file is not a database" traceback (issue #508). Corruption here
    # often means the db directory sits on a network filesystem that doesn't
    # support SQLite's WAL locking - see README's SQLite persistence note.
    if [ -f "$DB_FILE" ]; then
        if timeout 600 python -c 'from config.sqlite_integrity import check_database_integrity; import sys; check_database_integrity(sys.argv[1])' "$DB_FILE"; then
            :
        else
            integrity_status=$?
            # GNU timeout returns 124. BusyBox in the image returns 143.
            case "$integrity_status" in
                124|143)
                    echo "[entrypoint] Database integrity check exceeded 600 seconds. Migrations did not run. Check the database storage and try again." >&2
                    ;;
            esac
            exit "$integrity_status"
        fi
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

chown abc:abc -- /floppy

if [ -e "$DATA_DIR" ] && ! timeout 600 chown abc:abc -- "$DATA_DIR"; then
    echo "[entrypoint] Cannot set ownership for FLOPPY_DATA_DIR ${DATA_DIR} with PUID=${PUID} and PGID=${PGID}. Fix the mount permissions or the IDs." >&2
    exit 1
fi

SECRET_FILE="${DATA_DIR}/secret_key"
if { [ -e "$SECRET_FILE" ] || [ -L "$SECRET_FILE" ]; } && \
   ! timeout 600 chown -h abc:abc -- "$SECRET_FILE"; then
    echo "[entrypoint] Cannot set ownership for generated secret ${SECRET_FILE} with PUID=${PUID} and PGID=${PGID}. Fix the mount permissions or the IDs." >&2
    exit 1
fi

if [ -z "$DB_HOST" ]; then
    if [ -e "$DB_PARENT" ] && ! timeout 600 chown abc:abc -- "$DB_PARENT"; then
        echo "[entrypoint] Cannot set ownership for FLOPPY_DB_PATH parent ${DB_PARENT} with PUID=${PUID} and PGID=${PGID}. Fix the mount permissions or the IDs." >&2
        exit 1
    fi
    for path in "$DB_FILE" "$DB_FILE-wal" "$DB_FILE-shm"; do
        if { [ -e "$path" ] || [ -L "$path" ]; } && \
           ! timeout 600 chown -h abc:abc -- "$path"; then
            echo "[entrypoint] Cannot set ownership for SQLite file ${path} with PUID=${PUID} and PGID=${PGID}. Fix the mount permissions or the IDs." >&2
            exit 1
        fi
    done
fi

# "logs" holds the rotating file handler every process configures at import time
# (settings.LOG_FILE). settings.py creates the directory, so whichever process
# imports settings first as root leaves it root-owned and every abc-owned
# process then dies with "Unable to configure handler 'file'" -- taking gunicorn
# with it, so the container serves 502s while reporting healthy.
#
# The log directory can be an operator-selected mount. Change only that
# directory entry and Floppy's current log file, never unrelated content.
if [ -e "$LOG_DIR_PATH" ] && ! timeout 600 chown abc:abc -- "$LOG_DIR_PATH"; then
    echo "[entrypoint] WARNING: chown of ${LOG_DIR_PATH} failed or timed out (stalled mount?); continuing" >&2
fi
LOG_FILE="${LOG_DIR_PATH}/floppy.log"
if { [ -e "$LOG_FILE" ] || [ -L "$LOG_FILE" ]; } && \
   ! timeout 600 chown -h abc:abc -- "$LOG_FILE"; then
    echo "[entrypoint] WARNING: chown of ${LOG_FILE} failed or timed out (stalled mount?); continuing" >&2
fi

# Bound recursive ownership fixes for the image-managed service directories: a
# stalled bind mount must degrade to a warning instead of hanging boot (#341).
for dir in /floppy/staticfiles /var/log/nginx /var/lib/nginx; do
    timeout 600 chown -R abc:abc -- "$dir" || \
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
