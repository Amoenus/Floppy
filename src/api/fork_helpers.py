# FORK: overlay module — extends the upstream-owned dicts in api/helpers.py
# with the fork-only media types (music, podcast, comicissue) at app-ready
# time, so upstream's files stay byte-close to feat/add-api for mergeability.
from http import HTTPStatus as HTTP  # noqa: N814

from rest_framework.response import Response

from app.models import ComicIssue, MediaTypes, Music, Podcast, Sources

from . import helpers

FORK_MEDIA_MODELS = {
    MediaTypes.MUSIC.value: Music,
    MediaTypes.PODCAST.value: Podcast,
    MediaTypes.COMIC_ISSUE.value: ComicIssue,
}

FORK_VALID_SOURCES = {
    MediaTypes.MUSIC.value: [Sources.MUSICBRAINZ.value, Sources.MANUAL.value],
    MediaTypes.PODCAST.value: [
        Sources.POCKETCASTS.value,
        Sources.GPODDER.value,
        Sources.AUDIOBOOKSHELF.value,
    ],
    MediaTypes.COMIC_ISSUE.value: [Sources.COMICVINE.value, Sources.MANUAL.value],
}

_MODIFIABLE_FIELDS = {"score", "status", "progress", "start_date", "end_date", "notes"}


# FORK: sort vocabulary for consumption-history endpoints (upstream TODO:
# "missing sorting"). Values reuse the aggregated-sort names where they apply.
_HISTORY_SORT_KEYS = {
    "started": lambda media: (
        getattr(media, "start_date", None) is None,
        getattr(media, "start_date", None),
    ),
    "ended": lambda media: (
        getattr(media, "end_date", None) is None,
        getattr(media, "end_date", None),
    ),
    "added": lambda media: (
        getattr(media, "created_at", None) is None,
        getattr(media, "created_at", None),
    ),
    "score": lambda media: (
        getattr(media, "score", None) is None,
        getattr(media, "score", None),
    ),
}


def sort_history_results(request, results):
    """Sort consumption-history rows by the optional `sort` query param.

    Accepts `started`, `ended`, `added`, `score`, each with an optional `-`
    prefix for descending order. Returns (results, error_response).
    """
    sort = request.GET.get("sort")
    if sort in (None, ""):
        return results, None
    descending = sort.startswith("-")
    key_name = sort[1:] if descending else sort
    key = _HISTORY_SORT_KEYS.get(key_name)
    if key is None:
        valid = ", ".join(sorted(_HISTORY_SORT_KEYS))
        return None, Response(
            {"detail": f"Invalid sort. Valid values: {valid} (prefix '-' to reverse)."},
            status=HTTP.BAD_REQUEST,
        )
    return sorted(results, key=key, reverse=descending), None


def install_fork_media_types():
    """Register fork media types in the upstream lookup tables (idempotent)."""
    helpers.MEDIA_TYPE_MODEL_MAP.update(FORK_MEDIA_MODELS)
    helpers.MEDIA_TYPE_COMPLETE_MODEL_MAP.update(FORK_MEDIA_MODELS)
    # The VALID_LISTs are module-level list objects imported by name elsewhere;
    # mutate them in place so every importer sees the additions.
    helpers.MEDIA_TYPE_VALID_LIST[:] = list(helpers.MEDIA_TYPE_MODEL_MAP)
    helpers.MEDIA_TYPE_COMPLETE_VALID_LIST[:] = list(
        helpers.MEDIA_TYPE_COMPLETE_MODEL_MAP,
    )
    for media_type in FORK_MEDIA_MODELS:
        helpers.MEDIA_MODIFIABLE_FIELDS.setdefault(media_type, set(_MODIFIABLE_FIELDS))
    for media_type, sources in FORK_VALID_SOURCES.items():
        helpers.VALID_SOURCES.setdefault(media_type, list(sources))
    # Episodes support the shared tracker fields plus the legacy dropped flag.
    helpers.MEDIA_MODIFIABLE_FIELDS[MediaTypes.EPISODE.value] |= (
        _MODIFIABLE_FIELDS | {"dropped"}
    )
