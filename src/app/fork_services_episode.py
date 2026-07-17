# FORK: shared episode-tracking domain logic used by both the web views
# (save_views.episode_save / episode_drop) and the REST API, so the two
# surfaces cannot drift apart.
import logging

from app import cache_utils
from app.models import Episode, Item, MediaTypes, Season, Status
from app.providers import services
from app.services import metadata_resolution

logger = logging.getLogger(__name__)


def resolve_or_create_season(
    user,
    media_id,
    source,
    season_number,
    library_media_type="",
):
    """Return the user's tracked Season row, creating it if it doesn't exist.

    Mirrors the season auto-create behavior of the web episode actions:
    missing seasons are created In Progress with metadata-derived title/image.
    """
    season_qs = Season.objects.filter(
        item__media_id=media_id,
        item__source=source,
        item__season_number=season_number,
        item__episode_number=None,
        user=user,
    )
    related_season = season_qs.order_by("id").first()
    if related_season is None:
        tv_with_seasons_metadata = services.get_media_metadata(
            "tv_with_seasons",
            media_id,
            source,
            [season_number],
        )
        season_metadata = tv_with_seasons_metadata[f"season/{season_number}"]

        # Use season poster if available, otherwise fallback to TV show poster
        season_image = season_metadata.get("image") or tv_with_seasons_metadata.get(
            "image",
        )

        item = metadata_resolution.get_or_create_tracked_season_item(
            media_id,
            source,
            season_number,
            provider=source,
            library_media_type=library_media_type or MediaTypes.SEASON.value,
            metadata=None,
            defaults={
                **Item.title_fields_from_metadata(tv_with_seasons_metadata),
                "image": season_image,
            },
        )
        related_season = Season.objects.create(
            item=item,
            user=user,
            score=None,
            status=Status.IN_PROGRESS.value,
            notes="",
        )

        logger.info("%s did not exist, it was created successfully.", related_season)
    elif season_qs.count() > 1:
        logger.warning(
            "Multiple Season records for media_id=%s season=%s user=%s — using oldest",
            media_id,
            season_number,
            user,
        )

    _sync_library_media_type(related_season, library_media_type)
    return related_season


def _sync_library_media_type(related_season, library_media_type):
    """Propagate an explicit library bucket to the season and TV items."""
    if not library_media_type:
        return
    if related_season.item.library_media_type != library_media_type:
        related_season.item.library_media_type = library_media_type
        related_season.item.save(update_fields=["library_media_type"])
    if (
        related_season.related_tv
        and related_season.related_tv.item.library_media_type != library_media_type
    ):
        related_season.related_tv.item.library_media_type = library_media_type
        related_season.related_tv.item.save(update_fields=["library_media_type"])


def drop_episode(related_season, episode_number):
    """Mark an episode dropped — advances progress without watch history."""
    item = related_season.get_episode_item(episode_number)
    episode_record = Episode.objects.create(
        related_season=related_season,
        item=item,
        end_date=None,
        dropped=True,
        status=Status.DROPPED.value,
    )
    logger.info("%s dropped successfully.", episode_record)
    cache_utils.clear_time_left_cache_for_user(related_season.user_id)
    cache_utils.clear_media_list_cache_for_user(related_season.user_id)
    return episode_record
