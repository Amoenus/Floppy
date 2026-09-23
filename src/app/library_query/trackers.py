"""Which tracker rows put an ``Item`` in a user's library for a media type.

The engine queries ``Item`` rows and reaches tracker state through correlated
subqueries, so one item is one candidate however many tracker rows (repeat
viewings) it has. This module is the single place that knows how each media
type's tracker model is reached: the owner path, the status path, and the
anime-library routing that lets TV-tracked anime appear in the Anime library.
"""

from __future__ import annotations

from dataclasses import dataclass

from django.apps import apps
from django.db import models
from django.db.models import Case, F, OuterRef, Q, When

from app.models.choices import MediaTypes
from app.services import metadata_resolution


@dataclass(frozen=True)
class TrackerSource:
    """One tracker model feeding a library, and the items it may contribute."""

    model: type[models.Model]
    user_lookup: str
    status_field: str
    item_q: Q

    @property
    def is_episode(self) -> bool:
        """Return whether rows hang off a season instead of a user."""
        return self.user_lookup != "user"

    def rows(self, user):
        """Return every tracker row the user owns in this model."""
        return self.model.objects.filter(**{self.user_lookup: user})

    def item_rows(self, user, outer_ref: str = "pk"):
        """Return the user's rows for the outer item."""
        return self.rows(user).filter(item_id=OuterRef(outer_ref))

    def activity(self):
        """Return the expression that orders rows by most recent activity."""
        if self.is_episode:
            return Case(
                When(end_date__isnull=False, then=F("end_date")),
                default=F("created_at"),
                output_field=models.DateTimeField(),
            )
        return Case(
            When(end_date__isnull=False, then=F("end_date")),
            When(progressed_at__isnull=False, then=F("progressed_at")),
            default=F("created_at"),
            output_field=models.DateTimeField(),
        )


def _source(media_type: str, item_q: Q | None = None) -> TrackerSource:
    model = apps.get_model("app", media_type)
    if media_type == MediaTypes.EPISODE.value:
        return TrackerSource(
            model=model,
            user_lookup="related_season__user",
            status_field="related_season__status",
            item_q=item_q or Q(),
        )
    return TrackerSource(
        model=model,
        user_lookup="user",
        status_field="status",
        item_q=item_q or Q(),
    )


def tracker_sources(user, media_type: str) -> list[TrackerSource]:
    """Return the tracker sources that make up ``media_type``'s library.

    Anime a user tracks as TV lives on TV rows with an anime library bucket.
    ``anime_library_visibility`` decides whether those rows appear in the
    Anime library, the TV library, or both, exactly as the media list does.
    """
    anime_bucket = Q(library_media_type=MediaTypes.ANIME.value)
    if media_type == MediaTypes.ANIME.value:
        include_in_anime, _include_in_tv = metadata_resolution.anime_library_visibility(
            user,
        )
        sources = [_source(MediaTypes.ANIME.value)]
        if include_in_anime:
            sources.append(_source(MediaTypes.TV.value, anime_bucket))
        return sources
    if media_type == MediaTypes.TV.value:
        _include_in_anime, include_in_tv = metadata_resolution.anime_library_visibility(
            user,
        )
        return [_source(MediaTypes.TV.value, None if include_in_tv else ~anime_bucket)]
    return [_source(media_type)]
