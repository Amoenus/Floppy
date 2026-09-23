"""Differential harness: the shared engine against each surface's old path.

Every surface that moves onto ``app.library_query`` must return the same
items, in the same order, as the code it replaces - except where the two
disagree on purpose. This module runs both over one deterministic library and
compares:

- **membership**, for every filter case, with the default sort;
- **order**, for every sort key and direction, with no filters.

Each known difference is listed in ``KNOWN_DIVERGENCES`` with its reason. The
test fails on a new difference *and* on a listed one that has disappeared, so
the table always describes the code as it is. Set
``LIBRARY_QUERY_PARITY_REPORT=1`` to print every difference found.
"""

from __future__ import annotations

import os
from datetime import timedelta
from decimal import Decimal
from unittest import mock

from django.contrib.auth import get_user_model
from django.db.models import Q
from django.test import TestCase
from django.utils import timezone

from app.library_query import FilterValues, LibraryQuery, LibraryQueryExecutor, SortSpec
from app.library_query.adapters import (
    from_home_row_filters,
    from_media_list_filters,
    from_smart_rules,
)
from app.library_query.spec import STATUS_MATCH_ANY
from app.media_list_filters import MediaListFilters, get_media_list_entries
from app.models import (
    TV,
    Anime,
    Book,
    CollectionEntry,
    Game,
    Item,
    ItemTag,
    MediaTypes,
    Movie,
    Sources,
    Status,
    Tag,
)
from lists import smart_rules
from users import home_screen
from users.models import HomeScreenRow

MOVIE = MediaTypes.MOVIE.value
GAME = MediaTypes.GAME.value
BOOK = MediaTypes.BOOK.value
TV_TYPE = MediaTypes.TV.value
ANIME = MediaTypes.ANIME.value

MEDIA = {
    MOVIE: (Movie, Sources.TMDB.value),
    GAME: (Game, Sources.IGDB.value),
    BOOK: (Book, Sources.OPENLIBRARY.value),
    TV_TYPE: (TV, Sources.TMDB.value),
    ANIME: (Anime, Sources.MAL.value),
}
SURFACE_TYPES = (MOVIE, GAME, BOOK, TV_TYPE, ANIME)

# Filter cases in the shared vocabulary. Each surface translates what it
# supports; a case a surface cannot express is skipped for that surface.
FILTER_CASES = {
    "none": {},
    "status_completed": {"status": [Status.COMPLETED.value]},
    "status_in_progress": {"status": [Status.IN_PROGRESS.value]},
    "status_two": {"status": [Status.COMPLETED.value, Status.DROPPED.value]},
    "rated": {"rating": "rated"},
    "not_rated": {"rating": "not_rated"},
    "rating_range": {"rating_min": "5", "rating_max": "8"},
    "collected": {"collection": "collected"},
    "not_collected": {"collection": "not_collected"},
    "genre": {"genre": "drama"},
    "year": {"year": "2020"},
    "year_unknown": {"year": "unknown"},
    "released": {"release": "released"},
    "not_released": {"release": "not_released"},
    "source": {"source": "SOURCE"},
    "language": {"language": "en"},
    "country": {"country": "jp"},
    "platform": {"platform": "switch"},
    "format": {"format": "hardcover"},
    "author": {"author": "ursula le guin"},
    "tag_or": {"tag": ["red", "blue"], "tag_mode": "or"},
    "tag_and": {"tag": ["red", "blue"], "tag_mode": "and"},
    "tag_not": {"tag": ["red"], "tag_mode": "not"},
    "search": {"search": "star"},
    "date_added": {"date_added_from": "DAYS_AGO_20"},
    "completed_window": {"completed_date_from": "DAYS_AGO_20"},
    "release_window": {"release_date_from": "2019-01-01", "release_date_to": "2021-12-31"},
}
SMART_ONLY_KEYS = {"rating_min", "rating_max", "date_added_from", "release_date_from"}
HOME_UNSUPPORTED_KEYS = SMART_ONLY_KEYS | {"search", "completed_date_from"}

SORT_KEYS = (
    "title",
    "score",
    "critic_rating",
    "popularity",
    "progress",
    "plays",
    "release_date",
    "date_added",
    "start_date",
    "end_date",
    "time_to_beat",
    "author",
    "platform",
)

# Filters the media list silently ignores on types whose UI does not offer
# them (an API client could still send them). The engine applies every filter
# to every type.
MEDIA_LIST_TYPE_SCOPED_CASES = {"author", "format", "platform", "language", "country"}

TITLES = (
    "Star Voyage",
    "alpha",
    "Beta",
    "Star Voyage",
    "gamma",
    "Delta",
    "epsilon",
    "Zeta",
    "eta",
    "Theta",
    "Iota",
    "kappa",
)


class LibraryQueryParityTests(TestCase):
    """The engine matches each surface's current results."""

    maxDiff = None

    @classmethod
    def setUpTestData(cls):
        """Build one library that exercises every filter and sort."""
        cls.user = get_user_model().objects.create_user(username="parity", password="x")
        for media_type in SURFACE_TYPES:
            setattr(cls.user, f"{media_type}_enabled", True)
        cls.user.save()
        cls.now = timezone.now()
        red = Tag.objects.create(user=cls.user, name="Red")
        blue = Tag.objects.create(user=cls.user, name="Blue")
        for media_type in SURFACE_TYPES:
            cls._build_type(media_type, red, blue)
        cls._build_anime_on_tv()
        cls.statusless_ids = set(
            Item.objects.filter(media_id__endswith="-10").values_list("pk", flat=True),
        )
        cls.anime_on_tv_ids = set(
            Item.objects.filter(library_media_type=ANIME).values_list("pk", flat=True),
        )
        cls.platform_sensitive_ids = set(
            Item.objects.filter(
                Q(media_id__regex=r"-6$") | Q(platforms=[]) | Q(platforms__isnull=True),
            ).values_list("pk", flat=True),
        )
        cls.collected_attribute_ids = set(
            Item.objects.filter(
                media_id__regex=r"-(6|9)$",
            ).values_list("pk", flat=True),
        )

    @classmethod
    def _build_type(cls, media_type, red, blue):
        model, source = MEDIA[media_type]
        statuses = (
            Status.COMPLETED.value,
            Status.IN_PROGRESS.value,
            Status.PLANNING.value,
            Status.DROPPED.value,
            Status.PAUSED.value,
        )
        for index, title in enumerate(TITLES):
            item = Item.objects.create(
                media_id=f"{media_type}-{index}",
                source=source,
                media_type=media_type,
                title=title,
                image="https://example.com/i.jpg",
                release_datetime=(
                    None
                    if index % 5 == 0
                    else cls.now.replace(year=2016 + index) - timedelta(days=index)
                ),
                provider_rating=None if index % 4 == 0 else float(index % 3),
                trakt_popularity_rank=None if index % 3 == 0 else 100 - index,
                genres=["Drama"] if index % 2 else ["Comedy", "drama "][: index % 3],
                languages=["EN"] if index % 3 else ["ja"],
                country="JP" if index % 4 == 1 else "US",
                platforms=["Switch", "PC"] if index % 2 else ["PS5"],
                format="Hardcover" if index % 3 == 1 else "",
                authors=(
                    [{"name": "Ursula Le Guin"}] if index % 4 == 2 else ["Someone Else"]
                ),
            )
            if index == 11:
                # Collected but never tracked.
                CollectionEntry.objects.create(user=cls.user, item=item)
                continue
            status = statuses[index % len(statuses)] if index != 10 else None
            score = None if index % 3 == 0 else Decimal(index % 10)
            first = cls._track(
                model,
                item,
                status=status,
                score=score,
                progress=index,
                start_date=cls.now - timedelta(days=40 + index),
                end_date=cls.now - timedelta(days=index * 5) if index % 2 else None,
                days_ago=index * 3,
            )
            if index in (3, 6) and model is not TV:  # TV allows one row per item
                # A rewatch: the newer row changes the item's latest status.
                cls._track(
                    model,
                    item,
                    status=Status.DROPPED.value,
                    score=None,
                    progress=1,
                    start_date=cls.now - timedelta(days=2),
                    end_date=cls.now - timedelta(days=1),
                    days_ago=1,
                )
            del first
            if index % 3 == 0:
                CollectionEntry.objects.create(
                    user=cls.user,
                    item=item,
                    resolution="Switch" if index == 6 else "",
                    media_type="hardcover" if index == 9 else "",
                )
            if index % 2:
                ItemTag.objects.create(tag=red, item=item)
            if index % 3 == 1:
                ItemTag.objects.create(tag=blue, item=item)

    @classmethod
    def _build_anime_on_tv(cls):
        """Anime tracked on TV rows, routed to the Anime library."""
        for index in range(2):
            item = Item.objects.create(
                media_id=f"tv-anime-{index}",
                source=Sources.TMDB.value,
                media_type=TV_TYPE,
                library_media_type=ANIME,
                title=f"Grouped Anime {index}",
                image="https://example.com/i.jpg",
            )
            cls._track(TV, item, status=Status.IN_PROGRESS.value, days_ago=index)

    @classmethod
    def _track(cls, model, item, *, days_ago, **fields):
        concrete = {field.attname for field in model._meta.concrete_fields}
        fields = {key: value for key, value in fields.items() if key in concrete}
        row = model.objects.bulk_create([model(item=item, user=cls.user, **fields)])[0]
        model.objects.filter(pk=row.pk).update(
            created_at=cls.now - timedelta(days=days_ago),
        )
        return row

    # -- translation -----------------------------------------------------------

    def _case(self, name, media_type):
        source = MEDIA[media_type][1]
        days_ago = (timezone.localdate() - timedelta(days=20)).isoformat()
        case = {}
        for key, value in FILTER_CASES[name].items():
            if value == "SOURCE":
                value = source  # noqa: PLW2901
            elif value == "DAYS_AGO_20":
                value = days_ago  # noqa: PLW2901
            case[key] = value
        return case

    # -- surfaces --------------------------------------------------------------

    def _smart(self, media_type, case, sort_key, direction):
        rules = smart_rules.normalize_rule_payload(
            {"media_types": [media_type], **case},
            self.user,
        )
        old = smart_rules.collect_matching_item_ids(self.user, rules)
        query = from_smart_rules(
            self.user,
            rules,
            tuple(rules["media_types"]),
            sort_key=sort_key,
            direction=direction,
        )
        new = LibraryQueryExecutor(self.user, query).ids()
        return sorted(old), sorted(new)

    def _media_list(self, media_type, case, sort_key, direction):
        filters = MediaListFilters(
            statuses=tuple(case.get("status", ())),
            rating=case.get("rating", "all"),
            collection=case.get("collection", "all"),
            genre=case.get("genre", ""),
            year=case.get("year", ""),
            completed_date_from=case.get("completed_date_from", ""),
            release=case.get("release", "all"),
            source=case.get("source", ""),
            language=case.get("language", ""),
            country=case.get("country", ""),
            platforms=(case["platform"],) if case.get("platform") else (),
            format=case.get("format", ""),
            author=case.get("author", ""),
            tags=tuple(case.get("tag", ())),
            tag_mode=case.get("tag_mode", "or"),
            search=case.get("search", ""),
            sort=sort_key,
            direction=direction,
            media_type=media_type,
        )
        # Paginated, as the API asks: the SQL fast path runs where it applies.
        entries, _total = get_media_list_entries(
            self.user, media_type, filters, limit=500, offset=0,
        )
        old = [entry.item.pk for entry in entries]
        query = from_media_list_filters(filters, (media_type,))
        new = [item.pk for item in LibraryQueryExecutor(self.user, query).page(0, 500).items]
        return old, new

    def _home(self, media_type, case, sort_key, direction):
        filters = {"status": [], **case}
        row = HomeScreenRow(
            user=self.user,
            media_type=media_type,
            sort_by=sort_key,
            direction=direction,
            filters=filters,
        )
        old = [entry.item.pk for entry in home_screen._library_query_entries(self.user, row)]
        normalized = home_screen._normalized_filter_payload(filters, media_type)
        query = from_home_row_filters(
            self.user,
            normalized,
            media_type,
            sort_key=sort_key,
            direction=direction,
        )
        new = [item.pk for item in LibraryQueryExecutor(self.user, query).page(0, 500).items]
        return old, new

    SURFACES = {
        "smart": (_smart, frozenset()),
        "media_list": (_media_list, SMART_ONLY_KEYS),
        "home": (_home, HOME_UNSUPPORTED_KEYS),
    }

    # -- comparison ------------------------------------------------------------

    def _divergences(self):
        found = {}
        for surface, (run, unsupported) in self.SURFACES.items():
            for media_type in SURFACE_TYPES:
                for name in FILTER_CASES:
                    case = self._case(name, media_type)
                    if unsupported.intersection(case):
                        continue
                    old, new = run(self, media_type, case, "title", "asc")
                    if sorted(old) != sorted(new):
                        found[(surface, "members", media_type, name)] = (old, new)
                if surface == "smart":
                    continue
                for sort_key in SORT_KEYS:
                    for direction in ("asc", "desc"):
                        old, new = run(self, media_type, {}, sort_key, direction)
                        # Membership is checked above; compare the order of
                        # the items both paths return.
                        shared = set(old) & set(new)
                        old = [pk for pk in old if pk in shared]
                        new = [pk for pk in new if pk in shared]
                        if old != new:
                            key = (surface, "order", media_type, f"{sort_key}:{direction}")
                            found[key] = (old, new)
        return found

    def _values(self, key, ids):
        """Return the engine's sort value for each id, in order."""
        surface, _check, media_type, sort = key
        sort_key, direction = sort.split(":")
        if surface == "home":
            from app.library_query.adapters import home_engine_direction

            direction = home_engine_direction(sort_key, direction)
        query = LibraryQuery(
            media_types=(media_type,),
            filters=FilterValues(status_match=STATUS_MATCH_ANY),
            sort=SortSpec(sort_key, direction),
            include_collection_only=True,
        )
        values = {row[-1]: row[0] for row in LibraryQueryExecutor(
            self.user, query,
        )._scan_ranked}
        return [values.get(pk) for pk in ids]

    def _known_divergences(self):
        """Return (name, reason, matches) for each intended difference."""
        titles = dict(Item.objects.values_list("pk", "title"))

        def only(old, new, *, old_only=frozenset(), new_only=frozenset()):
            return (
                set(old) - set(new) <= set(old_only)
                and set(new) - set(old) <= set(new_only)
                and set(old) != set(new)
            )

        return [
            (
                "equal-value ties",
                "Items with equal sort values are ordered by title, then id, in "
                "the requested direction everywhere (the SQL path's rule); the "
                "Python paths kept whatever order the rows arrived in.",
                lambda key, old, new: key[1] == "order"
                and self._values(key, old) == self._values(key, new),
            ),
            (
                "home movie plays",
                "Home read a single movie row's raw progress; it now counts "
                "completed viewings, as the media list does.",
                lambda key, old, new: key[0] == "home"
                and key[1] == "order"
                and key[2] == MOVIE
                and key[3].split(":")[0] in {"plays", "progress"},
            ),
            (
                "platform sort uses the collected copy",
                "Platform sorts by the platform the user collected an item on, "
                "else its first listed platform, and items with no platform "
                'sort last - the media list sorted a missing one as "".',
                lambda key, old, new: key[0] == "media_list"
                and key[3].startswith("platform:")
                and [pk for pk in old if pk not in self.platform_sensitive_ids]
                == [pk for pk in new if pk not in self.platform_sensitive_ids],
            ),
            (
                "home platform sort",
                "Home had no platform sort and silently fell back to title; it "
                "now sorts by platform like the media list.",
                lambda key, old, new: key[0] == "home"
                and key[1] == "order"
                and key[3].startswith("platform:"),
            ),
            (
                "media list type-scoped filters",
                "The media list ignored some filters on types whose UI does not "
                "offer them; the engine applies every filter to every type.",
                lambda key, old, new: key[0] == "media_list"
                and key[1] == "members"
                and key[3] in MEDIA_LIST_TYPE_SCOPED_CASES
                and set(new) < set(old),
            ),
            (
                "home statusless rows",
                "Home now matches the media list its title links to: a tracker "
                'row with no status (an imported rating) is not part of "All".',
                lambda key, old, new: key[0] == "home"
                and only(old, new, old_only=self.statusless_ids, new_only=self.anime_on_tv_ids)
                and bool((set(old) - set(new)) & self.statusless_ids),
            ),
            (
                "home anime library routing",
                "Home now follows the user's anime library preference, as the "
                "media list does, for anime tracked on TV rows.",
                lambda key, old, new: key[0] == "home"
                and only(old, new, old_only=self.anime_on_tv_ids | self.statusless_ids,
                         new_only=self.anime_on_tv_ids)
                and bool((set(old) ^ set(new)) & self.anime_on_tv_ids),
            ),
            (
                "home collected platform and format",
                "Home now counts a collected copy's platform and format, as the "
                "media list does.",
                lambda key, old, new: key[0] == "home"
                and key[3] in {"platform", "format"}
                and only(
                    old,
                    new,
                    old_only=self.statusless_ids,
                    new_only=self.collected_attribute_ids,
                )
                and bool((set(new) - set(old)) & self.collected_attribute_ids),
            ),
        ]

    def test_engine_matches_every_surface_except_known_divergences(self):
        """Differences between old and new paths are exactly the declared ones."""
        with mock.patch("app.models.Item.fetch_releases", return_value=None):
            found = self._divergences()
        rules = self._known_divergences()
        unexplained = {}
        used = set()
        for key, (old, new) in sorted(found.items()):
            matched = [name for name, _reason, matches in rules if matches(key, old, new)]
            used.update(matched)
            if not matched:
                unexplained[key] = _describe(old, new)
            if os.environ.get("LIBRARY_QUERY_PARITY_REPORT"):
                print(key, matched, _describe(old, new))
        stale = sorted({name for name, _reason, _matches in rules} - used)
        self.assertEqual(
            (unexplained, stale),
            ({}, []),
            "Unexplained differences (fix the engine or declare them) and "
            "declared ones that no longer occur (remove them).",
        )


def _describe(old, new) -> str:
    old_set, new_set = set(old), set(new)
    if old_set != new_set:
        return f"old-only={sorted(old_set - new_set)} new-only={sorted(new_set - old_set)}"
    return f"order old={old} new={new}"
