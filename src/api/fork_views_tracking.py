# FORK: tracking endpoints that mirror web-only actions — episode watch/
# drop and tag management. Kept out of upstream-owned views.py; URL wiring
# lives in fork_urls.py.
import logging
from http import HTTPStatus as HTTP  # noqa: N814

from django.db.models import Count
from django.utils import timezone
from rest_framework import views as drf_views
from rest_framework.response import Response

from app.fork_services_episode import drop_episode, resolve_or_create_season
from app.models import Episode, ItemTag, MediaTypes, Season, Tag

from .helpers import (
    check_source_type,
    resolve_item_queryset,
    try_parse_datetime_input,
)
from .serializers import serialize_data

logger = logging.getLogger(__name__)


def _tv_route_error(media_type, source):
    """Validate the media_type/source pair for episode routes."""
    if media_type != MediaTypes.TV.value:
        return Response(
            {"detail": "Episodes are supported only for 'tv' media type."},
            status=HTTP.BAD_REQUEST,
        )
    if not check_source_type(media_type, source):
        return Response(
            {"detail": f"Cannot query `{source}` for `{media_type}` media type"},
            status=HTTP.BAD_REQUEST,
        )
    return None


def _get_tracked_season(user, media_id, source, season_number):
    """Return the user's tracked Season row or None."""
    return (
        Season.objects.filter(
            item__media_id=media_id,
            item__source=source,
            item__season_number=season_number,
            item__episode_number=None,
            user=user,
        )
        .order_by("id")
        .first()
    )


# /api/v1/media/tv/[source]/[media_id]/[season_number]/episodes/[episode_number]/watch/
class MediaEpisodeWatchView(drf_views.APIView):
    """Add or remove a watch (play) for an episode.

    POST mirrors the web UI's episode_save: the season is auto-created when
    missing and a new Episode play row is added. DELETE mirrors unwatching:
    the most recent play of the episode is removed.
    """

    def post(
        self,
        request,
        media_type,
        source,
        media_id,
        season_number,
        episode_number,
    ):
        """Record a watch for the episode."""
        error = _tv_route_error(media_type, source)
        if error:
            return error

        raw_end_date = request.data.get("end_date")
        if raw_end_date in (None, ""):
            end_date = timezone.now()
        else:
            try:
                end_date = try_parse_datetime_input(raw_end_date)
            except (TypeError, ValueError):
                return Response(
                    {"detail": "Invalid end_date format."},
                    status=HTTP.BAD_REQUEST,
                )

        library_media_type = (request.data.get("library_media_type") or "").strip()
        try:
            related_season = resolve_or_create_season(
                request.user,
                media_id,
                source,
                int(season_number),
                library_media_type=library_media_type,
            )
        except Exception as e:  # noqa: BLE001 — provider metadata failures
            return Response(
                {"detail": "Could not resolve season.", "errors": str(e)},
                status=HTTP.NOT_FOUND,
            )

        related_season.watch(int(episode_number), end_date)
        episode = (
            Episode.objects.filter(
                related_season=related_season,
                item__episode_number=int(episode_number),
            )
            .select_related("item")
            .order_by("-id")
            .first()
        )
        return Response(serialize_data(episode), status=HTTP.CREATED)

    def delete(
        self,
        request,
        media_type,
        source,
        media_id,
        season_number,
        episode_number,
    ):
        """Remove the most recent watch of the episode."""
        error = _tv_route_error(media_type, source)
        if error:
            return error

        related_season = _get_tracked_season(
            request.user,
            media_id,
            source,
            int(season_number),
        )
        if related_season is None:
            return Response(
                {"detail": "Season not found or not tracked."},
                status=HTTP.NOT_FOUND,
            )

        plays = Episode.objects.filter(
            related_season=related_season,
            item__episode_number=int(episode_number),
        )
        if not plays.exists():
            return Response(
                {"detail": "Episode has no watches."},
                status=HTTP.NOT_FOUND,
            )

        related_season.unwatch(int(episode_number))
        return Response(status=HTTP.NO_CONTENT)


# /api/v1/media/tv/[source]/[media_id]/[season_number]/episodes/[episode_number]/drop/
class MediaEpisodeDropView(drf_views.APIView):
    """Mark an episode dropped — advances progress without watch history."""

    def post(
        self,
        request,
        media_type,
        source,
        media_id,
        season_number,
        episode_number,
    ):
        """Record a drop for the episode (mirrors web episode_drop)."""
        error = _tv_route_error(media_type, source)
        if error:
            return error

        library_media_type = (request.data.get("library_media_type") or "").strip()
        try:
            related_season = resolve_or_create_season(
                request.user,
                media_id,
                source,
                int(season_number),
                library_media_type=library_media_type,
            )
        except Exception as e:  # noqa: BLE001 — provider metadata failures
            return Response(
                {"detail": "Could not resolve season.", "errors": str(e)},
                status=HTTP.NOT_FOUND,
            )

        episode = drop_episode(related_season, int(episode_number))
        return Response(serialize_data(episode), status=HTTP.CREATED)


def _serialize_tag(tag, item_count=None):
    """Return a plain payload for a Tag row."""
    payload = {
        "id": tag.id,
        "name": tag.name,
        "created_at": tag.created_at,
    }
    if item_count is not None:
        payload["item_count"] = item_count
    return payload


# /api/v1/tags/
class TagsView(drf_views.APIView):
    """List or create the user's tags."""

    def get(self, request):
        """Return all tags for the user with item counts."""
        tags = Tag.objects.filter(user=request.user).annotate(
            item_count=Count("item_tags"),
        )
        return Response(
            {"results": [_serialize_tag(tag, tag.item_count) for tag in tags]},
            status=HTTP.OK,
        )

    def post(self, request):
        """Create a tag (names are unique per user, case-insensitive)."""
        name = " ".join((request.data.get("name") or "").split())
        if not name:
            return Response(
                {"detail": "Tag name is required."},
                status=HTTP.BAD_REQUEST,
            )
        if Tag.objects.filter(user=request.user, name__iexact=name).exists():
            return Response(
                {"detail": f'Tag "{name}" already exists.'},
                status=HTTP.CONFLICT,
            )
        tag = Tag.objects.create(user=request.user, name=name)
        return Response(_serialize_tag(tag), status=HTTP.CREATED)


# /api/v1/tags/[tag_id]/
class TagDetailView(drf_views.APIView):
    """Rename or delete a tag."""

    def _get_tag(self, request, tag_id):
        return Tag.objects.filter(id=tag_id, user=request.user).first()

    def patch(self, request, tag_id):
        """Rename the tag."""
        tag = self._get_tag(request, tag_id)
        if tag is None:
            return Response({"detail": "Tag not found."}, status=HTTP.NOT_FOUND)
        name = " ".join((request.data.get("name") or "").split())
        if not name:
            return Response(
                {"detail": "Tag name is required."},
                status=HTTP.BAD_REQUEST,
            )
        if (
            Tag.objects.filter(user=request.user, name__iexact=name)
            .exclude(id=tag.id)
            .exists()
        ):
            return Response(
                {"detail": f'Tag "{name}" already exists.'},
                status=HTTP.CONFLICT,
            )
        tag.name = name
        tag.save()
        return Response(_serialize_tag(tag), status=HTTP.OK)

    def delete(self, request, tag_id):
        """Delete the tag and its item associations."""
        tag = self._get_tag(request, tag_id)
        if tag is None:
            return Response({"detail": "Tag not found."}, status=HTTP.NOT_FOUND)
        tag.delete()
        return Response(status=HTTP.NO_CONTENT)


# /api/v1/media/[media_type]/[source]/[media_id]/tags/
class MediaTagsView(drf_views.APIView):
    """Read or replace the caller's tags on a media item."""

    def _get_item(self, media_type, source, media_id):
        return resolve_item_queryset(media_id, source, media_type).first()

    def get(self, request, media_type, source, media_id):
        """Return the user's tags applied to this item."""
        item = self._get_item(media_type, source, media_id)
        if item is None:
            return Response({"detail": "Item not found."}, status=HTTP.NOT_FOUND)
        tags = Tag.objects.filter(user=request.user, item_tags__item=item)
        return Response(
            {"results": [_serialize_tag(tag) for tag in tags]},
            status=HTTP.OK,
        )

    def put(self, request, media_type, source, media_id):
        """Replace the user's tags on this item with the given tag ids."""
        item = self._get_item(media_type, source, media_id)
        if item is None:
            return Response({"detail": "Item not found."}, status=HTTP.NOT_FOUND)

        tag_ids = request.data.get("tag_ids")
        if not isinstance(tag_ids, list):
            return Response(
                {"detail": "'tag_ids' must be a list of tag ids."},
                status=HTTP.BAD_REQUEST,
            )

        tags = list(Tag.objects.filter(user=request.user, id__in=tag_ids))
        if len(tags) != len(set(tag_ids)):
            return Response(
                {"detail": "One or more tags not found."},
                status=HTTP.NOT_FOUND,
            )

        ItemTag.objects.filter(item=item, tag__user=request.user).exclude(
            tag__in=tags,
        ).delete()
        for tag in tags:
            ItemTag.objects.get_or_create(tag=tag, item=item)

        applied = Tag.objects.filter(user=request.user, item_tags__item=item)
        return Response(
            {"results": [_serialize_tag(tag) for tag in applied]},
            status=HTTP.OK,
        )
