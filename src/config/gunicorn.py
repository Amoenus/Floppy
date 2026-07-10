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
