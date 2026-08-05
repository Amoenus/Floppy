"""Collapse repeated media-server webhooks for the same play.

Plex and Jellyfin both emit several events for a single viewing - play, pause,
resume, progress, stop - and Floppy queued a task for every one. Each task can
fan out to a handful of TMDB lookups (``_process_tv`` in ``webhooks/base.py``
has five metadata-recovery paths), all landing on the interactive worker, which
runs at concurrency 1. On a constrained host that backlog is what turns a single
episode into minutes of provider traffic (issue #521).

Duplicate protection did exist, but only at the very end: ``_handle_tv_episode``
compares the new ``end_date`` against the previous one within five seconds. By
then the expensive work has already happened. This throttles at the front door
instead.

The fingerprint deliberately excludes playback position, so a stream of progress
events for the same episode collapses to one task. It includes the event type, so
a "stop" following a "play" is still processed - those mean different things.

Two rules:

* An unrecognized payload shape is **always processed**. A provider changing its
  JSON must degrade to "no deduplication", never to "silently dropped scrobble".
* An unavailable cache **fails open**, unlike the background scheduling locks in
  ``app/cache_safety.py``. A skipped cache warm costs nothing; a dropped scrobble
  is unrecoverable, and the DB-level five-second guard is still there as a
  backstop.
"""

from __future__ import annotations

import hashlib
import json
import logging

from app import cache_safety

logger = logging.getLogger(__name__)

# Long enough to swallow a burst of progress events, short enough that a genuine
# re-watch started right after the last one still registers.
WEBHOOK_DEDUPE_TTL_SECONDS = 10


def _jellyfin_identity(payload: dict) -> dict | None:
    item = payload.get("Item") or {}
    identity = {
        "event": payload.get("Event"),
        "item_id": item.get("Id"),
        "series": item.get("SeriesName"),
        "season": item.get("ParentIndexNumber"),
        "episode": item.get("IndexNumber"),
        "name": item.get("Name"),
    }
    return identity if any(identity.values()) else None


# Emby's payload mirrors Jellyfin's; both descend from the same schema.
_emby_identity = _jellyfin_identity


def _plex_identity(payload: dict) -> dict | None:
    metadata = payload.get("Metadata") or {}
    identity = {
        "event": payload.get("event"),
        "rating_key": metadata.get("ratingKey"),
        "guid": metadata.get("guid"),
        "type": metadata.get("type"),
    }
    return identity if any(identity.values()) else None


def _kodi_identity(payload: dict) -> dict | None:
    identity = {
        "event": payload.get("event"),
        "media_type": payload.get("mediaType"),
        "title": payload.get("title"),
        "series": payload.get("tvShowTitle"),
        "season": payload.get("season"),
        "episode": payload.get("episode"),
    }
    return identity if any(identity.values()) else None


def _stremio_identity(payload: dict) -> dict | None:
    identity = {"id": payload.get("id"), "type": payload.get("type")}
    return identity if identity["id"] else None


_IDENTITY_EXTRACTORS = {
    "jellyfin": _jellyfin_identity,
    "emby": _emby_identity,
    "plex": _plex_identity,
    "kodi": _kodi_identity,
    "stremio": _stremio_identity,
}


def webhook_dedupe_key(provider: str, user_id: int, payload: dict) -> str | None:
    """Return a dedupe key for this webhook, or None if it can't be fingerprinted."""
    extractor = _IDENTITY_EXTRACTORS.get(provider)
    if extractor is None or not isinstance(payload, dict):
        return None

    identity = extractor(payload)
    if not identity:
        return None

    # Hashed rather than interpolated: titles can be long, contain colons, and
    # would otherwise put user media names into cache keys verbatim.
    digest = hashlib.sha256(
        json.dumps(identity, sort_keys=True, default=str).encode(),
    ).hexdigest()[:32]
    return f"webhook_dedupe_{provider}_{user_id}_{digest}"


def should_process_webhook(
    provider: str,
    user_id: int,
    payload: dict,
    *,
    ttl: int = WEBHOOK_DEDUPE_TTL_SECONDS,
) -> bool:
    """Return whether this webhook is the first of its kind in the window."""
    key = webhook_dedupe_key(provider, user_id, payload)
    if key is None:
        # Unrecognized shape: process it. Never drop a scrobble to save work.
        return True

    if cache_safety.acquire_lock(
        key,
        timeout=ttl,
        on_error=cache_safety.ON_ERROR_PROCEED,
    ):
        return True

    logger.debug(
        "Skipping duplicate %s webhook for user %s within %ss",
        provider,
        user_id,
        ttl,
    )
    return False
