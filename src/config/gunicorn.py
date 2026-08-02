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


def pre_fork(server, worker):
    """Close database and Redis pools in the master before workers are forked.

    ``preload_app`` runs ``django.setup()`` (and every ``AppConfig.ready()``)
    once in the master before forking, and ``AppConfig.ready()`` touches the
    Redis cache (startup-task scheduling keys). Psycopg pools own background
    threads and must not be inherited by the preloaded workers (#341); the
    Redis connection likewise must not be inherited, or every forked
    worker/thread shares one raw socket and corrupts each other's commands -
    including session writes, which silently fail to persist (#335).
    """
    from django.core.cache import caches
    from django.db import connections

    connections.close_all()
    for connection in connections.all():
        close_pool = getattr(connection, "close_pool", None)
        if close_pool is not None:
            close_pool()

    for cache in caches.all():
        client = getattr(cache, "client", None)
        do_close_clients = getattr(client, "do_close_clients", None)
        if do_close_clients is not None:
            do_close_clients()


def post_fork(server, worker):
    """Drop database connections inherited from the preloaded master process.

    ``pre_fork`` closes any process-local database/Redis pool before the
    fork; this hook remains as a final guard against inherited database
    connections (issue #335).
    """
    from django.db import connections

    connections.close_all()
