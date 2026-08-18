"""Sync IMDB's public aggregate ratings for movies, shows, and episodes.

Movies/shows already carry their IMDB id in ``provider_external_ids["imdb_id"]``
(resolved by TMDB). This module downloads IMDB's public ``title.ratings``
dataset filtered to those ids, and separately uses the public
``title.episode`` dataset to resolve each show's per-episode tconsts (by
season/episode number) so their ratings can be looked up too — no extra API
calls needed for either step.
"""

from __future__ import annotations

import logging

from app.models import Item, MediaTypes

logger = logging.getLogger(__name__)

_SHOW_MEDIA_TYPES = (MediaTypes.TV.value, MediaTypes.ANIME.value)


def sync_movie_and_show_ratings() -> int:
    """Update imdb_rating/imdb_rating_count for movies and shows with a known imdb id.

    Returns the number of Items updated.
    """
    from app.providers import imdb_datasets

    items = list(
        Item.objects.filter(
            media_type__in=(MediaTypes.MOVIE.value, *_SHOW_MEDIA_TYPES),
            provider_external_ids__has_key="imdb_id",
        ),
    )
    if not items:
        return 0

    tconsts = {item.provider_external_ids["imdb_id"] for item in items}

    try:
        ratings = imdb_datasets.download_ratings(tconsts)
    except Exception:
        logger.warning("imdb_ratings: failed to download title ratings", exc_info=True)
        return 0

    updated = []
    for item in items:
        rating = ratings.get(item.provider_external_ids["imdb_id"])
        if rating is None:
            continue
        average_rating, num_votes = rating
        if item.imdb_rating == average_rating and item.imdb_rating_count == num_votes:
            continue
        item.imdb_rating = average_rating
        item.imdb_rating_count = num_votes
        updated.append(item)

    if updated:
        Item.objects.bulk_update(
            updated, ["imdb_rating", "imdb_rating_count"], batch_size=500
        )
        logger.info("imdb_ratings: updated %d movie/show ratings", len(updated))

    return len(updated)


def sync_episode_ratings() -> int:
    """Update imdb_rating/imdb_rating_count for episodes of tracked shows.

    Resolves each show's episode tconsts via the public title.episode
    dataset (keyed by season/episode number), then looks up ratings for
    those tconsts and matches them back to Episode-typed Items by
    media_id/source/season_number/episode_number.

    Returns the number of Items updated.
    """
    from app.providers import imdb_datasets

    shows = list(
        Item.objects.filter(
            media_type__in=_SHOW_MEDIA_TYPES,
            provider_external_ids__has_key="imdb_id",
        ).values("media_id", "source", "provider_external_ids"),
    )
    if not shows:
        return 0

    show_tconst_by_key = {
        (show["media_id"], show["source"]): show["provider_external_ids"]["imdb_id"]
        for show in shows
    }
    parent_tconsts = set(show_tconst_by_key.values())

    try:
        episode_map = imdb_datasets.download_episode_map(parent_tconsts)
    except Exception:
        logger.warning("imdb_ratings: failed to download episode map", exc_info=True)
        return 0

    if not episode_map:
        return 0

    child_tconsts = {
        tconst
        for season_episode_map in episode_map.values()
        for tconst in season_episode_map.values()
    }

    try:
        ratings = imdb_datasets.download_ratings(child_tconsts)
    except Exception:
        logger.warning(
            "imdb_ratings: failed to download episode title ratings", exc_info=True
        )
        return 0

    if not ratings:
        return 0

    updated = []
    for (media_id, source), parent_tconst in show_tconst_by_key.items():
        season_episode_map = episode_map.get(parent_tconst)
        if not season_episode_map:
            continue

        episode_items = Item.objects.filter(
            media_id=media_id,
            source=source,
            media_type=MediaTypes.EPISODE.value,
        )
        for episode_item in episode_items:
            if (
                episode_item.season_number is None
                or episode_item.episode_number is None
            ):
                continue
            tconst = season_episode_map.get(
                (episode_item.season_number, episode_item.episode_number),
            )
            if tconst is None:
                continue
            rating = ratings.get(tconst)
            if rating is None:
                continue
            average_rating, num_votes = rating
            if (
                episode_item.imdb_rating == average_rating
                and episode_item.imdb_rating_count == num_votes
            ):
                continue
            episode_item.imdb_rating = average_rating
            episode_item.imdb_rating_count = num_votes
            updated.append(episode_item)

    if updated:
        Item.objects.bulk_update(
            updated, ["imdb_rating", "imdb_rating_count"], batch_size=500
        )
        logger.info("imdb_ratings: updated %d episode ratings", len(updated))

    return len(updated)
