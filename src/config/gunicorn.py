import os

bind = "localhost:8001"
preload_app = True
timeout = 200
max_requests = 500
max_requests_jitter = 10

# Threaded workers so one slow request can't stall the whole UI.  The
# container also runs nginx, three celery workers, and beat, so keep the
# process count low and rely on threads for I/O-bound concurrency.
worker_class = "gthread"
workers = int(os.environ.get("WEB_CONCURRENCY", "2"))
threads = int(os.environ.get("GUNICORN_THREADS", "4"))

accesslog = "-"
errorlog = "-"


def pre_fork(server, worker):  # noqa: ARG001
    """Close database pools in the master before workers are forked.

    Psycopg pools own background threads and must not be inherited by the
    preloaded workers; inherited pools eventually exhaust their slots (#341).
    """
    from django.db import connections  # noqa: PLC0415

    connections.close_all()
    for connection in connections.all():
        close_pool = getattr(connection, "close_pool", None)
        if close_pool is not None:
            close_pool()


def post_fork(server, worker):  # noqa: ARG001
    """Drop connections inherited from the preloaded master process.

    ``preload_app`` runs ``django.setup()`` (and every ``AppConfig.ready()``)
    once in the master before forking. ``pre_fork`` closes any process-local
    database pool before the fork; this hook remains as a final guard against
    inherited connections (issue #335).
    """
    from django.db import connections  # noqa: PLC0415

    connections.close_all()
