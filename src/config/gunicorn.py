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


def post_fork(server, worker):  # noqa: ARG001
    """Drop connections inherited from the preloaded master process.

    ``preload_app`` runs ``django.setup()`` (and every ``AppConfig.ready()``)
    once in the master before forking. Without this, forked workers share the
    master's already-open DB/cache connections instead of opening their own,
    which caused login sessions to silently fail to persist once more than
    one worker/thread was in play (issue #335).
    """
    from django.db import connections  # noqa: PLC0415

    connections.close_all()
