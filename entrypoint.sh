#!/bin/sh

set -e

# Bounded, retrying migrate: a blocked migration must fail loudly and retry
# instead of wedging the container as "unhealthy" forever (issue #341).
# lock_timeout is libpq-only (ignored on SQLite) and fires only while waiting
# on a lock, so long data migrations are unaffected.
migrate_attempts=0
until DB_POOL_ENABLED=false PGOPTIONS="-c lock_timeout=120s" \
      timeout 900 python manage.py migrate --noinput; do
    migrate_attempts=$((migrate_attempts + 1))
    if [ "$migrate_attempts" -ge 5 ]; then
        echo "Migrations failed after ${migrate_attempts} attempts, exiting" >&2
        exit 1
    fi
    echo "Migrations blocked or failed (attempt ${migrate_attempts}), retrying in 15s" >&2
    sleep 15
done

PUID=${PUID:-1000}
PGID=${PGID:-1000}

groupmod -o -g "$PGID" abc
usermod -o -u "$PUID" abc

chown abc:abc /yamtrack
chown -R abc:abc db
chown -R abc:abc staticfiles
chown -R abc:abc /var/log/nginx
chown -R abc:abc /var/lib/nginx

exec /usr/local/bin/supervisord -c /etc/supervisord.conf