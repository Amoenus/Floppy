"""Persist MyAnimeList aggregate ratings for tracked anime items."""

from __future__ import annotations

import logging
from collections import defaultdict

from django.db.models import Prefetch, Q

from app.models import Item, ItemProviderLink, MediaTypes, Sources
from app.providers import mal as mal_provider

logger = logging.getLogger(__name__)

_MAL_PROVIDER_MEDIA_TYPES = (
    MediaTypes.ANIME.value,
    MediaTypes.TV.value,
)


def _is_anime_item(item: Item) -> bool:
    """Return whether an Item represents a title in the anime library."""
    return item.media_type == MediaTypes.ANIME.value or (
        item.media_type == MediaTypes.TV.value
        and item.library_media_type == MediaTypes.ANIME.value
    )


def _mal_rating_items():
    """Return anime Items with their exact MAL links prefetched."""
    mal_links = ItemProviderLink.objects.filter(
        provider=Sources.MAL.value,
        provider_media_type__in=_MAL_PROVIDER_MEDIA_TYPES,
    ).only("item_id", "provider_media_id")
    return Item.objects.filter(
        Q(media_type=MediaTypes.ANIME.value)
        | Q(
            media_type=MediaTypes.TV.value,
            library_media_type=MediaTypes.ANIME.value,
        ),
    ).prefetch_related(
        Prefetch("provider_links", queryset=mal_links, to_attr="_mal_rating_links"),
    )


def resolve_mal_id(item: Item | None) -> str | None:
    """Return an unambiguous exact MAL ID for an anime Item.

    Flat MAL entries use their own media ID. Grouped anime may carry the ID in
    either the persisted external-ID map or an ItemProviderLink. Conflicting
    IDs are treated as ambiguous rather than guessed from titles.
    """
    if item is None or not _is_anime_item(item):
        return None

    if item.source == Sources.MAL.value and item.media_type == MediaTypes.ANIME.value:
        media_id = str(item.media_id or "").strip()
        return media_id or None

    mal_ids = set()
    external_ids = item.provider_external_ids or {}
    external_mal_id = str(external_ids.get("mal_id") or "").strip()
    if external_mal_id:
        mal_ids.add(external_mal_id)

    provider_links = getattr(item, "_mal_rating_links", None)
    if provider_links is None:
        provider_links = item.provider_links.filter(
            provider=Sources.MAL.value,
            provider_media_type__in=_MAL_PROVIDER_MEDIA_TYPES,
        ).only("item_id", "provider_media_id")
    mal_ids.update(
        str(link.provider_media_id).strip()
        for link in provider_links
        if str(link.provider_media_id or "").strip()
    )

    return next(iter(mal_ids)) if len(mal_ids) == 1 else None


def sync_mal_ratings() -> int:
    """Fetch and persist MAL ratings for tracked anime.

    Requests are deduplicated by exact MAL ID. A successful response without a
    usable score clears an old value; a provider failure leaves the last
    successful value untouched.
    """
    items_by_mal_id = defaultdict(list)
    for item in _mal_rating_items().iterator(chunk_size=200):
        mal_id = resolve_mal_id(item)
        if mal_id:
            items_by_mal_id[mal_id].append(item)

    if not items_by_mal_id:
        return 0

    updated_items = []
    error_count = 0
    for mal_id, items in items_by_mal_id.items():
        try:
            rating = mal_provider.rating(mal_id)
        except Exception:
            error_count += 1
            logger.warning(
                "mal_ratings: failed to fetch rating for mal_id=%s",
                mal_id,
                exc_info=True,
            )
            continue

        desired_rating, desired_count = rating or (None, None)
        for item in items:
            if (
                item.mal_rating == desired_rating
                and item.mal_rating_count == desired_count
            ):
                continue
            item.mal_rating = desired_rating
            item.mal_rating_count = desired_count
            updated_items.append(item)

    if updated_items:
        Item.objects.bulk_update(
            updated_items,
            ["mal_rating", "mal_rating_count"],
            batch_size=500,
        )

    logger.info(
        "mal_ratings: processed %d MAL IDs, updated %d items, errors=%d",
        len(items_by_mal_id),
        len(updated_items),
        error_count,
    )
    return len(updated_items)
