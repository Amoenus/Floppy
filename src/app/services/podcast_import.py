"""Resolve an iTunes podcast search result into a tracked PodcastShow.

Shared by the web media-detail view and the podcast API so both surfaces
create/import shows the same way instead of duplicating the logic.
"""

from __future__ import annotations

import hashlib
import logging

from app.log_safety import exception_summary
from app.models import PodcastEpisode, PodcastShow

logger = logging.getLogger(__name__)


class PodcastImportError(Exception):
    """Raised when an iTunes id cannot be resolved into a podcast show."""


def import_show_from_itunes_id(itunes_id: str) -> PodcastShow:
    """Return the PodcastShow for an iTunes collection id, importing it if needed.

    Looks up the iTunes id via Pocket Casts, reuses an existing show with the
    same RSS feed if one is already tracked locally, or creates a new
    PodcastShow and imports its episode catalog from the RSS feed.

    Raises:
        PodcastImportError: if the iTunes id has no RSS feed, or the lookup
            fails.
    """
    from app.providers import pocketcasts
    from integrations import podcast_rss

    try:
        itunes_data = pocketcasts.lookup_by_itunes_id(itunes_id)
    except Exception as e:
        logger.warning(
            "iTunes lookup failed for id=%s: %s",
            itunes_id,
            exception_summary(e),
        )
        lookup_error = f"Failed to look up iTunes id {itunes_id}."
        raise PodcastImportError(lookup_error) from e

    rss_feed_url = itunes_data.get("feed_url", "")
    if not rss_feed_url:
        no_feed_error = f"Could not find an RSS feed for iTunes id {itunes_id}."
        raise PodcastImportError(no_feed_error)

    existing_show = PodcastShow.objects.filter(rss_feed_url=rss_feed_url).first()
    if existing_show:
        return existing_show

    podcast_uuid = f"itunes:{itunes_id}"
    existing_by_uuid = PodcastShow.objects.filter(podcast_uuid=podcast_uuid).first()
    if existing_by_uuid:
        return existing_by_uuid

    description = itunes_data.get("description", "")
    if not description:
        try:
            rss_metadata = podcast_rss.fetch_show_metadata_from_rss(rss_feed_url)
            description = rss_metadata.get("description", description)
            if not itunes_data.get("author") and rss_metadata.get("author"):
                itunes_data["author"] = rss_metadata["author"]
            if not itunes_data.get("language") and rss_metadata.get("language"):
                itunes_data["language"] = rss_metadata["language"]
        except Exception as e:
            logger.debug(
                "Failed to fetch show metadata from RSS: %s",
                exception_summary(e),
            )

    show = PodcastShow.objects.create(
        podcast_uuid=podcast_uuid,
        title=itunes_data.get("title", "Unknown Podcast"),
        author=itunes_data.get("author", ""),
        image=itunes_data.get("artwork_url", ""),
        description=description,
        genres=itunes_data.get("genres", []),
        language=itunes_data.get("language", ""),
        rss_feed_url=rss_feed_url,
    )

    try:
        _import_episodes_from_rss(show, rss_feed_url)
    except Exception as e:
        logger.warning(
            "Failed to fetch episodes from RSS feed for %s: %s",
            show.title,
            exception_summary(e),
        )

    return show


def _import_episodes_from_rss(show: PodcastShow, rss_feed_url: str) -> None:
    """Import every episode from an RSS feed into a newly created show."""
    from integrations import podcast_rss

    episodes_data = podcast_rss.fetch_episodes_from_rss(rss_feed_url, limit=None)
    seen_uuids = set()

    for episode_data in episodes_data:
        episode_uuid = episode_data.get("guid")
        if not episode_uuid:
            uuid_str = (
                f"{episode_data.get('title', '')}{episode_data.get('published', '')}"
            )
            episode_uuid = hashlib.md5(
                uuid_str.encode(),
                usedforsecurity=False,
            ).hexdigest()[:36]

        if episode_uuid in seen_uuids:
            continue

        exists = False
        if episode_data.get("title") and episode_data.get("published"):
            exists = PodcastEpisode.objects.filter(
                show=show,
                title__iexact=episode_data["title"].strip(),
                published__date=episode_data["published"].date(),
            ).exists()

        if not exists:
            try:
                PodcastEpisode.objects.create(
                    show=show,
                    episode_uuid=episode_uuid,
                    title=episode_data.get("title", "Unknown Episode"),
                    published=episode_data.get("published"),
                    duration=episode_data.get("duration"),
                    audio_url=episode_data.get("audio_url", ""),
                    episode_number=episode_data.get("episode_number"),
                    season_number=episode_data.get("season_number"),
                )
                seen_uuids.add(episode_uuid)
            except Exception:
                logger.debug(
                    "Skipping duplicate episode UUID %s for show %s",
                    episode_uuid,
                    show.title,
                )
