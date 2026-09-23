"""The sort registry: one definition per sort key, shared by every surface.

A ``SortDef`` has a SQL expression, or is computed in Python from the
hydrated candidate (reusing the media list's value function). Every surface
orders the same way: the value with nulls last, then the lower-cased title,
then the item id, all following the requested direction. Equal values
therefore cannot move between pages.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from django.db.models import (
    BigIntegerField,
    ExpressionWrapper,
    F,
    Max,
    Q,
    Subquery,
    Value,
)
from django.db.models.functions import Coalesce, Lower

from app.library_query.filters import (
    NEEDS_MAX_PROGRESS,
    NEEDS_MEDIA,
    TypeContext,
    latest_value,
)

if TYPE_CHECKING:
    from collections.abc import Callable

NEEDS_NEXT_EPISODE = "next_episode"

# A seeded multiplicative hash: a fixed permutation of ids per seed, computed
# identically in SQL and Python, so a shuffled shelf pages without repeats or
# gaps. The seed is mixed in before a second multiply; adding it last would
# only rotate the same order. Every product stays inside a signed 64-bit int.
RANDOM_MODULUS = 4294967291
RANDOM_MULTIPLIER = 2654435761
RANDOM_MIXER = 1103515245


@dataclass(frozen=True)
class SortDef:
    """How one sort key orders candidates.

    ``sql`` returns ``None`` for a media type whose value it cannot express;
    the query is then ordered in Python.
    """

    keys: tuple[str, ...]
    sql: Callable[[TypeContext, int], object] | None = None
    needs: frozenset[str] = field(default_factory=frozenset)
    # Tracker-derived values differ per media type; the executor coalesces
    # them when a query spans several types.
    tracker: bool = False


def _field(name: str):
    return lambda ctx, seed: F(name)


def _tracker_aggregate(sort_key: str):
    """Order by the value ``_aggregate_item_data`` computes across rows."""
    field_name = {
        "start_date": "start_date",
        "end_date": "end_date",
        "progress": "progress",
    }[sort_key]

    def build(ctx: TypeContext, seed: int):
        from app.models import BasicMedia

        subqueries = []
        for source in ctx.sources:
            if source.is_episode:
                continue
            if not source.has_field(field_name):
                # The value is derived in Python (TV dates come from seasons).
                return None
            subquery = BasicMedia.objects._aggregated_sort_subquery(
                source.model,
                ctx.user,
                source.model._meta.model_name,
                sort_key,
                outer_ref="pk",
            )
            if subquery is not None:
                subqueries.append(subquery)
        if not subqueries:
            return Value(None)
        return subqueries[0] if len(subqueries) == 1 else Coalesce(*subqueries)

    return build


def _latest_score(ctx: TypeContext, seed: int):
    """Order by the score on the most recently active scored row."""
    return latest_value(ctx, "score", Q(score__isnull=False))


def _latest_created(ctx: TypeContext, seed: int):
    subqueries = [
        Subquery(
            source.item_rows(ctx.user)
            .order_by()
            .values("item_id")
            .annotate(value=Max("created_at"))
            .values("value")[:1],
        )
        for source in ctx.sources
    ]
    return subqueries[0] if len(subqueries) == 1 else Coalesce(*subqueries)


def random_rank(item_id: int, seed: int) -> int:
    """Return an item's position key in the ``seed`` shuffle."""
    mixed = (item_id * RANDOM_MULTIPLIER + seed % RANDOM_MODULUS) % RANDOM_MODULUS
    return (mixed * RANDOM_MIXER) % RANDOM_MODULUS


def _random_sql(ctx: TypeContext, seed: int):
    mixed = (F("pk") * RANDOM_MULTIPLIER + seed % RANDOM_MODULUS) % RANDOM_MODULUS
    return ExpressionWrapper(
        (mixed * RANDOM_MIXER) % RANDOM_MODULUS,
        output_field=BigIntegerField(),
    )


def _media_list_value(sort_key: str):
    """Reuse the media list's Python value for keys that live in Python."""

    def value(candidate):
        from app.media_list_filters import MediaListEntry, _sort_value

        return _sort_value(
            MediaListEntry(item=candidate.item, media=candidate.media),
            sort_key,
            getattr(candidate, "next_episode", None),
        )

    return value


_MEDIA = frozenset({NEEDS_MEDIA})

SORTS: tuple[SortDef, ...] = (
    SortDef(("title", ""), sql=lambda ctx, seed: Lower("title")),
    SortDef(("release_date", "release_datetime"), sql=_field("release_datetime")),
    SortDef(("critic_rating",), sql=_field("provider_rating")),
    SortDef(("popularity",), sql=_field("trakt_popularity_rank")),
    SortDef(("id", "itemid", "mediaid"), sql=_field("media_id")),
    SortDef(("source",), sql=_field("source")),
    SortDef(("type",), sql=_field("media_type")),
    SortDef(("date_added", "added", "created_at"), sql=_latest_created, tracker=True),
    SortDef(("start_date", "started"), sql=_tracker_aggregate("start_date"), tracker=True),
    SortDef(("end_date", "ended"), sql=_tracker_aggregate("end_date"), tracker=True),
    SortDef(("score",), sql=_latest_score, tracker=True),
    SortDef(("progress", "plays"), sql=_tracker_aggregate("progress"), tracker=True),
    SortDef(("random",), sql=_random_sql),
    # The rest are computed in Python from the hydrated candidate.
    SortDef(("runtime",), needs=_MEDIA),
    SortDef(("time_watched",), needs=_MEDIA),
    SortDef(("time_to_beat",), needs=_MEDIA),
    SortDef(("platform",), needs=_MEDIA),
    SortDef(("author",), needs=_MEDIA),
    SortDef(("updated", "progressed_at"), needs=_MEDIA),
    SortDef(("time_left",), needs=frozenset({NEEDS_MEDIA, NEEDS_MAX_PROGRESS})),
    SortDef(
        ("next_episode_air_date",),
        needs=frozenset({NEEDS_MEDIA, NEEDS_MAX_PROGRESS, NEEDS_NEXT_EPISODE}),
    ),
)

SORTS_BY_KEY = {key: definition for definition in SORTS for key in definition.keys}


def sort_def(sort_key: str) -> SortDef:
    """Return the definition for ``sort_key``, falling back to title."""
    return SORTS_BY_KEY.get(sort_key or "", SORTS_BY_KEY["title"])


def python_key(sort_key: str):
    """Return the Python value function for a key without a SQL expression."""
    return _media_list_value(sort_key)
