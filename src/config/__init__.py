# Install the shared log boundary before Django, Celery, or Gunicorn configures
# handlers. Every Python log record is then redacted once before any handler
# can write it to stdout, disk, or an external collector.
from app.log_safety import install_redacting_log_record_factory

install_redacting_log_record_factory()

# This will make sure the app is always imported when
# Django starts so that shared_task will use this app.
from config.celery import app as celery_app  # noqa: E402

__all__ = ("celery_app",)
