"""Cast & Crew statistics for the statistics page.

Featured person spotlight, role leaders, studio footprint, and taste-signal
rollups (top genres, era spotlight, collection mix). Reshapes data already
computed by `statistics_talent._aggregate_top_talent()` and
`stats_video._compute_movie_tv_top_genres()` rather than re-querying from
scratch.
"""

import logging
import math
from collections import Counter, defaultdict

from django.conf import settings
from django.db.models import Count, Q

from app import helpers, statistics_cache
from app.models import (
    CollectionEntry,
    CreditRoleType,
    Item,
    ItemPersonCredit,
    MediaTypes,
    Movie,
    Person,
    PersonGender,
)
from app.statistics_talent import (
    _aggregate_top_talent,
    _tv_episode_play_rows,
)

logger = logging.getLogger(__name__)

# Mirrors GENRE_PALETTE in statistics-charts.js for consistent genre coloring.
GENRE_PALETTE = [
    "#6366f1", "#ec4899", "#10b981", "#f59e0b", "#3b82f6",
    "#8b5cf6", "#ef4444", "#14b8a6", "#f97316", "#a855f7",
    "#06b6d4", "#84cc16",
]

# One color per "Known for" pill role — kept in sync with the role
# classification already used across top talent (actor/actress/director/
# writer) plus a voice-actor variant derived from ItemPersonCredit.role text.
KNOWN_FOR_PILL_STYLES = {
    "actor": {"label": "Actor", "classes": "bg-indigo-500/20 text-indigo-300"},
    "actress": {"label": "Actress", "classes": "bg-pink-500/20 text-pink-300"},
    "director": {"label": "Director", "classes": "bg-amber-500/20 text-amber-300"},
    "writer": {"label": "Writer", "classes": "bg-emerald-500/20 text-emerald-300"},
    "voice_actor": {"label": "Voice Actor", "classes": "bg-cyan-500/20 text-cyan-300"},
}

ROLE_LEADER_COLUMNS = (
    ("top_actors", "Actors"),
    ("top_actresses", "Actresses"),
    ("top_directors", "Directors"),
    ("top_writers", "Writers"),
)


def _compact_role_leader_time_label(total_minutes):
    """Return a single-unit watched-time label for narrow leaderboard cells."""
    total_minutes = int(total_minutes or 0)
    if total_minutes >= 60:
        return f"{math.floor(total_minutes / 60)}h"
    return f"{total_minutes}m"


def get_role_leaders(top_talent, sort_by=None):
    """Reshape `_aggregate_top_talent()`'s `by_sort` output into a 4-column payload.

    Pure reshape — no new queries. Returns all entries supplied by the existing
    aggregation (already capped at STATISTICS_TOP_N there).
    """
    if not isinstance(top_talent, dict):
        return {"columns": []}

    sort_by = sort_by or top_talent.get("sort_by", "plays")
    by_sort = top_talent.get("by_sort") or {}
    selected = by_sort.get(sort_by) or {
        key: top_talent.get(key, []) for key, _label in ROLE_LEADER_COLUMNS
    }

    columns = []
    for bucket_key, label in ROLE_LEADER_COLUMNS:
        raw_entries = selected.get(bucket_key) or []
        entries = []
        for entry in raw_entries:
            entry_copy = dict(entry)
            if sort_by == "time":
                entry_copy["display_metric"] = _compact_role_leader_time_label(
                    entry_copy.get("watched_minutes", 0),
                )
            elif sort_by == "titles":
                entry_copy["display_metric"] = entry_copy.get("unique_titles", 0)
            else:
                entry_copy["display_metric"] = entry_copy.get("plays", 0)
            entries.append(entry_copy)
        if not entries:
            continue
        columns.append(
            {
                "bucket": bucket_key.removeprefix("top_"),
                "label": label,
                "entries": entries,
            },
        )

    return {"columns": columns, "sort_by": sort_by}


def _known_for_pills(person, bucket_payload):
    """Derive "Known for" pills from nonzero role buckets plus voice credits."""
    pills = []
    for bucket in ("actor", "actress", "director", "writer"):
        if bucket == bucket_payload.get("bucket"):
            style = KNOWN_FOR_PILL_STYLES[bucket]
            pills.append({"label": style["label"], "classes": style["classes"]})

    is_voice_actor = ItemPersonCredit.objects.filter(
        person_id=person.id,
        role_type=CreditRoleType.CAST.value,
        role__icontains="voice",
    ).exists()
    if is_voice_actor:
        style = KNOWN_FOR_PILL_STYLES["voice_actor"]
        pills.append({"label": style["label"], "classes": style["classes"]})

    if not pills:
        department = (person.known_for_department or "").strip().lower()
        if department == "acting":
            is_female = person.gender == PersonGender.FEMALE.value
            fallback_bucket = "actress" if is_female else "actor"
            style = KNOWN_FOR_PILL_STYLES[fallback_bucket]
            pills.append({"label": style["label"], "classes": style["classes"]})
        elif department == "directing":
            style = KNOWN_FOR_PILL_STYLES["director"]
            pills.append({"label": style["label"], "classes": style["classes"]})
        elif department == "writing":
            style = KNOWN_FOR_PILL_STYLES["writer"]
            pills.append({"label": style["label"], "classes": style["classes"]})

    return pills


def _build_person_payload_from_totals(person, totals, total_library_titles=None):
    """Build the Featured Repeat Player card payload from an already-fetched totals."""
    unique_titles = totals.get("unique_titles", 0)
    pct_of_library = 0.0
    if total_library_titles:
        pct_of_library = round((unique_titles / total_library_titles) * 100, 1)

    return {
        "name": person.name,
        "image": person.image or settings.IMG_NONE,
        "source": person.source,
        "person_id": person.source_person_id,
        "bucket": totals.get("bucket"),
        "plays": totals.get("plays", 0),
        "watched_minutes": totals.get("watched_minutes", 0),
        "watched_time": totals.get("watched_time", "0min"),
        "unique_movies": totals.get("unique_movies", 0),
        "unique_shows": totals.get("unique_shows", 0),
        "unique_titles": unique_titles,
        "pct_of_library": pct_of_library,
        "known_for_pills": _known_for_pills(person, totals),
    }


def _media_strip_from_totals(totals, limit=25, sort_by="plays"):
    """Build the media-strip item list from an already-fetched totals dict."""
    plays_by_media_key = totals.get("plays_by_media_key") or {}
    minutes_by_media_key = totals.get("minutes_by_media_key") or {}
    if not plays_by_media_key:
        return []

    if sort_by == "time":
        media_keys = sorted(
            plays_by_media_key.keys(),
            key=lambda key: (
                -minutes_by_media_key.get(key, 0),
                -plays_by_media_key.get(key, 0),
                key[1],
            ),
        )[:limit]
    else:
        media_keys = sorted(
            plays_by_media_key.keys(),
            key=lambda key: (
                -plays_by_media_key.get(key, 0),
                -minutes_by_media_key.get(key, 0),
                key[1],
            ),
        )[:limit]

    items_by_key = {}
    media_ids_by_type = defaultdict(list)
    for media_type, media_id in media_keys:
        media_ids_by_type[media_type].append(media_id)

    for media_type, media_ids in media_ids_by_type.items():
        item_qs = Item.objects.filter(media_type=media_type, media_id__in=media_ids)
        for item in item_qs:
            items_by_key[(item.media_type, str(item.media_id))] = item

    strip = []
    for media_key in media_keys:
        item = items_by_key.get(media_key)
        if not item:
            continue
        plays = plays_by_media_key.get(media_key, 0)
        watched_minutes = minutes_by_media_key.get(media_key, 0)
        if sort_by == "time":
            role = helpers.minutes_to_hhmm(watched_minutes or 0)
        elif sort_by == "titles":
            role = "In library"
        else:
            role = f"{plays} play{'s' if plays != 1 else ''}"
        strip.append(
            {
                "title": item.title,
                "image": item.image or settings.IMG_NONE,
                "media_type": item.media_type,
                "media_id": item.media_id,
                "source": item.source,
                "year": item.release_datetime.year if item.release_datetime else None,
                "vote_average": item.provider_rating,
                "role": role,
                "department": "",
                "credit_type": "",
            },
        )

    if sort_by == "titles":
        strip.sort(key=lambda entry: ((entry.get("title") or "").lower(), entry.get("year") or 0))

    return strip


def get_featured_person_with_strip(
    user,
    person_source,
    person_id,
    start_date,
    end_date,
    total_library_titles=None,
    strip_limit=25,
    sort_by="plays",
):
    """Compute the featured-person payload and media strip from one shared totals call.

    Both pieces of data are derived from the same `get_person_talent_totals()` result,
    which is the expensive part (unscoped episode/movie/credit scans) — call it once
    per person per request instead of once per consumer.
    """
    totals = statistics_cache.get_person_talent_totals(
        user,
        person_source,
        person_id,
        start_date,
        end_date,
    )
    if not totals:
        return None, []

    person = Person.objects.filter(
        source=person_source,
        source_person_id=str(person_id),
    ).first()
    if not person:
        return None, []

    payload = _build_person_payload_from_totals(person, totals, total_library_titles)
    strip = _media_strip_from_totals(totals, limit=strip_limit, sort_by=sort_by)
    return payload, strip


def pick_default_featured_candidate(top_talent, sort_by=None):
    """Pick the default Featured Repeat Player candidate.

    Default selection = the person with the highest `unique_titles` across the
    four leaderboards (actors/actresses/directors/writers).
    """
    if not isinstance(top_talent, dict):
        return None

    sort_by = sort_by or top_talent.get("sort_by", "plays")
    by_sort = top_talent.get("by_sort") or {}
    selected = by_sort.get(sort_by) or top_talent

    candidates = []
    for bucket_key, _label in ROLE_LEADER_COLUMNS:
        candidates.extend(selected.get(bucket_key) or [])

    if not candidates:
        return None

    return max(
        candidates,
        key=lambda entry: (entry.get("unique_titles", 0), entry.get("plays", 0)),
    )


def get_featured_repeat_player_with_strip(
    user,
    start_date,
    end_date,
    top_talent,
    total_library_titles=None,
    strip_limit=25,
    sort_by=None,
):
    """Return (featured_payload, media_strip) for the default Featured Repeat Player."""
    active_sort = sort_by or top_talent.get("sort_by", "plays")
    best = pick_default_featured_candidate(top_talent, sort_by=active_sort)
    if not best:
        return None, []

    return get_featured_person_with_strip(
        user,
        best.get("source"),
        best.get("person_id"),
        start_date,
        end_date,
        total_library_titles=total_library_titles,
        strip_limit=strip_limit,
        sort_by=active_sort,
    )


def build_media_strip_row(
    items,
    row_id="person-media-strip",
    person_name=None,
    total_titles=None,
    sort_by="plays",
):
    """Wrap a plain item list into the `row` shape `_scrollable_row.html` expects."""
    items = items or []
    title = f"{person_name}'s Titles" if person_name else "Titles"
    title_count = total_titles if total_titles is not None else len(items)
    sort_label = {
        "plays": "plays",
        "time": "time watched",
        "titles": "title",
    }.get(sort_by, "plays")
    summary = f"{title_count} title{'s' if title_count != 1 else ''} · sorted by {sort_label}"
    return {
        "row_id": row_id,
        "title": title,
        "summary": summary,
        "items": items,
        "total": len(items),
        "loaded_count": len(items),
        "card_width_class": "w-32 sm:w-36",
        "grid_class": "",
        "show_played_chip": False,
    }


def _run_comparison_studio_delta(
    user,
    studios,
    comparison_start_date,
    comparison_end_date,
):
    """Re-run studio aggregation over the comparison window and return a delta."""
    try:
        comparison_talent = _aggregate_top_talent(
            user,
            comparison_start_date,
            comparison_end_date,
            schedule_missing_backfill=False,
        )
    except Exception as exc:  # noqa: BLE001 - best effort comparison
        logger.debug(
            "studio_footprint_comparison_failed user_id=%s error=%s",
            user.id,
            exc,
        )
        return None

    comparison_by_sort = comparison_talent.get("by_sort") or {}
    comparison_studios = (
        (comparison_by_sort.get("plays") or {}).get("top_studios") or []
    )
    comparison_appearances = sum(
        studio.get("plays", 0) for studio in comparison_studios
    )
    current_appearances = sum(studio.get("plays", 0) for studio in studios)
    if comparison_appearances <= 0:
        return None

    delta_pct = round(
        ((current_appearances - comparison_appearances) / comparison_appearances) * 100,
        1,
    )
    return {"pct": delta_pct, "is_positive": delta_pct >= 0}


STUDIO_FOOTPRINT_LIMIT = 5


def get_studio_footprint(
    user,
    start_date,
    end_date,
    top_talent,
    comparison_start_date=None,
    comparison_end_date=None,
    limit=STUDIO_FOOTPRINT_LIMIT,
):
    """Reshape `top_talent.by_sort.plays.top_studios` into a percentage footprint.

    Percentages are computed against the full studio list (so they reflect true
    library share) but only the top `limit` studios are returned, keeping the
    card focused instead of diluted by a long tail.

    If a comparison window is provided, re-runs the studio aggregation over it to
    compute a "vs last year"-style delta; omitted entirely when comparison is off.
    """
    del start_date, end_date  # top_talent already reflects the active range
    if not isinstance(top_talent, dict):
        return {"studios": [], "delta": None}

    by_sort = top_talent.get("by_sort") or {}
    studios = (
        (by_sort.get("plays") or {}).get("top_studios")
        or top_talent.get("top_studios")
        or []
    )
    if not studios:
        return {"studios": [], "delta": None}

    total_plays = sum(studio.get("plays", 0) for studio in studios) or 1
    studio_rows = [
        {**studio, "pct": round((studio.get("plays", 0) / total_plays) * 100, 1)}
        for studio in studios[:limit]
    ]

    delta = None
    if comparison_start_date and comparison_end_date:
        delta = _run_comparison_studio_delta(
            user,
            studios,
            comparison_start_date,
            comparison_end_date,
        )

    return {"studios": studio_rows, "delta": delta}


def get_top_genres_combined(movie_consumption, tv_consumption, limit=5):
    """Merge already-computed movie/TV `top_genres`, weighted by minutes."""
    merged = defaultdict(lambda: {"name": "", "minutes": 0, "plays": 0})
    for consumption in (movie_consumption, tv_consumption):
        if not isinstance(consumption, dict):
            continue
        for genre in consumption.get("top_genres") or []:
            name = genre.get("name")
            if not name:
                continue
            merged[name]["name"] = name
            merged[name]["minutes"] += genre.get("minutes", 0)
            merged[name]["plays"] += genre.get("plays", 0)

    if not merged:
        return []

    ranked = sorted(
        merged.values(),
        key=lambda row: (row["minutes"], row["plays"]),
        reverse=True,
    )[:limit]
    total_minutes = sum(row["minutes"] for row in ranked) or 1
    for index, row in enumerate(ranked):
        row["pct"] = round((row["minutes"] / total_minutes) * 100, 1)
        row["formatted_duration"] = helpers.minutes_to_hhmm(row["minutes"])
        row["color"] = GENRE_PALETTE[index % len(GENRE_PALETTE)]

    return ranked


def _watched_movie_play_counts(user, start_date, end_date):
    """Return {item_id: play_count} for the user's watched movies in range."""
    movie_play_counts = Counter()
    movies_qs = Movie.objects.filter(user=user).filter(
        Q(end_date__isnull=False) | Q(start_date__isnull=False),
    )
    if start_date:
        movies_qs = movies_qs.filter(
            Q(end_date__gte=start_date)
            | (Q(end_date__isnull=True) & Q(start_date__gte=start_date)),
        )
    if end_date:
        movies_qs = movies_qs.filter(
            Q(end_date__lte=end_date)
            | (Q(end_date__isnull=True) & Q(start_date__lte=end_date)),
        )
    for item_id in movies_qs.values_list("item_id", flat=True).iterator():
        if item_id:
            movie_play_counts[item_id] += 1
    return movie_play_counts


def _watched_tv_play_counts(user, start_date, end_date):
    """Return {item_id: play_count} for the user's watched TV shows in range."""
    tv_episode_rows = _tv_episode_play_rows(user, start_date, end_date)
    tv_play_counts = Counter()
    for episode_row in tv_episode_rows.episode_play_rows:
        tv_item_id = episode_row[2]
        if tv_item_id:
            tv_play_counts[tv_item_id] += 1
    return tv_play_counts


def get_era_spotlight(user, start_date, end_date, limit=5):
    """Decade bucketing of watched movie/TV titles, keyed by Item.release_datetime."""
    movie_play_counts = _watched_movie_play_counts(user, start_date, end_date)
    tv_play_counts = _watched_tv_play_counts(user, start_date, end_date)

    all_item_ids = set(movie_play_counts.keys()) | set(tv_play_counts.keys())
    if not all_item_ids:
        return []

    decade_stats = defaultdict(
        lambda: {"decade": 0, "label": "", "plays": 0, "titles": set()},
    )
    release_years = Item.objects.filter(id__in=all_item_ids).values_list(
        "id",
        "release_datetime__year",
    )
    for item_id, release_year in release_years:
        if not release_year:
            continue
        plays = movie_play_counts.get(item_id, 0) + tv_play_counts.get(item_id, 0)
        if plays <= 0:
            continue
        decade = (release_year // 10) * 10
        decade_stats[decade]["decade"] = decade
        decade_stats[decade]["label"] = f"{decade}s"
        decade_stats[decade]["plays"] += plays
        decade_stats[decade]["titles"].add(item_id)

    ranked = sorted(
        decade_stats.values(),
        key=lambda row: row["plays"],
        reverse=True,
    )[:limit]
    total_plays = sum(row["plays"] for row in ranked) or 1
    return [
        {
            "decade": row["decade"],
            "label": row["label"],
            "plays": row["plays"],
            "unique_titles": len(row["titles"]),
            "pct": round((row["plays"] / total_plays) * 100, 1),
        }
        for row in ranked
    ]


def get_collection_mix(user, limit=5):
    """Group the user's owned video CollectionEntry rows by format (media_type).

    `media_type` here is the free-text physical/digital source field (bluray,
    dvd, digital, etc.) and is commonly left blank, so blank entries are kept
    and labeled "Unspecified" rather than excluded — dropping them understated
    the total and made the card look empty even when a user had a collection.
    """
    video_media_types = (
        MediaTypes.MOVIE.value,
        MediaTypes.TV.value,
        MediaTypes.SEASON.value,
        MediaTypes.EPISODE.value,
        MediaTypes.ANIME.value,
    )
    rows = list(
        CollectionEntry.objects.filter(
            user=user,
            item__media_type__in=video_media_types,
        )
        .values("media_type")
        .annotate(count=Count("id"))
        .order_by("-count"),
    )
    total = sum(row["count"] for row in rows)
    if not total:
        return {"formats": [], "total": 0}

    formats = [
        {
            "name": row["media_type"] or "Unspecified",
            "count": row["count"],
            "pct": round((row["count"] / total) * 100, 1),
        }
        for row in rows[:limit]
    ]
    return {"formats": formats, "total": total}
