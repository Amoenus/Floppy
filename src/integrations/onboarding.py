"""Service capability map used by the first-run setup wizard.

Answers, for a given import source, which media types it's relevant to and
whether the current user already has it connected. This is additive: it
reads the same account relations the ``import_data`` view already exposes
in its template context (``src/users/views.py:import_data``) rather than
introducing a new notion of "connected", and it doesn't change
``import_data.html``, ``SOURCES_CONFIG``, or any existing import view.

The wizard opens a source's existing setup/import UI via
``import_data`` (``?open=<slug>``) rather than duplicating its forms, so
this module only needs to know *which* sources are relevant to *which*
media types and whether they're already connected — not their connect/
import URLs.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.models.choices import MediaTypes

MOVIE = MediaTypes.MOVIE.value
TV = MediaTypes.TV.value
ANIME = MediaTypes.ANIME.value
MANGA = MediaTypes.MANGA.value
GAME = MediaTypes.GAME.value
BOARDGAME = MediaTypes.BOARDGAME.value
BOOK = MediaTypes.BOOK.value
COMIC = MediaTypes.COMIC.value
MUSIC = MediaTypes.MUSIC.value
PODCAST = MediaTypes.PODCAST.value

ALL_MEDIA_TYPES = (
    MOVIE,
    TV,
    ANIME,
    MANGA,
    GAME,
    BOARDGAME,
    BOOK,
    COMIC,
    MUSIC,
    PODCAST,
)


@dataclass(frozen=True)
class OnboardingSource:
    """One import source, as the setup wizard needs to reason about it."""

    slug: str
    media_types: tuple[str, ...]
    setup_kind: str  # oauth | api_key | host_url | credentials | upload
    account_attr: str | None = None  # request.user.<attr> if persistently connected
    recommended_import_mode: str = "new"
    tags: tuple[str, ...] = field(default_factory=tuple)  # matches import_data.html's activeMediaTag values

    def is_connected(self, user) -> bool:
        """Whether this user already has a persistent connection for this source."""
        if not self.account_attr:
            return False
        return getattr(user, self.account_attr, None) is not None


ONBOARDING_SOURCES: tuple[OnboardingSource, ...] = (
    OnboardingSource("plex", (MOVIE, TV, MUSIC), "oauth", "plex_account", tags=("screen", "music")),
    OnboardingSource("radarr", (MOVIE,), "host_url", "radarr_account", tags=("screen",)),
    OnboardingSource("sonarr", (TV,), "host_url", "sonarr_account", tags=("screen",)),
    OnboardingSource("stremio", (MOVIE, TV), "credentials", "stremio_account", tags=("screen",)),
    OnboardingSource(
        "audiobookshelf", (BOOK, PODCAST), "host_url", "audiobookshelf_account", tags=("reading", "podcasts")
    ),
    OnboardingSource("storyteller", (BOOK,), "host_url", "storyteller_account", tags=("reading",)),
    OnboardingSource("pocketcasts", (PODCAST,), "credentials", "pocketcasts_account", tags=("podcasts",)),
    OnboardingSource("gpodder", (PODCAST,), "credentials", "gpodder_account", tags=("podcasts",)),
    OnboardingSource("lastfm", (MUSIC,), "api_key", "lastfm_account", tags=("music",)),
    OnboardingSource("koito", (MUSIC,), "host_url", "koito_account", tags=("music",)),
    OnboardingSource("trakt", (MOVIE, TV), "oauth", recommended_import_mode="new", tags=("screen",)),
    OnboardingSource("mdblist", (MOVIE, TV), "api_key", "mdblist_account", tags=("screen",)),
    OnboardingSource("simkl", (MOVIE, TV, ANIME), "oauth", tags=("screen", "anime_manga")),
    OnboardingSource("myanimelist", (ANIME, MANGA), "oauth", tags=("anime_manga",)),
    OnboardingSource("anilist", (ANIME, MANGA), "oauth", tags=("anime_manga",)),
    OnboardingSource("kitsu", (ANIME, MANGA), "credentials", tags=("anime_manga",)),
    OnboardingSource("hltb", (GAME,), "credentials", tags=("games",)),
    OnboardingSource("grouvee", (GAME,), "upload", tags=("games",)),
    OnboardingSource("steam", (GAME,), "credentials", tags=("games",)),
    OnboardingSource("imdb", (MOVIE, TV), "upload", tags=("screen",)),
    OnboardingSource("goodreads", (BOOK,), "upload", tags=("reading",)),
    OnboardingSource("hardcover", (BOOK,), "upload", tags=("reading",)),
    OnboardingSource("storygraph", (BOOK,), "upload", tags=("reading",)),
    OnboardingSource(
        "yamtrack",
        ALL_MEDIA_TYPES,
        "upload",
        recommended_import_mode="overwrite",
        tags=("backup", "screen", "anime_manga", "reading", "games", "podcasts", "music"),
    ),
)

_SOURCES_BY_SLUG = {source.slug: source for source in ONBOARDING_SOURCES}


def get_source(slug: str) -> OnboardingSource | None:
    """Return the ``OnboardingSource`` for ``slug``, if known."""
    return _SOURCES_BY_SLUG.get(slug)


def sources_for_media_type(media_type: str) -> list[OnboardingSource]:
    """Return sources relevant to a single media type, in a stable, sensible order."""
    return [source for source in ONBOARDING_SOURCES if media_type in source.media_types]
