"""IMDB public non-commercial datasets provider.

Downloads title.basics.tsv.gz, title.principals.tsv.gz, name.basics.tsv.gz,
title.ratings.tsv.gz, and title.episode.tsv.gz from
https://datasets.imdbws.com/ (updated daily, free for non-commercial use).
Used to resolve a video game's IMDB title and pull its cast/crew, and to
sync IMDB's public aggregate ratings for movies, shows, and episodes. Each
function streams the gzip response and discards rows that don't match the
requested filter to keep memory low.
"""

import csv
import gzip
import logging
import urllib.request

logger = logging.getLogger(__name__)

TITLE_BASICS_URL = "https://datasets.imdbws.com/title.basics.tsv.gz"
PRINCIPALS_URL = "https://datasets.imdbws.com/title.principals.tsv.gz"
NAME_BASICS_URL = "https://datasets.imdbws.com/name.basics.tsv.gz"
TITLE_RATINGS_URL = "https://datasets.imdbws.com/title.ratings.tsv.gz"
TITLE_EPISODE_URL = "https://datasets.imdbws.com/title.episode.tsv.gz"

_DOWNLOAD_TIMEOUT = 120
_VIDEO_GAME_TITLE_TYPE = "videoGame"


def download_videogame_title_index() -> dict[str, tuple[str, int | None]]:
    """Download and parse title.basics.tsv.gz, filtered to video game titles.

    Returns {tconst: (primaryTitle, startYear)}. startYear is None when IMDB
    doesn't have a release year on file for that title.
    """
    logger.info(
        "imdb_datasets: downloading title index from %s",
        TITLE_BASICS_URL,
    )
    index: dict[str, tuple[str, int | None]] = {}

    with (
        urllib.request.urlopen(TITLE_BASICS_URL, timeout=_DOWNLOAD_TIMEOUT) as resp,  # noqa: S310
        gzip.open(resp, "rt", encoding="utf-8") as f,
    ):
        reader = csv.DictReader(f, delimiter="\t")
        for row in reader:
            if row.get("titleType") != _VIDEO_GAME_TITLE_TYPE:
                continue
            tconst = row.get("tconst", "").strip()
            title = row.get("primaryTitle", "").strip()
            if not tconst or not title:
                continue
            year_raw = (row.get("startYear") or "").strip()
            year = int(year_raw) if year_raw and year_raw != "\\N" else None
            index[tconst] = (title, year)

    logger.info("imdb_datasets: loaded %d video game titles", len(index))
    return index


def download_principals(tconsts: set[str]) -> dict[str, list[dict]]:
    """Download and parse title.principals.tsv.gz, filtered to tconsts.

    Returns {tconst: [{"nconst", "category", "job", "characters", "ordering"}]}.
    """
    if not tconsts:
        return {}

    logger.info(
        "imdb_datasets: downloading principals for %d titles from %s",
        len(tconsts),
        PRINCIPALS_URL,
    )
    result: dict[str, list[dict]] = {}

    with (
        urllib.request.urlopen(PRINCIPALS_URL, timeout=_DOWNLOAD_TIMEOUT) as resp,  # noqa: S310
        gzip.open(resp, "rt", encoding="utf-8") as f,
    ):
        reader = csv.DictReader(f, delimiter="\t")
        for row in reader:
            tconst = row.get("tconst", "").strip()
            if tconst not in tconsts:
                continue
            nconst = row.get("nconst", "").strip()
            if not nconst:
                continue
            ordering_raw = (row.get("ordering") or "").strip()
            try:
                ordering = int(ordering_raw) if ordering_raw else None
            except (ValueError, TypeError):
                ordering = None
            result.setdefault(tconst, []).append(
                {
                    "nconst": nconst,
                    "category": (row.get("category") or "").strip(),
                    "job": _clean_optional(row.get("job")),
                    "characters": _clean_optional(row.get("characters")),
                    "ordering": ordering,
                },
            )

    logger.info("imdb_datasets: principals loaded for %d titles", len(result))
    return result


def download_names(nconsts: set[str]) -> dict[str, str]:
    """Download and parse name.basics.tsv.gz, filtered to nconsts.

    Returns {nconst: primaryName}.
    """
    if not nconsts:
        return {}

    logger.info(
        "imdb_datasets: downloading names for %d people from %s",
        len(nconsts),
        NAME_BASICS_URL,
    )
    names: dict[str, str] = {}

    with (
        urllib.request.urlopen(NAME_BASICS_URL, timeout=_DOWNLOAD_TIMEOUT) as resp,  # noqa: S310
        gzip.open(resp, "rt", encoding="utf-8") as f,
    ):
        reader = csv.DictReader(f, delimiter="\t")
        for row in reader:
            nconst = row.get("nconst", "").strip()
            if nconst not in nconsts:
                continue
            name = (row.get("primaryName") or "").strip()
            if name:
                names[nconst] = name

    logger.info("imdb_datasets: loaded %d names", len(names))
    return names


def download_ratings(tconsts: set[str]) -> dict[str, tuple[float, int]]:
    """Download and parse title.ratings.tsv.gz, filtered to tconsts.

    Returns {tconst: (averageRating, numVotes)}.
    """
    if not tconsts:
        return {}

    logger.info(
        "imdb_datasets: downloading ratings for %d titles from %s",
        len(tconsts),
        TITLE_RATINGS_URL,
    )
    ratings: dict[str, tuple[float, int]] = {}

    with (
        urllib.request.urlopen(TITLE_RATINGS_URL, timeout=_DOWNLOAD_TIMEOUT) as resp,  # noqa: S310
        gzip.open(resp, "rt", encoding="utf-8") as f,
    ):
        reader = csv.DictReader(f, delimiter="\t")
        for row in reader:
            tconst = row.get("tconst", "").strip()
            if tconst not in tconsts:
                continue
            rating_raw = (row.get("averageRating") or "").strip()
            votes_raw = (row.get("numVotes") or "").strip()
            if not rating_raw or not votes_raw:
                continue
            try:
                ratings[tconst] = (float(rating_raw), int(votes_raw))
            except (ValueError, TypeError):
                continue

    logger.info("imdb_datasets: loaded %d ratings", len(ratings))
    return ratings


def download_episode_map(
    parent_tconsts: set[str],
) -> dict[str, dict[tuple[int, int], str]]:
    """Download and parse title.episode.tsv.gz, filtered to parent_tconsts.

    Returns {parentTconst: {(seasonNumber, episodeNumber): tconst}}.
    """
    if not parent_tconsts:
        return {}

    logger.info(
        "imdb_datasets: downloading episode map for %d shows from %s",
        len(parent_tconsts),
        TITLE_EPISODE_URL,
    )
    result: dict[str, dict[tuple[int, int], str]] = {}

    with (
        urllib.request.urlopen(TITLE_EPISODE_URL, timeout=_DOWNLOAD_TIMEOUT) as resp,  # noqa: S310
        gzip.open(resp, "rt", encoding="utf-8") as f,
    ):
        reader = csv.DictReader(f, delimiter="\t")
        for row in reader:
            parent_tconst = row.get("parentTconst", "").strip()
            if parent_tconst not in parent_tconsts:
                continue
            tconst = row.get("tconst", "").strip()
            season_raw = (row.get("seasonNumber") or "").strip()
            episode_raw = (row.get("episodeNumber") or "").strip()
            if not tconst or not season_raw or not episode_raw:
                continue
            try:
                season_number = int(season_raw)
                episode_number = int(episode_raw)
            except (ValueError, TypeError):
                continue
            result.setdefault(parent_tconst, {})[(season_number, episode_number)] = (
                tconst
            )

    logger.info("imdb_datasets: episode map loaded for %d shows", len(result))
    return result


def _clean_optional(value: str | None) -> str:
    r"""IMDB datasets use the literal string "\\N" for nulls; normalize to ""."""
    value = (value or "").strip()
    return "" if value == "\\N" else value
