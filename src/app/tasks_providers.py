"""Watch-provider backfill: queryset builder, enqueue, and reconcile tasks.

Populates Item.watch_providers from TMDB metadata so movies/TV/anime can be
filtered by streaming service. Modeled on the simpler parts of tasks_genre.py,
without genre's TVDB anime-detection logic (not applicable here).
"""

import logging

from celery import shared_task
from django.conf import settings
from django.core.cache import cache

from app.interactive_requests import interactive_request_active
from app.log_safety import exception_summary
from app.models import Item, MediaTypes, MetadataBackfillField, Sources
from app.providers import services
from app.task_cooperation import CooperativeRun
from app.tasks_backfill_state import (
    _apply_backfill_state_filters,
    _filter_backfill_item_ids,
    _normalize_item_ids,
    _record_backfill_failure,
    _record_backfill_success,
)

logger = logging.getLogger(__name__)

BACKGROUND_TASK_PRIORITY = getattr(settings, "CELERY_TASK_PRIORITY_BACKGROUND", 1)

WATCH_PROVIDERS_BACKFILL_VERSION = 1
PROVIDER_MEDIA_TYPES = (
    MediaTypes.MOVIE.value,
    MediaTypes.TV.value,
    MediaTypes.ANIME.value,
)
WATCH_PROVIDERS_BACKFILL_QUEUE_TTL = 60 * 60  # 1 hour
WATCH_PROVIDERS_BACKFILL_ITEMS_QUEUE_KEY = "watch_providers_backfill_items_queue"
WATCH_PROVIDERS_BACKFILL_ITEMS_SCHEDULED_KEY = (
    "watch_providers_backfill_items_scheduled"
)

_WATCH_PROVIDERS_BATCH_SIZE_DEFAULT = 1500


def _provider_items_queryset():
    from app.models import MetadataBackfillState

    queryset = Item.objects.filter(
        media_type__in=PROVIDER_MEDIA_TYPES,
        source=Sources.TMDB.value,
        watch_providers={},
    )
    queryset = _apply_backfill_state_filters(
        queryset, MetadataBackfillField.WATCH_PROVIDERS
    )
    completed_ids = MetadataBackfillState.objects.filter(
        field=MetadataBackfillField.WATCH_PROVIDERS,
        give_up=False,
        fail_count=0,
        last_success_at__isnull=False,
        strategy_version__gte=WATCH_PROVIDERS_BACKFILL_VERSION,
    ).values("item_id")
    return queryset.exclude(id__in=completed_ids)


def is_provider_backfill_reconcile_complete() -> bool:
    """Return whether the current watch-provider strategy has no remaining candidates."""
    return not _provider_items_queryset().exists()


def _populate_providers_for_items(items):
    updated_count = 0
    error_count = 0
    run = CooperativeRun("watch_providers_backfill")
    for item in run.iter(items):
        try:
            metadata = services.get_media_metadata(
                item.media_type.lower(),
                item.media_id,
                item.source,
            )
            if not isinstance(metadata, dict):
                error_count += 1
                _record_backfill_failure(
                    item, MetadataBackfillField.WATCH_PROVIDERS, "no metadata"
                )
                continue

            providers = metadata.get("providers")
            if not isinstance(providers, dict):
                providers = {}

            item.watch_providers = providers
            item.save(update_fields=["watch_providers"])
            _record_backfill_success(
                item,
                MetadataBackfillField.WATCH_PROVIDERS,
                strategy_version=WATCH_PROVIDERS_BACKFILL_VERSION,
            )
            updated_count += 1
        except Exception as exc:
            error_count += 1
            logger.exception(
                "Error updating watch providers for %s: %s",
                item.title,
                exception_summary(exc),  # noqa: TRY401  # exception_summary() is the project's sanitised rendering
            )
            _record_backfill_failure(
                item,
                MetadataBackfillField.WATCH_PROVIDERS,
                f"exception: {exception_summary(exc)}",
            )

    run.reenqueue_if_deferred(enqueue_provider_backfill_items)
    logger.info(
        "Watch provider population batch completed: %s updated, %s errors",
        updated_count,
        error_count,
    )
    return updated_count, error_count


def enqueue_provider_backfill_items(item_ids, countdown=10):
    """Queue item IDs for watch-provider backfill."""
    normalized = _normalize_item_ids(item_ids)
    normalized = _filter_backfill_item_ids(
        normalized, MetadataBackfillField.WATCH_PROVIDERS
    )
    if not normalized:
        return 0
    try:
        queue = cache.get(WATCH_PROVIDERS_BACKFILL_ITEMS_QUEUE_KEY) or []
        queue = list(set(queue).union(normalized))
        cache.set(
            WATCH_PROVIDERS_BACKFILL_ITEMS_QUEUE_KEY,
            queue,
            timeout=WATCH_PROVIDERS_BACKFILL_QUEUE_TTL,
        )
        if cache.add(
            WATCH_PROVIDERS_BACKFILL_ITEMS_SCHEDULED_KEY, True, timeout=30
        ):
            populate_provider_backfill_queue.apply_async(countdown=countdown)
    except Exception as exc:  # pragma: no cover - cache unavailable
        logger.debug(
            "Watch provider backfill queue unavailable: %s", exception_summary(exc)
        )
        populate_provider_data_for_items.apply_async(
            args=[normalized], countdown=countdown
        )
    return len(normalized)


@shared_task(name="app.tasks.populate_provider_data_for_items")
def populate_provider_data_for_items(item_ids: list[int]):
    """Populate watch-provider data for a targeted list of item IDs."""
    normalized = _normalize_item_ids(item_ids)
    if not normalized:
        return {"updated": 0, "errors": 0, "message": "No item IDs provided"}

    items_to_update = list(_provider_items_queryset().filter(id__in=normalized))
    if not items_to_update:
        return {
            "updated": 0,
            "errors": 0,
            "message": "No targeted items need watch-provider data",
        }

    updated_count, error_count = _populate_providers_for_items(items_to_update)
    return {
        "updated": updated_count,
        "errors": error_count,
        "message": f"Processed {len(items_to_update)} targeted items",
    }


@shared_task(name="app.tasks.populate_provider_backfill_queue")
def populate_provider_backfill_queue(batch_size: int = 50):
    """Drain the watch-provider backfill queue and process items in small batches."""
    queue = cache.get(WATCH_PROVIDERS_BACKFILL_ITEMS_QUEUE_KEY) or []
    if not queue:
        cache.delete(WATCH_PROVIDERS_BACKFILL_ITEMS_SCHEDULED_KEY)
        return {"processed": 0, "message": "No queued watch-provider items"}

    cache.delete(WATCH_PROVIDERS_BACKFILL_ITEMS_SCHEDULED_KEY)
    batch = queue[:batch_size]
    remaining = queue[batch_size:]
    if remaining:
        cache.set(
            WATCH_PROVIDERS_BACKFILL_ITEMS_QUEUE_KEY,
            remaining,
            timeout=WATCH_PROVIDERS_BACKFILL_QUEUE_TTL,
        )
        if cache.add(
            WATCH_PROVIDERS_BACKFILL_ITEMS_SCHEDULED_KEY, True, timeout=30
        ):
            populate_provider_backfill_queue.apply_async(countdown=10)
    else:
        cache.delete(WATCH_PROVIDERS_BACKFILL_ITEMS_QUEUE_KEY)

    return populate_provider_data_for_items(batch)


@shared_task(name="app.tasks.reconcile_provider_backfill")
def reconcile_provider_backfill(
    strategy_version: int | None = None,
    batch_size: int = _WATCH_PROVIDERS_BATCH_SIZE_DEFAULT,
):
    """Queue all current watch-provider backfill candidates without waiting for the beat sweep."""
    batch_size = max(int(batch_size), 1)
    last_item_id = 0
    selected = 0
    enqueued = 0

    while True:
        batch_ids = list(
            _provider_items_queryset()
            .filter(id__gt=last_item_id)
            .order_by("id")
            .values_list("id", flat=True)[:batch_size],
        )
        if not batch_ids:
            break

        last_item_id = batch_ids[-1]
        selected += len(batch_ids)
        enqueued += enqueue_provider_backfill_items(batch_ids, countdown=10)

    if strategy_version is not None:
        cache.set(
            f"watch_providers_backfill_reconciled_v{strategy_version}",
            "done",
            timeout=None,
        )

    logger.info(
        "reconcile_provider_backfill selected=%d enqueued=%d version=%s",
        selected,
        enqueued,
        strategy_version,
    )
    return {"selected": selected, "enqueued": enqueued}


@shared_task(name="Ensure watch provider backfill reconcile")
def ensure_provider_backfill_reconcile(
    strategy_version: int | None = None,
    batch_size: int = _WATCH_PROVIDERS_BATCH_SIZE_DEFAULT,
):
    """Retry the watch-provider backfill reconcile until it has completed."""
    if interactive_request_active():
        logger.info(
            "ensure_provider_backfill_reconcile skipped reason=interactive_request_active"
        )
        return {"skipped": True, "reason": "interactive_request_active"}

    resolved_strategy_version = int(
        strategy_version or WATCH_PROVIDERS_BACKFILL_VERSION
    )
    version_key = f"watch_providers_backfill_reconciled_v{resolved_strategy_version}"
    status = cache.get(version_key)
    reconcile_complete = is_provider_backfill_reconcile_complete()

    if reconcile_complete:
        cache.set(version_key, "done", timeout=None)
        logger.debug(
            "ensure_provider_backfill_reconcile skipped version=%s status=done",
            resolved_strategy_version,
        )
        return {"skipped": True, "reason": "done"}

    if status == "pending":
        logger.debug(
            "ensure_provider_backfill_reconcile skipped version=%s status=pending",
            resolved_strategy_version,
        )
        return {"skipped": True, "reason": "pending"}

    if status == "done":
        logger.info(
            "ensure_provider_backfill_reconcile rerunning version=%s stale_cache_done=1",
            resolved_strategy_version,
        )

    return reconcile_provider_backfill(
        strategy_version=resolved_strategy_version,
        batch_size=batch_size,
    )
