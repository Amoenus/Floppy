"""In-place migration of TMDB-tracked TV shows to a user's preferred TVDB identity.

Unlike anime's flat-MAL -> grouped-TV migration (`app.services.anime_migration`),
this does not need to recreate any rows: TV/Season/Episode instances FK the
`Item` primary key directly, so re-keying the existing show/season/episode
`Item` rows' `media_id`/`source` in place preserves all watch history with
zero relation rewiring. See issue #387.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from django.db import transaction
from django.utils import timezone

from app.models import Item, MediaTypes, Sources
from app.providers import tmdb, tvdb

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class TvMigrationResult:
    """Outcome of a single show's migration attempt."""

    migrated: bool
    reason: str = ""


def _resolve_tvdb_id(item: Item) -> str | None:
    tvdb_id = (item.provider_external_ids or {}).get("tvdb_id")
    if tvdb_id:
        return str(tvdb_id)
    resolved = tmdb.resolve_tvdb_id_for_tmdb_show(item.media_id)
    return str(resolved) if resolved else None


def _local_season_items(item: Item) -> list[Item]:
    return list(
        Item.objects.filter(
            media_id=item.media_id,
            source=Sources.TMDB.value,
            media_type=MediaTypes.SEASON.value,
        ),
    )


def _local_episode_items(item: Item, season_numbers: list[int]) -> list[Item]:
    return list(
        Item.objects.filter(
            media_id=item.media_id,
            source=Sources.TMDB.value,
            media_type=MediaTypes.EPISODE.value,
            season_number__in=season_numbers,
        ),
    )


def _structure_is_compatible(
    local_seasons: list[Item],
    local_episodes: list[Item],
    tvdb_payload: dict,
) -> bool:
    """Return whether every locally-tracked season/episode exists on TVDB.

    Deliberately conservative: TVDB is allowed to have *more* seasons or
    episodes than are tracked locally (unaired episodes, specials the user
    never watched); it must not be missing anything the user already has.
    """
    for season in local_seasons:
        season_payload = tvdb_payload.get(f"season/{season.season_number}")
        if season_payload is None:
            return False

    episode_numbers_by_season: dict[int, set[int]] = {}
    for episode in local_episodes:
        episode_numbers_by_season.setdefault(episode.season_number, set()).add(
            episode.episode_number,
        )

    for season_number, episode_numbers in episode_numbers_by_season.items():
        season_payload = tvdb_payload.get(f"season/{season_number}")
        if season_payload is None:
            return False
        tvdb_episode_numbers = {
            episode.get("episode_number")
            for episode in season_payload.get("episodes") or []
        }
        if not episode_numbers.issubset(tvdb_episode_numbers):
            return False

    return True


def _would_collide(
    media_id: str,
    source: str,
    media_type: str,
    *,
    season_number: int | None = None,
    episode_number: int | None = None,
    exclude_pk: int,
) -> bool:
    return (
        Item.objects.filter(
            media_id=media_id,
            source=source,
            media_type=media_type,
            season_number=season_number,
            episode_number=episode_number,
        )
        .exclude(pk=exclude_pk)
        .exists()
    )


def _pin(item: Item, reason: str) -> TvMigrationResult:
    item.metadata_migration_pinned_at = timezone.now()
    item.save(update_fields=["metadata_migration_pinned_at"])
    logger.info(
        "Pinned TV item %s (%s) from TVDB auto-migration: %s",
        item.media_id,
        item.title,
        reason,
    )
    return TvMigrationResult(migrated=False, reason=reason)


def migrate_tv_item_to_tvdb(item: Item) -> TvMigrationResult:
    """Migrate a TMDB-tracked, non-anime TV show `Item` to TVDB identity in place.

    Never raises and never partially migrates: any check that fails aborts
    before mutating data. Structure mismatches and identity collisions pin
    the item (best-effort, still retried for other reasons later) instead of
    migrating, since a bad migration would silently re-identify a user's
    watch history under the wrong show.
    """
    if item.source != Sources.TMDB.value or item.media_type != MediaTypes.TV.value:
        return TvMigrationResult(migrated=False, reason="not a TMDB TV item")
    if item.library_media_type == MediaTypes.ANIME.value:
        return TvMigrationResult(migrated=False, reason="grouped anime item, skipped")
    if not tvdb.enabled():
        return TvMigrationResult(migrated=False, reason="TVDB not configured")

    tvdb_id = _resolve_tvdb_id(item)
    if not tvdb_id:
        return TvMigrationResult(migrated=False, reason="no TVDB id resolvable")

    if _would_collide(
        tvdb_id,
        Sources.TVDB.value,
        MediaTypes.TV.value,
        exclude_pk=item.pk,
    ):
        return _pin(item, "a separate item already tracks this show via TVDB")

    local_seasons = _local_season_items(item)
    season_numbers = [season.season_number for season in local_seasons]
    local_episodes = _local_episode_items(item, season_numbers)

    try:
        tvdb_payload = tvdb.tv_with_seasons(tvdb_id, season_numbers)
    except Exception as exc:  # pragma: no cover - defensive network guard
        logger.warning(
            "TVDB migration lookup failed for show %s (TVDB %s): %s",
            item.media_id,
            tvdb_id,
            exc,
        )
        return TvMigrationResult(migrated=False, reason="TVDB lookup failed")

    if not _structure_is_compatible(local_seasons, local_episodes, tvdb_payload):
        return _pin(item, "season/episode structure does not match TVDB")

    for season in local_seasons:
        if _would_collide(
            tvdb_id,
            Sources.TVDB.value,
            MediaTypes.SEASON.value,
            season_number=season.season_number,
            exclude_pk=season.pk,
        ):
            return _pin(item, "a separate season item already exists under TVDB")
    for episode in local_episodes:
        if _would_collide(
            tvdb_id,
            Sources.TVDB.value,
            MediaTypes.EPISODE.value,
            season_number=episode.season_number,
            episode_number=episode.episode_number,
            exclude_pk=episode.pk,
        ):
            return _pin(item, "a separate episode item already exists under TVDB")

    with transaction.atomic():
        item.media_id = tvdb_id
        item.source = Sources.TVDB.value
        item.title = tvdb_payload.get("title") or item.title
        item.image = tvdb_payload.get("image") or item.image
        item.save(update_fields=["media_id", "source", "title", "image"])

        for season in local_seasons:
            season_payload = tvdb_payload.get(f"season/{season.season_number}") or {}
            season.media_id = tvdb_id
            season.source = Sources.TVDB.value
            season.image = season_payload.get("image") or season.image
            season.save(update_fields=["media_id", "source", "image"])

        for episode in local_episodes:
            episode.media_id = tvdb_id
            episode.source = Sources.TVDB.value
            episode.save(update_fields=["media_id", "source"])

    logger.info(
        "Migrated TV item %s to TVDB %s (%s)",
        item.media_id,
        tvdb_id,
        item.title,
    )
    return TvMigrationResult(migrated=True)
