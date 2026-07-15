# FORK: overlay module — extends the upstream-owned dicts in api/helpers.py
# with the fork-only media types (music, podcast, comicissue) at app-ready
# time, so upstream's files stay byte-close to feat/add-api for mergeability.
from app.models import ComicIssue, MediaTypes, Music, Podcast, Sources

from . import helpers

FORK_MEDIA_MODELS = {
    MediaTypes.MUSIC.value: Music,
    MediaTypes.PODCAST.value: Podcast,
    MediaTypes.COMIC_ISSUE.value: ComicIssue,
}

FORK_VALID_SOURCES = {
    MediaTypes.MUSIC.value: [Sources.MUSICBRAINZ.value, Sources.MANUAL.value],
    MediaTypes.PODCAST.value: [Sources.POCKETCASTS.value, Sources.GPODDER.value],
    MediaTypes.COMIC_ISSUE.value: [Sources.COMICVINE.value, Sources.MANUAL.value],
}

_MODIFIABLE_FIELDS = {"score", "status", "progress", "start_date", "end_date", "notes"}


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
