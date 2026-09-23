"""Run a ``LibraryQuery``: one page of ordered items and the total, in bounded work.

Two paths, chosen from the filter and sort registries rather than a list of
exceptions:

- **SQL**: every active filter and the sort compile to SQL. Filtering,
  ordering, ``COUNT`` and ``LIMIT``/``OFFSET`` all run in the database; only
  the page's items are loaded.
- **Scan**: a filter or the sort needs Python. Candidates are narrowed by
  every SQL-capable condition first, then read in fixed-size batches that
  keep only ``(sort value, title, id)`` per match. The page's items are
  loaded at the end. Memory and hydration are bounded by the batch and the
  page; computing Python values is still one pass over the SQL-narrowed
  candidates.

The executor returns ``Item`` rows. Decorating them (tracker rows, card
images, progress) is the calling surface's job, and it only ever sees a page.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import cached_property
from itertools import islice
from typing import TYPE_CHECKING

from django.db.models import Exists, F, OuterRef, Q
from django.db.models.functions import Coalesce, Lower
from django.utils import timezone

from app.library_query import filters as filter_registry
from app.library_query import sorts as sort_registry
from app.library_query.trackers import tracker_sources
from app.models.choices import MediaTypes, Sources
from app.models.item import Item

if TYPE_CHECKING:
    from app.library_query.spec import LibraryQuery

DEFAULT_BATCH_SIZE = 256
DESC = "desc"


@dataclass
class Candidate:
    """An item being evaluated, and its aggregated tracker row once loaded."""

    item: Item
    media: object | None = None
    next_episode: dict | None = None


@dataclass
class Page:
    """One ordered page of items and the size of the full result."""

    items: list[Item]
    total: int
    used_sql: bool


class LibraryQueryExecutor:
    """Evaluate one ``LibraryQuery`` for one user."""

    def __init__(self, user, query: LibraryQuery, *, batch_size: int = DEFAULT_BATCH_SIZE):
        """Prepare ``query`` for ``user``; nothing runs until it is asked for."""
        self.user = user
        self.query = query
        self.batch_size = batch_size
        self.today = timezone.localdate()

    # -- compilation ----------------------------------------------------------

    @cached_property
    def contexts(self) -> list[filter_registry.TypeContext]:
        """Return one compilation context per requested media type."""
        return [
            filter_registry.TypeContext(
                user=self.user,
                media_type=media_type,
                sources=tuple(tracker_sources(self.user, media_type)),
                today=self.today,
                provider_region=self.query.provider_region,
                pinned_providers=self.query.pinned_providers,
            )
            for media_type in self.query.media_types
        ]

    def _active(self, ctx):
        return filter_registry.active_filters(self.query.filters, ctx.media_type)

    def _membership_q(self, ctx) -> Q:
        """Return the condition for an item being in this type's candidates."""
        values = self.query.filters
        active = self._active(ctx)
        type_q = Q(media_type=ctx.media_type) | Q(library_media_type=ctx.media_type)

        if self.query.list_id is not None:
            from lists.models import CustomListItem

            in_list = Q(
                Exists(
                    CustomListItem.objects.filter(
                        custom_list_id=self.query.list_id,
                        item_id=OuterRef("pk"),
                    ),
                ),
            )
            row_filters = [d for d in active if d.row is not None and d.key != "status"]
            tracked = in_list & type_q
            if row_filters or values.statuses:
                tracked &= self._tracked_q(ctx, active)
            return tracked

        membership = self._tracked_q(ctx, active)
        if self.query.include_collection_only and filter_registry.collection_only_allowed(
            values,
        ):
            membership |= self._collection_only_q(ctx)
        return membership

    def _tracked_q(self, ctx, active) -> Q:
        """Return: a tracker row of this type satisfies every row condition."""
        per_source = []
        for source in ctx.sources:
            row_q = Q()
            for definition in active:
                if definition.row is None:
                    continue
                condition = definition.row(self.query.filters, source, ctx)
                if condition is not None:
                    row_q &= condition
            per_source.append(
                source.item_q & Q(Exists(source.item_rows(self.user).filter(row_q))),
            )
        return filter_registry.any_q(per_source)

    def _collection_only_q(self, ctx) -> Q:
        """Return collected items of this type that have no tracker row."""
        from app.models.discovery import CollectionEntry

        type_q = Q(media_type=ctx.media_type) | Q(library_media_type=ctx.media_type)
        direct = Q(
            Exists(
                CollectionEntry.objects.filter(user=self.user, item_id=OuterRef("pk")),
            ),
        ) & ~Q(media_type=MediaTypes.EPISODE.value)
        collected = direct
        if ctx.media_type in (MediaTypes.TV.value, MediaTypes.ANIME.value):
            collected |= Q(
                media_type__in=(MediaTypes.TV.value, MediaTypes.ANIME.value),
            ) & Q(
                Exists(
                    CollectionEntry.objects.filter(
                        user=self.user,
                        item__media_type=MediaTypes.EPISODE.value,
                        item__media_id=OuterRef("media_id"),
                        item__source=OuterRef("source"),
                    ),
                ),
            )
        untracked = ~filter_registry.any_q(
            [Q(Exists(source.item_rows(self.user))) for source in ctx.sources],
        )
        return type_q & collected & untracked

    def _item_q(self, ctx) -> Q:
        """Return every SQL condition for this media type."""
        condition = self._membership_q(ctx)
        for definition in self._active(ctx):
            if definition.sql is None:
                continue
            compiled = definition.sql(self.query.filters, ctx)
            if compiled is not None:
                condition &= compiled
        return condition

    @cached_property
    def _predicates_by_type(self) -> dict[str, list]:
        return {
            ctx.media_type: [d for d in self._active(ctx) if d.predicate is not None]
            for ctx in self.contexts
        }

    def _predicates(self, ctx):
        return self._predicates_by_type[ctx.media_type]

    @cached_property
    def _needs_scan(self) -> bool:
        return any(self._predicates_by_type.values())

    def _union_exists(self):
        """Return: the item belongs to a list the query always includes."""
        from lists.models import CustomListItem

        return Exists(
            CustomListItem.objects.filter(
                custom_list_id__in=self.query.union_list_ids,
                item_id=OuterRef("pk"),
            ),
        )

    @cached_property
    def filtered(self):
        """Return the ``Item`` queryset narrowed by every SQL condition."""
        if not self.contexts:
            queryset = Item.objects.none()
        else:
            queryset = Item.objects.filter(
                filter_registry.any_q([self._item_q(ctx) for ctx in self.contexts]),
            )
        hidden_ids = self._cross_provider_hidden_ids(queryset)
        if hidden_ids:
            queryset = queryset.exclude(pk__in=hidden_ids)
        if self.query.union_list_ids:
            queryset = Item.objects.filter(
                Q(pk__in=queryset.values("pk")) | Q(self._union_exists()),
            )
        return queryset

    @cached_property
    def sort(self):
        """Return the definition of the requested sort key."""
        return sort_registry.sort_def(self.query.sort.key)

    @cached_property
    def direction(self) -> str:
        """Return the requested direction, or the key's default."""
        from app.models import BasicMedia

        return BasicMedia.objects.resolve_direction(
            self.query.sort.key,
            self.query.sort.direction,
        )

    @cached_property
    def uses_sql(self) -> bool:
        """Return whether filters and sort all compile to SQL."""
        return self.sort.sql is not None and not self._needs_scan

    def _sort_expression(self):
        expressions = [self.sort.sql(ctx, self.query.sort.seed) for ctx in self.contexts]
        if len(expressions) == 1 or not self.sort.tracker:
            return expressions[0]
        return Coalesce(*expressions)

    def _ordered(self, queryset):
        expression = self._sort_expression()
        descending = self.direction == DESC
        queryset = queryset.annotate(_library_sort=expression)
        value = F("_library_sort")
        return queryset.order_by(
            value.desc(nulls_last=True) if descending else value.asc(nulls_last=True),
            Lower("title").desc() if descending else Lower("title").asc(),
            F("pk").desc() if descending else F("pk").asc(),
        )

    # -- cross-provider aliases -----------------------------------------------

    def _cross_provider_hidden_ids(self, queryset) -> set[int]:
        """Return TMDB items hidden because their TVDB alias is also listed (#639)."""
        if not self.query.dedupe_cross_provider:
            return set()
        show_types = {MediaTypes.TV.value, MediaTypes.ANIME.value, MediaTypes.SEASON.value}
        if not show_types.intersection(self.query.media_types):
            return set()
        from app.services.item_merge import dedupe_cross_provider_items

        rows = queryset.filter(
            media_type__in=(MediaTypes.TV.value, MediaTypes.SEASON.value),
            source__in=(Sources.TMDB.value, Sources.TVDB.value),
        ).only("id", "media_id", "media_type", "season_number", "source", "provider_external_ids")
        items = list(rows)
        if not any(item.source == Sources.TVDB.value for item in items):
            return set()
        kept = dedupe_cross_provider_items(
            items,
            getattr(self.user, "tv_metadata_source_default", Sources.TMDB.value),
        )
        return {item.id for item in items} - {item.id for item in kept}

    # -- evaluation -----------------------------------------------------------

    def count(self) -> int:
        """Return how many items match."""
        if not self._needs_scan:
            return self.filtered.count()
        return len(self._scan_ranked)

    def ids(self) -> set[int]:
        """Return every matching item id (for smart-list membership)."""
        if not self._needs_scan:
            return set(self.filtered.values_list("pk", flat=True))
        return {item_id for *_rest, item_id in self._scan_ranked}

    def page(self, offset: int, limit: int) -> Page:
        """Return ``limit`` items starting at ``offset``, and the total."""
        offset = max(0, offset)
        if self.uses_sql:
            ordered = self._ordered(self.filtered)
            total = ordered.count()
            return Page(list(ordered[offset : offset + limit]), total, used_sql=True)

        ranked = self._scan_ranked
        selected_ids = [item_id for *_rest, item_id in ranked[offset : offset + limit]]
        by_id = Item.objects.in_bulk(selected_ids)
        return Page([by_id[i] for i in selected_ids if i in by_id], len(ranked), False)

    @cached_property
    def _scan_ranked(self) -> list[tuple]:
        """Return ``(value, title, id)`` for every match, in order."""
        queryset = self.filtered
        if self.sort.sql is not None:
            queryset = queryset.annotate(_library_sort=self._sort_expression())
        if self.query.union_list_ids:
            queryset = queryset.annotate(_in_union=self._union_exists())

        needs = set(self.sort.needs)
        for ctx in self.contexts:
            for definition in self._predicates(ctx):
                needs |= definition.needs
        contexts_by_type = {ctx.media_type: ctx for ctx in self.contexts}
        python_key = None if self.sort.sql is not None else sort_registry.python_key(
            self.query.sort.key,
        )

        rows = []
        iterator = queryset.iterator(chunk_size=self.batch_size)
        while True:
            batch = [Candidate(item) for item in islice(iterator, self.batch_size)]
            if not batch:
                break
            if filter_registry.NEEDS_MEDIA in needs:
                _attach_media(self.user, batch, needs)
            for candidate in batch:
                if not getattr(candidate.item, "_in_union", False):
                    ctx = _context_for(candidate.item, contexts_by_type)
                    if ctx is not None and not all(
                        definition.predicate(candidate, self.query.filters, ctx)
                        for definition in self._predicates(ctx)
                    ):
                        continue
                value = (
                    candidate.item._library_sort
                    if python_key is None
                    else python_key(candidate)
                )
                rows.append((value, (candidate.item.title or "").lower(), candidate.item.pk))

        return order_rows(rows, descending=self.direction == DESC)


def order_rows(rows: list[tuple], *, descending: bool) -> list[tuple]:
    """Order ``(value, title, id)`` rows like the SQL path: nulls last, then title, id."""
    present = [row for row in rows if row[0] is not None]
    missing = [row for row in rows if row[0] is None]
    present.sort(reverse=descending)
    missing.sort(key=lambda row: (row[1], row[2]), reverse=descending)
    return present + missing


def _context_for(item, contexts_by_type):
    for media_type in (item.library_media_type, item.media_type):
        ctx = contexts_by_type.get(media_type)
        if ctx is not None:
            return ctx
    return None


def _attach_media(user, batch: list[Candidate], needs: set[str]) -> None:
    """Load each candidate's aggregated tracker row, for this batch only."""
    from django.apps import apps

    from app.models import BasicMedia

    by_type: dict[str, list[Candidate]] = {}
    for candidate in batch:
        if candidate.item.media_type == MediaTypes.EPISODE.value:
            continue
        by_type.setdefault(candidate.item.media_type, []).append(candidate)

    for media_type, candidates in by_type.items():
        model = apps.get_model("app", media_type)
        rows = model.objects.filter(
            user=user,
            item_id__in=[candidate.item.pk for candidate in candidates],
        ).select_related("item")
        aggregated = BasicMedia.objects._aggregate_duplicate_data(rows, user, media_type)
        latest = {}
        for media in aggregated:
            current = latest.get(media.item_id)
            if current is None or media.created_at > current.created_at:
                latest[media.item_id] = media
        tracked = []
        for candidate in candidates:
            candidate.media = latest.get(candidate.item.pk)
            if candidate.media is not None:
                tracked.append(candidate.media)
        if tracked and filter_registry.NEEDS_MAX_PROGRESS in needs:
            BasicMedia.objects.annotate_max_progress(tracked, media_type)
        if sort_registry.NEEDS_NEXT_EPISODE in needs:
            from app.media_list_filters import next_episode_for_media

            for candidate in candidates:
                if candidate.media is not None:
                    candidate.next_episode = next_episode_for_media(candidate.media)
