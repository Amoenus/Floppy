# Install the shared log boundary before Django, Celery, or Gunicorn configures
# handlers. Every Python log record is redacted once before any handler writes
# it. If app is not importable during isolated config checks, proceed cleanly.
try:
    from app.log_safety import install_redacting_log_record_factory

    install_redacting_log_record_factory()
except ModuleNotFoundError:
    pass

# Ensure Celery application is loaded when Django starts.
from config.celery import app as celery_app

__all__ = ("celery_app",)
