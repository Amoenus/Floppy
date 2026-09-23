"""Horizontal (16:9) backdrop resolution shared by the web UI and the API.

Item.image holds a portrait poster (TMDB w500); backdrops are never stored on
the model, only fetched from the provider and cached in Redis for 7 days by
``lists.models.CustomList``.

``resolve_backdrop`` returns ``None`` when no backdrop exists, leaving the
choice of fallback to the caller: the web UI falls back to the poster so a
card always renders, while the API reports ``null`` so clients can pick their
own artwork.

Request paths and the interactive worker read backdrops with
``allow_network=False`` and hand misses to ``schedule_backdrop_warm``, which
fetches them on a background worker so a later read finds them in Redis.
"""

import logging

from django.conf import settings
from django.core.cache import cache

from app.models import MediaTypes, Sources

logger = logging.getLogger(__name__)

# How long a queued warm suppresses another request for the same item.
BACKDROP_WARM_GUARD_SECONDS = 60 * 10

# Episodes and seasons share their show's media_id, and TMDB files anime under
# /tv, so all three resolve against the show-level backdrop.
_SHOW_LEVEL_TYPES = (
    MediaTypes.EPISODE.value,
    MediaTypes.SEASON.value,
    MediaTypes.ANIME.value,
)
_TVDB_TYPES = (MediaTypes.TV.value, *_SHOW_LEVEL_TYPES)


def _read(item, key):
    """Read a field from either a serialized dict or a model instance."""
    if isinstance(item, dict):
        return item.get(key)
    return getattr(item, key, None)


def _identity(item):
    """Return (source, media_type, media_id) or None when incomplete."""
    if not item:
        return None
    source = _read(item, "source")
    media_type = _read(item, "media_type")
    media_id = _read(item, "media_id")
    if not source or not media_type or not media_id:
        return None
    return source, media_type, media_id


def _tvdb_tmdb_id(item):
    """Return the TMDB cross-reference the TVDB provider stores, if any."""
    return (_read(item, "provider_external_ids") or {}).get("tmdb_id")


def _usable(backdrop):
    """Treat the placeholder image as no backdrop at all."""
    if backdrop and backdrop != settings.IMG_NONE:
        return backdrop
    return None


def cached_backdrop(item) -> str | None:
    """Return an already-cached backdrop without triggering provider lookups."""
    identity = _identity(item)
    if identity is None:
        return None
    source, media_type, media_id = identity

    if source == Sources.TMDB.value:
        backdrop_media_type = (
            MediaTypes.TV.value if media_type in _SHOW_LEVEL_TYPES else media_type
        )
        if backdrop_media_type in (MediaTypes.MOVIE.value, MediaTypes.TV.value):
            return _usable(
                cache.get(f"tmdb_backdrop_{backdrop_media_type}_{media_id}"),
            )

    if source == Sources.TVDB.value and media_type in _TVDB_TYPES:
        tmdb_id = _tvdb_tmdb_id(item)
        if tmdb_id:
            return _usable(cache.get(f"tmdb_backdrop_tv_{tmdb_id}"))

    if source == Sources.IGDB.value and media_type == MediaTypes.GAME.value:
        return _usable(cache.get(f"igdb_backdrop_{media_id}"))

    return None


def resolve_backdrop(item, *, allow_network=True) -> str | None:
    """Return a horizontal backdrop URL for an item, or None if there is none.

    With ``allow_network=False`` only the Redis cache is consulted, so callers
    on a hot path never block on a provider request.
    """
    cached = cached_backdrop(item)
    if cached:
        return cached

    identity = _identity(item)
    if identity is None or not allow_network:
        return None
    source, media_type, media_id = identity

    try:
        from lists.models import CustomList
    except Exception:
        return None

    custom_list = CustomList()

    if source == Sources.TMDB.value and media_type in _SHOW_LEVEL_TYPES:
        return _fetch(custom_list._get_tmdb_backdrop, MediaTypes.TV.value, media_id)

    if source == Sources.TMDB.value and media_type in (
        MediaTypes.MOVIE.value,
        MediaTypes.TV.value,
    ):
        return _fetch(custom_list._get_tmdb_backdrop, media_type, media_id)

    if source == Sources.TVDB.value and media_type in _TVDB_TYPES:
        tmdb_id = _tvdb_tmdb_id(item)
        if tmdb_id:
            return _fetch(custom_list._get_tmdb_backdrop, MediaTypes.TV.value, tmdb_id)

    if source == Sources.IGDB.value and media_type == MediaTypes.GAME.value:
        return _fetch(custom_list._get_igdb_backdrop, media_id)

    return None


def _fetch(getter, *args) -> str | None:
    """Call a provider backdrop getter; artwork is never worth raising over."""
    try:
        return _usable(getter(*args))
    except Exception:  # deliberate best-effort; failure is non-fatal here
        return None


def warm_identity(item) -> dict | None:
    """Return a JSON-safe identity to warm, or None if no backdrop can exist.

    Mirrors the provider branches of ``resolve_backdrop`` so items that can
    never have a backdrop (books, music, podcasts, TVDB without a TMDB id)
    never queue work.
    """
    identity = _identity(item)
    if identity is None:
        return None
    source, media_type, media_id = identity
    if source == Sources.TMDB.value and media_type in (
        MediaTypes.MOVIE.value,
        MediaTypes.TV.value,
        *_SHOW_LEVEL_TYPES,
    ):
        return {"source": source, "media_type": media_type, "media_id": str(media_id)}
    if source == Sources.TVDB.value and media_type in _TVDB_TYPES:
        tmdb_id = _tvdb_tmdb_id(item)
        if tmdb_id:
            return {
                "source": source,
                "media_type": media_type,
                "media_id": str(media_id),
                "provider_external_ids": {"tmdb_id": tmdb_id},
            }
        return None
    if source == Sources.IGDB.value and media_type == MediaTypes.GAME.value:
        return {"source": source, "media_type": media_type, "media_id": str(media_id)}
    return None


def _warm_guard_key(identity: dict) -> str:
    return (
        f"backdrop_warm:{identity['source']}:{identity['media_type']}:"
        f"{identity['media_id']}"
    )


def schedule_backdrop_warm(items) -> int:
    """Queue one background fetch for the backdrops these items are missing.

    Each item is guarded for ``BACKDROP_WARM_GUARD_SECONDS`` so repeated page
    loads do not queue the same fetch again. Returns the number queued.
    """
    identities = []
    guard_keys = []
    for item in items:
        identity = warm_identity(item)
        if identity is None:
            continue
        key = _warm_guard_key(identity)
        if key in guard_keys or not cache.add(key, True, BACKDROP_WARM_GUARD_SECONDS):
            continue
        guard_keys.append(key)
        identities.append(identity)

    if not identities:
        return 0

    try:
        from app.tasks import warm_backdrops_task

        warm_backdrops_task.apply_async(
            args=[identities],
            priority=getattr(settings, "CELERY_TASK_PRIORITY_FOLLOWUP", 3),
        )
    except Exception:  # pragma: no cover - Celery not available
        cache.delete_many(guard_keys)
        logger.debug("Could not schedule backdrop warm", exc_info=True)
        return 0
    return len(identities)
