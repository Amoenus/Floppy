# Install the shared log boundary before Django, Celery, or Gunicorn configures
# handlers. Every Python log record is redacted once before any handler writes
# it.
try:
    from app.log_safety import install_redacting_log_record_factory
except ModuleNotFoundError as error:
    # The data path checks import config with only config on sys.path, so the
    # app package is absent by design. Any other missing module is a fault:
    # raise it, or the process starts with no redaction and no warning.
    if error.name != "app":
        raise
else:
    install_redacting_log_record_factory()

# Ensure Celery application is loaded when Django starts.
from config.celery import app as celery_app

__all__ = ("celery_app",)
