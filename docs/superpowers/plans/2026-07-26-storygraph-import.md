# StoryGraph CSV Import Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Import a StoryGraph account export CSV into Yamtrack as book tracking entries, one entry per read, resolved against Hardcover with an Open Library fallback.

**Architecture:** A single importer module, `src/integrations/imports/storygraph.py`, following the `goodreads.py` / `hardcover.py` shape: module-level pure parsers, a `StoryGraphImporter` class that resolves each row to a book, builds unsaved model instances, and hands them to `helpers.bulk_create_media`. Re-reads become separate `Book` rows because that is how Yamtrack models multiple reads — `history_cache_day_builder.py:176` builds the history calendar from live `Book.start_date`/`end_date`, never from `HistoricalBook`. The rest of the work is the standard import wiring: celery task, view, url, template card, source display, task-name map, API map.

**Tech Stack:** Python 3, Django, django-simple-history (`bulk_create_with_history`), Celery, `pytest` via `pytest-django` (settings module `config.test_settings`).

Design spec: `docs/superpowers/specs/2026-07-26-storygraph-import-design.md`.

## Global Constraints

- Run tests from the repo root: `pytest src/integrations/tests/imports/test_storygraph.py -v`. `pytest.ini` sets `DJANGO_SETTINGS_MODULE = config.test_settings`.
- Never call a real provider API in a test. Patch `integrations.imports.storygraph.services.search` and `integrations.imports.storygraph.services.get_media_metadata`, as `src/integrations/tests/imports/test_hardcover.py` does.
- Follow the repo's docstring style: every module, class, and public function has a one-line docstring. Ruff enforces it.
- Media source values come from `app.models.Sources`; statuses from `app.models.Status`; media types from `app.models.MediaTypes`. Never hardcode their string values.
- `Item` rows are shared by all users. Never overwrite a non-empty `Item.format`.
- Commit after each task with the message given in the task's final step.

## File Structure

| File | Responsibility |
| --- | --- |
| `src/integrations/imports/storygraph.py` (create) | Parsers, provider matching, importer class, `importer(file, user, mode)` entry point |
| `src/integrations/tests/mock_data/import_storygraph.csv` (create) | Fixture export covering every row shape |
| `src/integrations/tests/imports/test_storygraph.py` (create) | Importer tests |
| `src/integrations/tasks/_media_imports.py` (modify) | Celery task `Import from StoryGraph` |
| `src/integrations/tasks/__init__.py` (modify) | Re-export the task |
| `src/integrations/views.py` (modify) | `import_storygraph` upload view |
| `src/integrations/urls.py` (modify) | Route `import/storygraph` |
| `src/users/templatetags/user_tags.py` (modify) | Source display entry |
| `src/static/img/storygraph-logo.svg` (create) | Logo for the source display |
| `src/templates/users/import_data.html` (modify) | Upload card |
| `src/users/models.py` (modify) | Task-name map for import history |
| `src/api/fork_views_integrations.py` (modify) | `POST /api/v1/imports/storygraph/` |

---

### Task 1: CSV field parsers

Pure functions, no database, no network. Everything later tasks build on.

**Files:**
- Create: `src/integrations/imports/storygraph.py`
- Create: `src/integrations/tests/imports/test_storygraph.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `Read` — `namedtuple("Read", ("start", "end"))`, both `datetime | None`
  - `parse_reads(dates_read: str) -> list[Read]` — oldest first
  - `determine_status(raw_status: str) -> str` — a `Status` value
  - `parse_rating(raw_rating: str) -> float | None` — 0–10 scale
  - `parse_tags(raw_tags: str) -> list[str]`
  - `parse_authors(raw_authors: str) -> list[str]`
  - `normalize_isbn(raw_isbn: str) -> str` — `""` when not an ISBN-10/13
  - `map_format(raw_format: str) -> str`

- [ ] **Step 1: Write the failing tests**

Create `src/integrations/tests/imports/test_storygraph.py`:

```python
from datetime import datetime

from django.test import SimpleTestCase
from django.utils import timezone

from app.models import Status
from integrations.imports import storygraph


class ParseReads(SimpleTestCase):
    """Tests for parsing StoryGraph's Dates Read column."""

    def test_range_gives_start_and_end(self):
        """A dash-separated range is a start date and an end date."""
        reads = storygraph.parse_reads("2022/03/16-2022/04/01")
        self.assertEqual(len(reads), 1)
        self.assertEqual(reads[0].start.date(), datetime(2022, 3, 16).date())
        self.assertEqual(reads[0].end.date(), datetime(2022, 4, 1).date())

    def test_single_date_is_end_only(self):
        """StoryGraph writes one date when only the finish date is known."""
        reads = storygraph.parse_reads("2021/07/21")
        self.assertEqual(len(reads), 1)
        self.assertIsNone(reads[0].start)
        self.assertEqual(reads[0].end.date(), datetime(2021, 7, 21).date())

    def test_multiple_reads_sorted_oldest_first(self):
        """Re-reads are comma separated and come back oldest first."""
        reads = storygraph.parse_reads("2022/10/29-2022/11/28, 2021/09/14")
        self.assertEqual(len(reads), 2)
        self.assertEqual(reads[0].end.date(), datetime(2021, 9, 14).date())
        self.assertEqual(reads[1].end.date(), datetime(2022, 11, 28).date())

    def test_blank_and_garbage_ignored(self):
        """Empty or unparseable values produce no reads."""
        self.assertEqual(storygraph.parse_reads(""), [])
        self.assertEqual(storygraph.parse_reads(None), [])
        self.assertEqual(storygraph.parse_reads("not a date"), [])

    def test_dates_are_timezone_aware(self):
        """Parsed dates are aware so Django never warns on save."""
        read = storygraph.parse_reads("2021/07/21")[0]
        self.assertIsNotNone(timezone.is_aware(read.end) or None)
        self.assertTrue(timezone.is_aware(read.end))


class ParseFields(SimpleTestCase):
    """Tests for the remaining column parsers."""

    def test_status_mapping(self):
        """Each StoryGraph read status maps to a Yamtrack status."""
        self.assertEqual(storygraph.determine_status("read"), Status.COMPLETED.value)
        self.assertEqual(
            storygraph.determine_status("currently-reading"),
            Status.IN_PROGRESS.value,
        )
        self.assertEqual(storygraph.determine_status("to-read"), Status.PLANNING.value)
        self.assertEqual(
            storygraph.determine_status("did-not-finish"),
            Status.DROPPED.value,
        )

    def test_blank_status_defaults_to_planning(self):
        """Rows with no read status are library entries, so plan them."""
        self.assertEqual(storygraph.determine_status(""), Status.PLANNING.value)
        self.assertEqual(storygraph.determine_status(None), Status.PLANNING.value)
        self.assertEqual(storygraph.determine_status("nonsense"), Status.PLANNING.value)

    def test_rating_doubled_to_ten_point_scale(self):
        """StoryGraph rates 0-5 with halves; Yamtrack scores 0-10."""
        self.assertEqual(storygraph.parse_rating("4.5"), 9.0)
        self.assertEqual(storygraph.parse_rating("5.0"), 10.0)
        self.assertIsNone(storygraph.parse_rating(""))
        self.assertIsNone(storygraph.parse_rating("0"))
        self.assertIsNone(storygraph.parse_rating("nonsense"))

    def test_tags_split_and_deduplicated(self):
        """Tags are comma separated free text."""
        self.assertEqual(
            storygraph.parse_tags("management, spanish , management"),
            ["management", "spanish"],
        )
        self.assertEqual(storygraph.parse_tags(""), [])

    def test_authors_split(self):
        """Multiple authors are comma separated in one column."""
        self.assertEqual(
            storygraph.parse_authors("Brandon Sanderson, Robert Jordan"),
            ["Brandon Sanderson", "Robert Jordan"],
        )
        self.assertEqual(storygraph.parse_authors(""), [])

    def test_isbn_normalization(self):
        """Only ISBN-10 and ISBN-13 values survive; ASINs do not."""
        self.assertEqual(storygraph.normalize_isbn("978-0-575-07979-3"), "9780575079793")
        self.assertEqual(storygraph.normalize_isbn("080442957X"), "080442957X")
        self.assertEqual(storygraph.normalize_isbn("B0851JCZYV"), "")
        self.assertEqual(storygraph.normalize_isbn(""), "")

    def test_format_mapping(self):
        """StoryGraph formats map onto the values Yamtrack already uses."""
        self.assertEqual(storygraph.map_format("digital"), "ebook")
        self.assertEqual(storygraph.map_format("audio"), "audiobook")
        self.assertEqual(storygraph.map_format("paperback"), "paperback")
        self.assertEqual(storygraph.map_format("hardcover"), "hardcover")
        self.assertEqual(storygraph.map_format(""), "")
        self.assertEqual(storygraph.map_format("something else"), "")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest src/integrations/tests/imports/test_storygraph.py -v`
Expected: collection error — `No module named 'integrations.imports.storygraph'`.

- [ ] **Step 3: Write the parsers**

Create `src/integrations/imports/storygraph.py`:

```python
"""Importer for The StoryGraph's account export CSV.

StoryGraph has no public API, so the export CSV is the supported path. Each
read in the ``Dates Read`` column becomes its own ``Book`` row, which is how
Yamtrack models re-reads: the history calendar is built from live rows rather
than from simple-history records.
"""

import logging
import re
from collections import namedtuple
from datetime import datetime

from django.utils import timezone

from app.models import Status

logger = logging.getLogger(__name__)

STATUS_MAP = {
    "read": Status.COMPLETED.value,
    "currently-reading": Status.IN_PROGRESS.value,
    "to-read": Status.PLANNING.value,
    "did-not-finish": Status.DROPPED.value,
}
FORMAT_MAP = {
    "digital": "ebook",
    "audio": "audiobook",
    "paperback": "paperback",
    "hardcover": "hardcover",
}
ISBN_13_LENGTH = 13
ISBN_10_LENGTH = 10
MAX_STAR_RATING = 5

Read = namedtuple("Read", ("start", "end"))


def parse_date(value):
    """Parse a StoryGraph ``YYYY/MM/DD`` date into an aware datetime."""
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.strptime(text, "%Y/%m/%d")  # noqa: DTZ007 - tz applied below
    except ValueError:
        return None
    return parsed.replace(tzinfo=timezone.get_current_timezone())


def parse_reads(dates_read):
    """Parse ``Dates Read`` into ordered reads, oldest first.

    A dash separated chunk is a start and an end date. A bare date is a finish
    date with no known start, so ``start`` stays ``None``.
    """
    reads = []
    for chunk in str(dates_read or "").split(","):
        pieces = [piece.strip() for piece in chunk.split("-") if piece.strip()]
        dates = [date for date in map(parse_date, pieces) if date]
        if not dates:
            continue
        if len(dates) == 1:
            reads.append(Read(start=None, end=dates[0]))
        else:
            reads.append(Read(start=dates[0], end=dates[-1]))

    reads.sort(key=lambda read: read.end or read.start)
    return reads


def determine_status(raw_status):
    """Map a StoryGraph read status onto a Yamtrack status."""
    return STATUS_MAP.get(
        str(raw_status or "").strip().lower(),
        Status.PLANNING.value,
    )


def parse_rating(raw_rating):
    """Convert a 0-5 star rating with halves into a 0-10 score."""
    text = str(raw_rating or "").strip()
    if not text:
        return None
    try:
        rating = float(text)
    except ValueError:
        return None
    if rating <= 0:
        return None
    return round(min(rating, MAX_STAR_RATING) * 2, 1)


def parse_tags(raw_tags):
    """Split the comma separated ``Tags`` column, preserving order."""
    tags = [tag.strip() for tag in str(raw_tags or "").split(",") if tag.strip()]
    return list(dict.fromkeys(tags))


def parse_authors(raw_authors):
    """Split the comma separated ``Authors`` column."""
    return [name.strip() for name in str(raw_authors or "").split(",") if name.strip()]


def normalize_isbn(raw_isbn):
    """Return the value as an ISBN, or ``""`` when it is an ASIN or junk."""
    candidate = str(raw_isbn or "").strip().replace("-", "").replace(" ", "").upper()
    if len(candidate) == ISBN_13_LENGTH and candidate.isdigit():
        return candidate
    if len(candidate) == ISBN_10_LENGTH and candidate[:9].isdigit():
        return candidate
    return ""


def map_format(raw_format):
    """Map a StoryGraph format onto the format values Yamtrack stores."""
    return FORMAT_MAP.get(str(raw_format or "").strip().lower(), "")


def normalize_name(value):
    """Lowercase a title or name down to alphanumerics for comparison."""
    normalized = re.sub(r"[^a-z0-9]+", " ", str(value or "").lower())
    return re.sub(r"\s+", " ", normalized).strip()
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest src/integrations/tests/imports/test_storygraph.py -v`
Expected: PASS, 13 tests.

- [ ] **Step 5: Commit**

```bash
git add src/integrations/imports/storygraph.py src/integrations/tests/imports/test_storygraph.py
git commit -m "Add StoryGraph CSV field parsers"
```

---

### Task 2: Provider matching

Resolve a CSV row to a book on Hardcover, falling back to Open Library, verifying title and author so an ASIN row does not silently match the wrong book.

**Files:**
- Modify: `src/integrations/imports/storygraph.py`
- Modify: `src/integrations/tests/imports/test_storygraph.py`

**Interfaces:**
- Consumes: `normalize_name`, `normalize_isbn`, `parse_authors` from Task 1.
- Produces:
  - `titles_match(left: str, right: str) -> bool`
  - `classify_authors(target: list[str], candidate: list[str]) -> str` — `"match"`, `"unknown"`, or `"conflict"`
  - `extract_provider_authors(metadata: dict) -> list[str]`
  - `BookResolver(cache: dict)` with `resolve(title: str, authors: list[str], isbn: str) -> tuple[str, str, dict] | None` returning `(source, media_id, metadata)`

- [ ] **Step 1: Write the failing tests**

Append to `src/integrations/tests/imports/test_storygraph.py`:

```python
from unittest.mock import patch

from app.models import Sources


class MatchingHelpers(SimpleTestCase):
    """Tests for the title and author comparison helpers."""

    def test_titles_match_tolerates_subtitles(self):
        """A provider title with a subtitle still matches the CSV title."""
        self.assertTrue(storygraph.titles_match("Mistborn", "Mistborn: The Final Empire"))
        self.assertTrue(storygraph.titles_match("The Blade Itself", "the blade itself"))

    def test_titles_do_not_match_across_books(self):
        """Unrelated titles do not match."""
        self.assertFalse(storygraph.titles_match("Mistborn", "The God Delusion"))
        self.assertFalse(storygraph.titles_match("", "Mistborn"))

    def test_author_classification(self):
        """Authors classify as match, unknown, or conflict."""
        self.assertEqual(
            storygraph.classify_authors(["Joe Abercrombie"], ["Joe Abercrombie"]),
            "match",
        )
        self.assertEqual(
            storygraph.classify_authors(["Joe Abercrombie"], ["J. Abercrombie"]),
            "match",
        )
        self.assertEqual(storygraph.classify_authors(["Joe Abercrombie"], []), "unknown")
        self.assertEqual(
            storygraph.classify_authors(["Joe Abercrombie"], ["Robin Hobb"]),
            "conflict",
        )
        self.assertEqual(storygraph.classify_authors([], ["Robin Hobb"]), "match")

    def test_extract_provider_authors_handles_shapes(self):
        """Provider metadata carries authors as strings, lists, or dicts."""
        self.assertEqual(
            storygraph.extract_provider_authors(
                {"details": {"author": ["Robin Hobb"]}},
            ),
            ["Robin Hobb"],
        )
        self.assertEqual(
            storygraph.extract_provider_authors(
                {"details": {"authors": [{"name": "Robin Hobb"}]}},
            ),
            ["Robin Hobb"],
        )
        self.assertEqual(
            storygraph.extract_provider_authors({"details": {"author": "Robin Hobb"}}),
            ["Robin Hobb"],
        )
        self.assertEqual(storygraph.extract_provider_authors({}), [])


class BookResolverTests(SimpleTestCase):
    """Tests for resolving CSV rows against metadata providers."""

    def setUp(self):
        """Build the provider fixtures shared by these tests."""
        self.metadata = {
            "1": {
                "media_id": "1",
                "title": "The Blade Itself",
                "image": "https://example.com/blade.jpg",
                "max_progress": 515,
                "details": {"author": ["Joe Abercrombie"]},
            },
            "2": {
                "media_id": "2",
                "title": "A Completely Different Book",
                "image": "https://example.com/other.jpg",
                "max_progress": 100,
                "details": {"author": ["Someone Else"]},
            },
        }

    def _search(self, results_by_query):
        def search(media_type, query, page, source):
            return {"results": results_by_query.get((source, query), [])}

        return search

    def _metadata(self, media_type, media_id, source):
        return self.metadata[str(media_id)]

    def test_isbn_hit_on_hardcover_wins(self):
        """An ISBN search on Hardcover short circuits the ladder."""
        search = self._search(
            {(Sources.HARDCOVER.value, "9780575079793"): [{"media_id": "1", "title": "The Blade Itself"}]},
        )
        with patch("integrations.imports.storygraph.services.search", side_effect=search), patch(
            "integrations.imports.storygraph.services.get_media_metadata",
            side_effect=self._metadata,
        ):
            resolved = storygraph.BookResolver({}).resolve(
                "The Blade Itself",
                ["Joe Abercrombie"],
                "9780575079793",
            )

        self.assertIsNotNone(resolved)
        source, media_id, metadata = resolved
        self.assertEqual(source, Sources.HARDCOVER.value)
        self.assertEqual(media_id, "1")
        self.assertEqual(metadata["max_progress"], 515)

    def test_falls_back_to_openlibrary(self):
        """A book Hardcover cannot find is looked up on Open Library."""
        search = self._search(
            {(Sources.OPENLIBRARY.value, "The Blade Itself Joe Abercrombie"): [
                {"media_id": "1", "title": "The Blade Itself"},
            ]},
        )
        with patch("integrations.imports.storygraph.services.search", side_effect=search), patch(
            "integrations.imports.storygraph.services.get_media_metadata",
            side_effect=self._metadata,
        ):
            resolved = storygraph.BookResolver({}).resolve(
                "The Blade Itself",
                ["Joe Abercrombie"],
                "",
            )

        self.assertIsNotNone(resolved)
        self.assertEqual(resolved[0], Sources.OPENLIBRARY.value)

    def test_wrong_title_is_rejected(self):
        """A search result for a different book is not accepted."""
        search = self._search(
            {(Sources.HARDCOVER.value, "The Blade Itself Joe Abercrombie"): [
                {"media_id": "2", "title": "A Completely Different Book"},
            ]},
        )
        with patch("integrations.imports.storygraph.services.search", side_effect=search), patch(
            "integrations.imports.storygraph.services.get_media_metadata",
            side_effect=self._metadata,
        ):
            resolved = storygraph.BookResolver({}).resolve(
                "The Blade Itself",
                ["Joe Abercrombie"],
                "",
            )

        self.assertIsNone(resolved)

    def test_provider_error_does_not_propagate(self):
        """A provider blowing up leaves the book unresolved, not the import."""
        with patch(
            "integrations.imports.storygraph.services.search",
            side_effect=Exception("provider down"),
        ):
            resolved = storygraph.BookResolver({}).resolve("Whatever", [], "")

        self.assertIsNone(resolved)

    def test_resolution_is_cached(self):
        """Resolving the same book twice hits the provider once."""
        calls = []

        def search(media_type, query, page, source):
            calls.append(query)
            if (source, query) == (Sources.HARDCOVER.value, "9780575079793"):
                return {"results": [{"media_id": "1", "title": "The Blade Itself"}]}
            return {"results": []}

        cache = {}
        with patch("integrations.imports.storygraph.services.search", side_effect=search), patch(
            "integrations.imports.storygraph.services.get_media_metadata",
            side_effect=self._metadata,
        ):
            resolver = storygraph.BookResolver(cache)
            first = resolver.resolve("The Blade Itself", ["Joe Abercrombie"], "9780575079793")
            second = resolver.resolve("The Blade Itself", ["Joe Abercrombie"], "9780575079793")

        self.assertEqual(first, second)
        self.assertEqual(calls.count("9780575079793"), 1)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest src/integrations/tests/imports/test_storygraph.py -v -k "MatchingHelpers or BookResolver"`
Expected: FAIL — `module 'integrations.imports.storygraph' has no attribute 'titles_match'`.

- [ ] **Step 3: Write the resolver**

Add to the imports at the top of `src/integrations/imports/storygraph.py`:

```python
from difflib import SequenceMatcher

from app.log_safety import exception_summary
from app.models import MediaTypes, Sources, Status
from app.providers import services
```

(The existing `from app.models import Status` line is replaced by the combined import above.)

Add the constants next to the others:

```python
BOOK_METADATA_PROVIDER_ORDER = (Sources.HARDCOVER.value, Sources.OPENLIBRARY.value)
TITLE_MATCH_THRESHOLD = 0.72
MAX_SEARCH_RESULTS = 5
MAX_TITLE_CANDIDATES = 3
BEST_TIER = 3
```

Then append:

```python
def title_similarity(left, right):
    """Return a 0-1 similarity ratio between two normalized titles."""
    left_normalized = normalize_name(left)
    right_normalized = normalize_name(right)
    if not left_normalized or not right_normalized:
        return 0.0
    return SequenceMatcher(None, left_normalized, right_normalized).ratio()


def titles_match(left, right):
    """Match titles, tolerating subtitles ('Mistborn' vs 'Mistborn: ...')."""
    left_normalized = normalize_name(left)
    right_normalized = normalize_name(right)
    if not left_normalized or not right_normalized:
        return False
    if left_normalized == right_normalized:
        return True
    if right_normalized.startswith(left_normalized) or left_normalized.startswith(
        right_normalized,
    ):
        return True
    return title_similarity(left, right) >= TITLE_MATCH_THRESHOLD


def authors_overlap(target_authors, provider_authors):
    """Return True when two author name sets plausibly mean the same person."""
    target = {name for name in map(normalize_name, target_authors) if name}
    provider = {name for name in map(normalize_name, provider_authors) if name}
    if not target or not provider:
        return False
    if target & provider:
        return True
    for left in target:
        for right in provider:
            if left in right or right in left:
                return True
            if left.split()[-1] == right.split()[-1]:  # shared surname
                return True
    return False


def classify_authors(target_authors, candidate_authors):
    """Classify author agreement as 'match', 'unknown', or 'conflict'."""
    if not target_authors:
        return "match"
    if not candidate_authors:
        return "unknown"
    if authors_overlap(target_authors, candidate_authors):
        return "match"
    return "conflict"


def extract_provider_authors(metadata):
    """Pull author names out of provider metadata, whatever shape they take."""
    details = metadata.get("details", {}) if isinstance(metadata, dict) else {}
    if not isinstance(details, dict):
        details = {}

    raw_authors = details.get("authors") or details.get("author") or []
    if isinstance(raw_authors, str):
        raw_authors = [part.strip() for part in raw_authors.split(",") if part.strip()]
    elif not isinstance(raw_authors, list):
        raw_authors = [raw_authors] if raw_authors else []

    authors = []
    for raw_author in raw_authors:
        value = (
            raw_author.get("name") or raw_author.get("person")
            if isinstance(raw_author, dict)
            else raw_author
        )
        name = str(value or "").strip()
        if name:
            authors.append(name)
    return list(dict.fromkeys(authors))


class BookResolver:
    """Resolve StoryGraph rows to books on Hardcover, then Open Library."""

    def __init__(self, cache):
        """Initialize with a dict used to memoize resolutions across rows."""
        self.cache = cache

    def resolve(self, title, authors, isbn):
        """Return ``(source, media_id, metadata)`` for a book, or None."""
        cache_key = isbn or f"{normalize_name(title)}|{normalize_name(' '.join(authors))}"
        if cache_key in self.cache:
            return self.cache[cache_key]

        resolved = self._search_providers(title, authors, isbn)
        self.cache[cache_key] = resolved
        return resolved

    def _queries(self, title, authors, isbn):
        """Build the ordered search queries for one book."""
        queries = [isbn] if isbn else []
        if title and authors:
            queries.append(f"{title} {authors[0]}")
        if title:
            queries.append(title)
        return list(dict.fromkeys(query for query in queries if query))

    def _search_providers(self, title, authors, isbn):
        """Walk the provider and query ladder, keeping the best candidate."""
        best_tier = 0
        best_result = None

        for source in BOOK_METADATA_PROVIDER_ORDER:
            for query in self._queries(title, authors, isbn):
                tier, result = self._match_query(source, query, title, authors)
                if tier > best_tier:
                    best_tier, best_result = tier, result
                    if best_tier == BEST_TIER:
                        return best_result

        return best_result

    def _match_query(self, source, query, title, authors):
        """Search one provider with one query, returning ``(tier, result)``."""
        try:
            response = services.search(MediaTypes.BOOK.value, query, 1, source)
        except Exception as error:  # noqa: BLE001 - a bad provider must not stop the import
            logger.debug(
                "StoryGraph search failed source=%s error=%s",
                source,
                exception_summary(error),
            )
            return 0, None

        results = response.get("results", []) if isinstance(response, dict) else []
        best_tier = 0
        best_result = None

        for candidate in self._title_candidates(results, title):
            media_id = candidate.get("media_id")
            if not media_id:
                continue

            try:
                metadata = services.get_media_metadata(
                    MediaTypes.BOOK.value,
                    str(media_id),
                    source,
                )
            except Exception as error:  # noqa: BLE001 - same reasoning as above
                logger.debug(
                    "StoryGraph metadata fetch failed source=%s error=%s",
                    source,
                    exception_summary(error),
                )
                continue

            if not titles_match(title, str(metadata.get("title") or "")):
                continue

            verdict = classify_authors(authors, extract_provider_authors(metadata))
            if verdict == "conflict":
                continue

            tier = BEST_TIER if verdict == "match" else 2
            if tier > best_tier:
                best_tier = tier
                best_result = (source, str(media_id), metadata)
                if best_tier == BEST_TIER:
                    break

        return best_tier, best_result

    def _title_candidates(self, results, title):
        """Return the best title-matching search results, best first."""
        scored = []
        for result in results[:MAX_SEARCH_RESULTS]:
            candidate_title = str(result.get("title") or "")
            if not titles_match(title, candidate_title):
                continue
            scored.append((title_similarity(title, candidate_title), result))
        scored.sort(key=lambda pair: pair[0], reverse=True)
        return [result for _score, result in scored[:MAX_TITLE_CANDIDATES]]
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest src/integrations/tests/imports/test_storygraph.py -v`
Expected: PASS, all Task 1 and Task 2 tests.

- [ ] **Step 5: Commit**

```bash
git add src/integrations/imports/storygraph.py src/integrations/tests/imports/test_storygraph.py
git commit -m "Add StoryGraph provider matching with Open Library fallback"
```

---

### Task 3: Importer — entries, items, formats

The importer itself: read the CSV, resolve each row, build one `Book` row per read, create items, and bulk create. Deduplication, tags, and the date report arrive in Tasks 4–6.

**Files:**
- Modify: `src/integrations/imports/storygraph.py`
- Create: `src/integrations/tests/mock_data/import_storygraph.csv`
- Modify: `src/integrations/tests/imports/test_storygraph.py`

**Interfaces:**
- Consumes: everything from Tasks 1 and 2.
- Produces:
  - `importer(file, user, mode) -> tuple[dict[str, int], str]`
  - `StoryGraphImporter(file, user, mode)` with `import_data()`

- [ ] **Step 1: Write the fixture CSV**

Create `src/integrations/tests/mock_data/import_storygraph.csv` (header identical to a real export):

```csv
Title,Authors,Contributors,ISBN/UID,Format,Read Status,Date Added,Last Date Read,Dates Read,Read Count,Moods,Pace,Character- or Plot-Driven?,Strong Character Development?,Loveable Characters?,Diverse Characters?,Flawed Characters?,Star Rating,Review,Content Warnings,Content Warning Description,Tags,Owned?
The Blade Itself,Joe Abercrombie,"",9780575079793,digital,read,2021/01/01,2021/02/09,2021/01/20-2021/02/09,1,"",,,,,,,4.5,Grim and funny.,"",,"fantasy",No
Kindle Only,Some Author,"",B0851JCZYV,digital,read,2025/07/01,2025/07/16,2025/07/16,1,"",,,,,,,,,"",,"",No
No Isbn Book,Another Author,"","",paperback,read,2013/06/04,"","",1,"",,,,,,,5.0,,"",,"",No
Re-read Book,Third Author,"",9781111111111,digital,read,2021/09/01,2022/11/28,"2022/10/29-2022/11/28, 2021/09/14",2,"",,,,,,,5.0,,"",,"",No
Current Book,Fourth Author,"",9782222222222,digital,currently-reading,2026/07/15,"","",0,"",,,,,,,,,"",,"",No
Planned Book,Fifth Author,"",9783333333333,hardcover,to-read,2026/02/04,"","",0,"",,,,,,,,,"",,"",No
Dnf Book,Sixth Author,"",9784444444444,digital,did-not-finish,2024/05/05,"","",0,"",,,,,,,,,"",,"",No
Tagged Only Book,Seventh Author,"","",,,"","","",,"",,,,,,,,,"",,"management, spanish",No
Audio Book,Eighth Author,"",9785555555555,audio,read,2024/01/01,2024/01/05,2024/01/02-2024/01/05,1,"",,,,,,,,,"",,"",No
Missing Book,Unknown Author,"","",digital,read,2020/01/01,2020/01/05,2020/01/05,1,"",,,,,,,,,"",,"",No
```

- [ ] **Step 2: Write the failing tests**

Append to `src/integrations/tests/imports/test_storygraph.py`:

```python
from pathlib import Path

from django.contrib.auth import get_user_model
from django.test import TestCase

from app.models import Book, Item

mock_path = Path(__file__).resolve().parent.parent / "mock_data"

PROVIDER_BOOKS = {
    "The Blade Itself": {"media_id": "1", "pages": 515, "author": "Joe Abercrombie"},
    "Kindle Only": {"media_id": "2", "pages": 300, "author": "Some Author"},
    "No Isbn Book": {"media_id": "3", "pages": 200, "author": "Another Author"},
    "Re-read Book": {"media_id": "4", "pages": 400, "author": "Third Author"},
    "Current Book": {"media_id": "5", "pages": 350, "author": "Fourth Author"},
    "Planned Book": {"media_id": "6", "pages": 1007, "author": "Fifth Author"},
    "Dnf Book": {"media_id": "7", "pages": 250, "author": "Sixth Author"},
    "Tagged Only Book": {"media_id": "8", "pages": 150, "author": "Seventh Author"},
    "Audio Book": {"media_id": "9", "pages": 320, "author": "Eighth Author"},
}
PROVIDER_BY_ID = {book["media_id"]: (title, book) for title, book in PROVIDER_BOOKS.items()}


def fake_search(media_type, query, page, source):
    """Return a hit when the query names or identifies a fixture book."""
    if source != Sources.HARDCOVER.value:
        return {"results": []}
    for title, book in PROVIDER_BOOKS.items():
        if title.lower() in query.lower():
            return {"results": [{"media_id": book["media_id"], "title": title}]}
    return {"results": []}


def fake_metadata(media_type, media_id, source):
    """Return provider metadata for a fixture book."""
    title, book = PROVIDER_BY_ID[str(media_id)]
    return {
        "media_id": book["media_id"],
        "title": title,
        "image": f"https://example.com/{book['media_id']}.jpg",
        "max_progress": book["pages"],
        "details": {"author": [book["author"]]},
    }


class ImportStoryGraph(TestCase):
    """Tests for importing a StoryGraph export."""

    def setUp(self):
        """Import the fixture export with the providers mocked out."""
        self.user = get_user_model().objects.create_user(
            username="test",
            password="12345",  # noqa: S106 - test credential
        )
        with patch(
            "integrations.imports.storygraph.services.search",
            side_effect=fake_search,
        ), patch(
            "integrations.imports.storygraph.services.get_media_metadata",
            side_effect=fake_metadata,
        ), Path(mock_path / "import_storygraph.csv").open("rb") as file:
            self.counts, self.messages = storygraph.importer(file, self.user, "new")

    def _books(self, title):
        return Book.objects.filter(user=self.user, item__title=title).order_by("end_date")

    def test_entry_count(self):
        """Nine resolvable rows produce ten entries, the re-read counting twice."""
        self.assertEqual(Book.objects.filter(user=self.user).count(), 10)
        self.assertEqual(self.counts["book"], 10)

    def test_completed_read_dates(self):
        """A dash separated read keeps its start and end date."""
        book = self._books("The Blade Itself").get()
        self.assertEqual(book.status, Status.COMPLETED.value)
        self.assertEqual(book.start_date.date(), datetime(2021, 1, 20).date())
        self.assertEqual(book.end_date.date(), datetime(2021, 2, 9).date())

    def test_finish_date_only_leaves_start_null(self):
        """A bare date is a finish date, not a one day read."""
        book = self._books("Kindle Only").get()
        self.assertIsNone(book.start_date)
        self.assertEqual(book.end_date.date(), datetime(2025, 7, 16).date())

    def test_reread_creates_two_entries(self):
        """Each read in Dates Read becomes its own entry."""
        books = list(self._books("Re-read Book"))
        self.assertEqual(len(books), 2)
        self.assertEqual(books[0].end_date.date(), datetime(2021, 9, 14).date())
        self.assertEqual(books[1].end_date.date(), datetime(2022, 11, 28).date())

    def test_rating_only_on_newest_read(self):
        """One StoryGraph rating must not be counted once per re-read."""
        books = list(self._books("Re-read Book"))
        self.assertIsNone(books[0].score)
        self.assertEqual(float(books[1].score), 10.0)

    def test_review_becomes_notes(self):
        """The Review column lands in notes."""
        book = self._books("The Blade Itself").get()
        self.assertEqual(book.notes, "Grim and funny.")
        self.assertEqual(float(book.score), 9.0)

    def test_progress_from_provider_page_count(self):
        """Completed books take their page count from provider metadata."""
        self.assertEqual(self._books("The Blade Itself").get().progress, 515)
        self.assertEqual(self._books("Planned Book").get().progress, 0)

    def test_audiobook_keeps_zero_progress(self):
        """Audiobook progress is minutes, so a page count would render wrong."""
        book = self._books("Audio Book").get()
        self.assertEqual(book.status, Status.COMPLETED.value)
        self.assertEqual(book.progress, 0)
        self.assertEqual(book.item.format, "audiobook")

    def test_status_mapping_across_rows(self):
        """Every read status maps through to the tracked entry."""
        self.assertEqual(self._books("Current Book").get().status, Status.IN_PROGRESS.value)
        self.assertEqual(self._books("Planned Book").get().status, Status.PLANNING.value)
        self.assertEqual(self._books("Dnf Book").get().status, Status.DROPPED.value)
        self.assertEqual(self._books("Tagged Only Book").get().status, Status.PLANNING.value)

    def test_date_added_is_never_a_start_date(self):
        """Date Added is when a book was shelved, not when reading began."""
        self.assertIsNone(self._books("Current Book").get().start_date)
        self.assertIsNone(self._books("Current Book").get().end_date)

    def test_read_without_dates_has_no_dates(self):
        """A read with no dates is completed but contributes no calendar day."""
        book = self._books("No Isbn Book").get()
        self.assertEqual(book.status, Status.COMPLETED.value)
        self.assertIsNone(book.start_date)
        self.assertIsNone(book.end_date)

    def test_format_written_only_when_empty(self):
        """Item.format is shared between users, so an existing value stands."""
        item = Item.objects.get(title="The Blade Itself")
        self.assertEqual(item.format, "ebook")

        item.format = "hardcover"
        item.save(update_fields=["format"])
        with patch(
            "integrations.imports.storygraph.services.search",
            side_effect=fake_search,
        ), patch(
            "integrations.imports.storygraph.services.get_media_metadata",
            side_effect=fake_metadata,
        ), Path(mock_path / "import_storygraph.csv").open("rb") as file:
            storygraph.importer(file, self.user, "new")

        item.refresh_from_db()
        self.assertEqual(item.format, "hardcover")

    def test_unresolvable_book_warns(self):
        """A book no provider knows is reported, not imported."""
        self.assertIn("Missing Book", self.messages)
        self.assertFalse(Book.objects.filter(item__title="Missing Book").exists())

    def test_history_record_dated_from_the_read(self):
        """The history record is stamped with the read's end date."""
        book = self._books("The Blade Itself").get()
        record = book.history.first()
        self.assertEqual(record.history_date.date(), datetime(2021, 2, 9).date())
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `pytest src/integrations/tests/imports/test_storygraph.py::ImportStoryGraph -v`
Expected: FAIL — `module 'integrations.imports.storygraph' has no attribute 'importer'`.

- [ ] **Step 4: Write the importer**

Add to the imports at the top of `src/integrations/imports/storygraph.py`:

```python
from collections import defaultdict, namedtuple
from csv import DictReader

from django.apps import apps
from django.conf import settings

import app
from integrations.imports import helpers
from integrations.imports.helpers import MediaImportError, MediaImportUnexpectedError
```

(The existing `from collections import namedtuple` line is replaced by the combined import above.)

Append to the module:

```python
def importer(file, user, mode):
    """Import books from a StoryGraph export CSV."""
    return StoryGraphImporter(file, user, mode).import_data()


class StoryGraphImporter:
    """Import a StoryGraph export, one tracked entry per read."""

    def __init__(self, file, user, mode):
        """Initialize the importer with the upload, user, and import mode."""
        self.file = file
        self.user = user
        self.mode = mode
        self.warnings = []

        self.existing_media = helpers.get_existing_media(user)
        self.to_delete = defaultdict(lambda: defaultdict(set))
        self.bulk_media = defaultdict(list)
        self.resolver = BookResolver({})

        logger.info(
            "Initialized StoryGraph CSV importer for user %s with mode %s",
            user.username,
            mode,
        )

    def import_data(self):
        """Import every row of the CSV and return counts plus messages."""
        try:
            raw_file = self.file.read()
            try:
                decoded_file = raw_file.decode("utf-8-sig").splitlines()
            except UnicodeDecodeError:
                decoded_file = raw_file.decode("latin-1").splitlines()
        except (UnicodeDecodeError, AttributeError) as error:
            msg = "Invalid file format. Please upload a CSV file."
            raise MediaImportError(msg) from error

        for row in DictReader(decoded_file):
            try:
                self._process_row(row)
            except services.ProviderAPIError as error:
                title = (row.get("Title") or "").strip() or str(row)
                self.warnings.append(f"Error processing entry: {title} - {error}")
                continue
            except Exception as error:
                error_msg = f"Error processing entry: {row}"
                raise MediaImportUnexpectedError(error_msg) from error

        helpers.cleanup_existing_media(self.to_delete, self.user)
        helpers.bulk_create_media(self.bulk_media, self.user)

        imported_counts = {
            media_type: len(media_list)
            for media_type, media_list in self.bulk_media.items()
        }
        return imported_counts, "\n".join(dict.fromkeys(self.warnings))

    def _process_row(self, row):
        """Resolve one CSV row and queue its tracked entries."""
        title = (row.get("Title") or "").strip()
        if not title:
            return

        resolved = self.resolver.resolve(
            title,
            parse_authors(row.get("Authors")),
            normalize_isbn(row.get("ISBN/UID")),
        )
        if not resolved:
            self.warnings.append(
                f"{title}: couldn't find this book on Hardcover or Open Library",
            )
            return

        source, media_id, metadata = resolved
        item = self._create_or_update_item(source, media_id, metadata, row)
        for instance in self._build_entries(item, row, metadata):
            self.bulk_media[MediaTypes.BOOK.value].append(instance)

    def _create_or_update_item(self, source, media_id, metadata, row):
        """Create or update the item, filling in an empty format only."""
        item, _ = app.models.Item.objects.update_or_create(
            media_id=media_id,
            source=source,
            media_type=MediaTypes.BOOK.value,
            defaults={
                **app.models.Item.title_fields_from_metadata(
                    metadata,
                    fallback_title=(row.get("Title") or "").strip(),
                ),
                "image": metadata.get("image") or settings.IMG_NONE,
            },
        )

        book_format = map_format(row.get("Format"))
        if book_format and not item.format:
            item.format = book_format
            item.save(update_fields=["format"])

        return item

    def _page_count(self, item, metadata, status):
        """Return the progress to store, in pages, for a tracked entry."""
        if status != Status.COMPLETED.value or item.format == "audiobook":
            return 0
        max_progress = metadata.get("max_progress")
        return int(max_progress) if max_progress else 0

    def _build_entries(self, item, row, metadata):
        """Build one unsaved Book per read, newest last."""
        status = determine_status(row.get("Read Status"))
        progress = self._page_count(item, metadata, status)
        reads = (
            parse_reads(row.get("Dates Read"))
            if status == Status.COMPLETED.value
            else []
        )
        fallback_date = parse_date(row.get("Date Added"))

        instances = [
            self._build_instance(item, status, read.start, read.end, progress, fallback_date)
            for read in reads
        ]
        if not instances:
            instances.append(
                self._build_instance(item, status, None, None, progress, fallback_date),
            )

        newest = instances[-1]
        newest.score = parse_rating(row.get("Star Rating"))
        newest.notes = (row.get("Review") or "").strip()
        return instances

    def _build_instance(self, item, status, start_date, end_date, progress, fallback_date):
        """Build a single unsaved Book instance for one read."""
        model = apps.get_model(app_label="app", model_name=MediaTypes.BOOK.value)
        instance = model(
            item=item,
            user=self.user,
            status=status,
            progress=progress,
            start_date=start_date,
            end_date=end_date,
        )
        instance._history_date = (  # noqa: SLF001 - simple_history reads this
            end_date or start_date or fallback_date or timezone.now()
        )
        return instance
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `pytest src/integrations/tests/imports/test_storygraph.py -v`
Expected: PASS, all tests including `ImportStoryGraph`.

- [ ] **Step 6: Commit**

```bash
git add src/integrations/imports/storygraph.py src/integrations/tests/imports/test_storygraph.py src/integrations/tests/mock_data/import_storygraph.csv
git commit -m "Add StoryGraph importer creating one entry per read"
```

---

### Task 4: Deduplication and import modes

Re-importing must not duplicate reads. Matching is on the read's end date.

**Files:**
- Modify: `src/integrations/imports/storygraph.py`
- Modify: `src/integrations/tests/imports/test_storygraph.py`

**Interfaces:**
- Consumes: `StoryGraphImporter` from Task 3.
- Produces: `StoryGraphImporter.tracked_reads` — `dict[tuple[str, str], set[date | None]]` keyed by `(source, media_id)`.

- [ ] **Step 1: Write the failing tests**

Append to `src/integrations/tests/imports/test_storygraph.py`:

```python
class ImportStoryGraphDeduplication(TestCase):
    """Tests that re-importing does not duplicate reads."""

    def setUp(self):
        """Create the user and import the fixture once."""
        self.user = get_user_model().objects.create_user(
            username="test",
            password="12345",  # noqa: S106 - test credential
        )
        self._import()

    def _import(self, mode="new", rows=None):
        """Import the fixture, or a custom CSV body, with providers mocked."""
        if rows is None:
            source_file = Path(mock_path / "import_storygraph.csv").open("rb")
        else:
            source_file = BytesIO(rows.encode("utf-8"))
        with patch(
            "integrations.imports.storygraph.services.search",
            side_effect=fake_search,
        ), patch(
            "integrations.imports.storygraph.services.get_media_metadata",
            side_effect=fake_metadata,
        ), source_file as file:
            return storygraph.importer(file, self.user, mode)

    def test_reimport_creates_nothing(self):
        """Importing the same export twice leaves the entry count unchanged."""
        before = Book.objects.filter(user=self.user).count()
        counts, _ = self._import()
        self.assertEqual(Book.objects.filter(user=self.user).count(), before)
        self.assertEqual(counts.get("book", 0), 0)

    def test_new_read_creates_one_entry(self):
        """A read added in StoryGraph after the first import arrives."""
        header = Path(mock_path / "import_storygraph.csv").read_text().splitlines()[0]
        row = (
            "The Blade Itself,Joe Abercrombie,\"\",9780575079793,digital,read,"
            "2021/01/01,2026/05/10,\"2021/01/20-2021/02/09, 2026/05/01-2026/05/10\",2,"
            "\"\",,,,,,,4.5,Grim and funny.,\"\",,\"fantasy\",No"
        )
        counts, _ = self._import(rows=f"{header}\n{row}\n")

        self.assertEqual(counts.get("book", 0), 1)
        books = Book.objects.filter(user=self.user, item__title="The Blade Itself")
        self.assertEqual(books.count(), 2)

    def test_dateless_read_not_duplicated(self):
        """A read with no dates is added once and never again."""
        counts, _ = self._import()
        self.assertEqual(counts.get("book", 0), 0)
        self.assertEqual(
            Book.objects.filter(user=self.user, item__title="No Isbn Book").count(),
            1,
        )

    def test_overwrite_rebuilds_entries(self):
        """Overwrite mode replaces the book's entries rather than adding to them."""
        self._import(mode="overwrite")
        self.assertEqual(Book.objects.filter(user=self.user).count(), 10)
        self.assertEqual(
            Book.objects.filter(user=self.user, item__title="Re-read Book").count(),
            2,
        )
```

Add `from io import BytesIO` to the test module's imports.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest src/integrations/tests/imports/test_storygraph.py::ImportStoryGraphDeduplication -v`
Expected: FAIL — `test_reimport_creates_nothing` finds 20 books instead of 10.

- [ ] **Step 3: Add deduplication to the importer**

In `StoryGraphImporter.__init__`, after `self.bulk_media = defaultdict(list)`:

```python
        self.tracked_reads = self._load_tracked_reads()
```

Add the two methods:

```python
    def _load_tracked_reads(self):
        """Map each already-tracked book to the read dates it has."""
        tracked = defaultdict(set)
        model = apps.get_model(app_label="app", model_name=MediaTypes.BOOK.value)
        for book in model.objects.filter(user=self.user).select_related("item"):
            key = (book.item.source, book.item.media_id)
            tracked[key].add(book.end_date.date() if book.end_date else None)
        return tracked

    def _tracked_dates(self, source, media_id):
        """Return the read dates to skip, queueing a wipe in overwrite mode."""
        if self.mode == "overwrite":
            if media_id in self.existing_media[MediaTypes.BOOK.value][source]:
                self.to_delete[MediaTypes.BOOK.value][source].add(media_id)
            self.tracked_reads[(source, media_id)] = set()
        return self.tracked_reads[(source, media_id)]
```

Change `_process_row` to pass the tracked dates through:

```python
        source, media_id, metadata = resolved
        item = self._create_or_update_item(source, media_id, metadata, row)
        tracked_dates = self._tracked_dates(source, media_id)
        for instance in self._build_entries(item, row, metadata, tracked_dates):
            self.bulk_media[MediaTypes.BOOK.value].append(instance)
```

Replace `_build_entries` with the deduplicating version:

```python
    def _build_entries(self, item, row, metadata, tracked_dates):
        """Build one unsaved Book per untracked read, newest last."""
        status = determine_status(row.get("Read Status"))
        progress = self._page_count(item, metadata, status)
        reads = (
            parse_reads(row.get("Dates Read"))
            if status == Status.COMPLETED.value
            else []
        )
        fallback_date = parse_date(row.get("Date Added"))
        had_entries = bool(tracked_dates)

        instances = []
        for read in reads:
            read_day = read.end.date() if read.end else None
            if read_day in tracked_dates:
                continue
            tracked_dates.add(read_day)
            instances.append(
                self._build_instance(
                    item,
                    status,
                    read.start,
                    read.end,
                    progress,
                    fallback_date,
                ),
            )

        if not reads and not had_entries:
            tracked_dates.add(None)
            instances.append(
                self._build_instance(item, status, None, None, progress, fallback_date),
            )

        if instances and not had_entries:
            # One StoryGraph rating covers the book, so it goes on the newest
            # entry only - repeating it per re-read would double count it in
            # statistics. A book that already has entries carries its rating
            # there, so a newly added re-read is left unrated.
            newest = instances[-1]
            newest.score = parse_rating(row.get("Star Rating"))
            newest.notes = (row.get("Review") or "").strip()

        return instances
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest src/integrations/tests/imports/test_storygraph.py -v`
Expected: PASS, every class.

- [ ] **Step 5: Commit**

```bash
git add src/integrations/imports/storygraph.py src/integrations/tests/imports/test_storygraph.py
git commit -m "Deduplicate StoryGraph reads by end date across imports"
```

---

### Task 5: Tags become custom lists

**Files:**
- Modify: `src/integrations/imports/storygraph.py`
- Modify: `src/integrations/tests/imports/test_storygraph.py`

**Interfaces:**
- Consumes: `parse_tags` from Task 1, `StoryGraphImporter` from Task 4.
- Produces: `StoryGraphImporter._sync_tags(item, row) -> None`.

- [ ] **Step 1: Write the failing tests**

Append to `src/integrations/tests/imports/test_storygraph.py`:

```python
from lists.models import CustomList, CustomListItem


class ImportStoryGraphTags(TestCase):
    """Tests for mapping StoryGraph tags onto custom lists."""

    def setUp(self):
        """Create the user and import the fixture."""
        self.user = get_user_model().objects.create_user(
            username="test",
            password="12345",  # noqa: S106 - test credential
        )
        self._import()

    def _import(self):
        with patch(
            "integrations.imports.storygraph.services.search",
            side_effect=fake_search,
        ), patch(
            "integrations.imports.storygraph.services.get_media_metadata",
            side_effect=fake_metadata,
        ), Path(mock_path / "import_storygraph.csv").open("rb") as file:
            return storygraph.importer(file, self.user, "new")

    def test_lists_created_from_tags(self):
        """Each tag becomes a local custom list owned by the user."""
        names = set(
            CustomList.objects.filter(owner=self.user).values_list("name", flat=True),
        )
        self.assertEqual(names, {"fantasy", "management", "spanish"})

    def test_items_added_to_their_lists(self):
        """A tagged book joins every list its tags name."""
        tagged = Item.objects.get(title="Tagged Only Book")
        list_names = set(
            CustomListItem.objects.filter(item=tagged).values_list(
                "custom_list__name",
                flat=True,
            ),
        )
        self.assertEqual(list_names, {"management", "spanish"})

    def test_membership_is_idempotent(self):
        """Re-importing does not duplicate lists or memberships."""
        self._import()
        self.assertEqual(CustomList.objects.filter(owner=self.user).count(), 3)
        self.assertEqual(
            CustomListItem.objects.filter(custom_list__owner=self.user).count(),
            3,
        )
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest src/integrations/tests/imports/test_storygraph.py::ImportStoryGraphTags -v`
Expected: FAIL — no `CustomList` rows exist.

- [ ] **Step 3: Add tag syncing**

Add the import at the top of `src/integrations/imports/storygraph.py`:

```python
from lists.models import CustomList, CustomListItem
```

In `StoryGraphImporter.__init__`, after `self.tracked_reads = self._load_tracked_reads()`:

```python
        self.list_cache = {}
```

Add the method:

```python
    def _sync_tags(self, item, row):
        """Mirror the row's tags as custom lists holding this item."""
        for tag in parse_tags(row.get("Tags")):
            custom_list = self.list_cache.get(tag)
            if custom_list is None:
                custom_list = CustomList.objects.filter(
                    owner=self.user,
                    name=tag,
                ).first() or CustomList.objects.create(
                    owner=self.user,
                    name=tag,
                    source="local",
                )
                self.list_cache[tag] = custom_list

            CustomListItem.objects.get_or_create(
                item=item,
                custom_list=custom_list,
                defaults={"added_by": self.user},
            )
```

Call it from `_process_row`, right after the item is created:

```python
        item = self._create_or_update_item(source, media_id, metadata, row)
        self._sync_tags(item, row)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest src/integrations/tests/imports/test_storygraph.py -v`
Expected: PASS, every class.

- [ ] **Step 5: Commit**

```bash
git add src/integrations/imports/storygraph.py src/integrations/tests/imports/test_storygraph.py
git commit -m "Mirror StoryGraph tags as custom lists"
```

---

### Task 6: Incomplete-date report

StoryGraph exports commonly lack read dates. The import summary names the affected books so they can be fixed at the source and re-imported.

**Files:**
- Modify: `src/integrations/imports/storygraph.py`
- Modify: `src/integrations/tests/imports/test_storygraph.py`

**Interfaces:**
- Consumes: `StoryGraphImporter` from Task 5.
- Produces: `StoryGraphImporter._report_lines() -> list[str]`.

- [ ] **Step 1: Write the failing tests**

Append to `src/integrations/tests/imports/test_storygraph.py`:

```python
class ImportStoryGraphDateReport(TestCase):
    """Tests for the incomplete-date report in the import summary."""

    def setUp(self):
        """Create the user and import the fixture."""
        self.user = get_user_model().objects.create_user(
            username="test",
            password="12345",  # noqa: S106 - test credential
        )
        with patch(
            "integrations.imports.storygraph.services.search",
            side_effect=fake_search,
        ), patch(
            "integrations.imports.storygraph.services.get_media_metadata",
            side_effect=fake_metadata,
        ), Path(mock_path / "import_storygraph.csv").open("rb") as file:
            self.counts, self.messages = storygraph.importer(file, self.user, "new")

    def test_books_read_without_dates_listed(self):
        """A read with no dates at all is named in the summary."""
        self.assertIn("No Isbn Book", self.messages)
        self.assertIn("no read date", self.messages)

    def test_reads_without_start_date_listed(self):
        """A read with a finish date but no start date is named."""
        self.assertIn("Kindle Only", self.messages)
        self.assertIn("no start date", self.messages)

    def test_complete_reads_not_listed(self):
        """A read with both dates is not reported."""
        report = [line for line in self.messages.splitlines() if "date" in line]
        self.assertNotIn("The Blade Itself", "\n".join(report))

    def test_report_absent_when_dates_complete(self):
        """An export with complete dates produces no report lines."""
        header = Path(mock_path / "import_storygraph.csv").read_text().splitlines()[0]
        row = (
            "The Blade Itself,Joe Abercrombie,\"\",9780575079793,digital,read,"
            "2021/01/01,2021/02/09,2021/01/20-2021/02/09,1,"
            "\"\",,,,,,,4.5,Grim and funny.,\"\",,\"fantasy\",No"
        )
        user = get_user_model().objects.create_user(
            username="other",
            password="12345",  # noqa: S106 - test credential
        )
        with patch(
            "integrations.imports.storygraph.services.search",
            side_effect=fake_search,
        ), patch(
            "integrations.imports.storygraph.services.get_media_metadata",
            side_effect=fake_metadata,
        ), BytesIO(f"{header}\n{row}\n".encode()) as file:
            _counts, messages = storygraph.importer(file, user, "new")

        self.assertEqual(messages, "")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest src/integrations/tests/imports/test_storygraph.py::ImportStoryGraphDateReport -v`
Expected: FAIL — `"no read date"` is not in the messages.

- [ ] **Step 3: Add the report**

In `StoryGraphImporter.__init__`, after `self.list_cache = {}`:

```python
        self.missing_read_dates = []
        self.missing_start_dates = []
```

In `_build_entries`, record the gaps as each completed instance is built. Replace the loop body and the dateless branch:

```python
        for read in reads:
            read_day = read.end.date() if read.end else None
            if read_day in tracked_dates:
                continue
            tracked_dates.add(read_day)
            if not read.start:
                self.missing_start_dates.append(item.title)
            instances.append(
                self._build_instance(
                    item,
                    status,
                    read.start,
                    read.end,
                    progress,
                    fallback_date,
                ),
            )

        if not reads and not had_entries:
            tracked_dates.add(None)
            if status == Status.COMPLETED.value:
                self.missing_read_dates.append(item.title)
            instances.append(
                self._build_instance(item, status, None, None, progress, fallback_date),
            )
```

Add the report builder:

```python
    def _report_lines(self):
        """Describe the date gaps worth fixing in StoryGraph and re-importing."""
        lines = []
        if self.missing_read_dates:
            titles = ", ".join(dict.fromkeys(self.missing_read_dates))
            lines.append(f"Imported as read with no read date: {titles}")
        if self.missing_start_dates:
            titles = ", ".join(dict.fromkeys(self.missing_start_dates))
            lines.append(f"Imported with a finish date but no start date: {titles}")
        return lines
```

Change the return of `import_data`:

```python
        messages = list(dict.fromkeys(self.warnings)) + self._report_lines()
        return imported_counts, "\n".join(messages)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest src/integrations/tests/imports/test_storygraph.py -v`
Expected: PASS, every class.

- [ ] **Step 5: Commit**

```bash
git add src/integrations/imports/storygraph.py src/integrations/tests/imports/test_storygraph.py
git commit -m "Report StoryGraph reads with missing dates in the import summary"
```

---

### Task 7: Wiring — task, view, url, UI, API

Hook the importer into the app the way every other CSV importer is hooked in.

**Files:**
- Modify: `src/integrations/tasks/_media_imports.py:235-238` (after `import_hardcover`)
- Modify: `src/integrations/tasks/__init__.py:37` (import list) and its `__all__`-style re-export block
- Modify: `src/integrations/views.py:2134-2152` (after `import_hardcover`)
- Modify: `src/integrations/urls.py:63`
- Modify: `src/users/templatetags/user_tags.py:96-99`
- Create: `src/static/img/storygraph-logo.svg`
- Modify: `src/templates/users/import_data.html:1675-1700` (after the Hardcover card)
- Modify: `src/users/models.py:1497`
- Modify: `src/api/fork_views_integrations.py:36` and the docstring at line 54
- Modify: `src/integrations/tests/imports/test_storygraph.py`

**Interfaces:**
- Consumes: `storygraph.importer` from Task 6.
- Produces: celery task `import_storygraph` registered as `"Import from StoryGraph"`; url name `import_storygraph`; API service key `storygraph`.

- [ ] **Step 1: Write the failing tests**

Append to `src/integrations/tests/imports/test_storygraph.py`:

```python
from django.urls import reverse

from config.celery import app as celery_app
from integrations import tasks


class StoryGraphWiring(TestCase):
    """Tests that the importer is reachable from the app."""

    def setUp(self):
        """Create and sign in a user."""
        self.user = get_user_model().objects.create_user(
            username="test",
            password="12345",  # noqa: S106 - test credential
        )
        self.client.force_login(self.user)

    def test_task_registered(self):
        """The celery task is registered under its display name."""
        self.assertEqual(tasks.import_storygraph.name, "Import from StoryGraph")
        self.assertIn("Import from StoryGraph", celery_app.tasks)

    def test_view_requires_a_file(self):
        """Posting without a file reports an error instead of queueing."""
        response = self.client.post(reverse("import_storygraph"), {"mode": "new"})
        self.assertEqual(response.status_code, 302)

    def test_view_queues_the_task(self):
        """Posting a CSV queues the import task."""
        with Path(mock_path / "import_storygraph.csv").open("rb") as file, patch(
            "integrations.tasks.import_storygraph.delay",
        ) as delay:
            response = self.client.post(
                reverse("import_storygraph"),
                {"mode": "new", "storygraph_csv": file},
            )

        self.assertEqual(response.status_code, 302)
        delay.assert_called_once()
```

`from config.celery import app as celery_app` is the same import `src/integrations/tests/test_task_registration.py` uses.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest src/integrations/tests/imports/test_storygraph.py::StoryGraphWiring -v`
Expected: FAIL — `module 'integrations.tasks' has no attribute 'import_storygraph'`.

- [ ] **Step 3: Add the celery task**

In `src/integrations/tasks/_media_imports.py`, add `storygraph` to the `from integrations.imports import (...)` block (alphabetically, after `steam`), then add after `import_hardcover`:

```python
@shared_task(name="Import from StoryGraph")
def import_storygraph(file, user_id, mode):
    """Celery task for importing media data from StoryGraph."""
    return import_media(storygraph.importer, _coerce_uploaded_file(file), user_id, mode)
```

In `src/integrations/tasks/__init__.py`, add `import_storygraph` to the `from integrations.tasks._media_imports import (...)` list, keeping alphabetical order (after `import_steam`). If the module ends with an explicit re-export list, add it there too.

- [ ] **Step 4: Add the view and url**

In `src/integrations/views.py`, after `import_hardcover`:

```python
@require_POST
def import_storygraph(request):
    """View for importing books data from StoryGraph CSV."""
    file = request.FILES.get("storygraph_csv")

    if not file:
        messages.error(request, "StoryGraph CSV file is required.")
        return redirect("import_data")

    mode = request.POST["mode"]
    tasks.import_storygraph.delay(
        user_id=request.user.id,
        file=_read_uploaded_file(file),
        mode=mode,
    )
    messages.info(
        request,
        "The task to import media from StoryGraph CSV file has been queued.",
    )
    return redirect("import_data")
```

In `src/integrations/urls.py`, after the `import/hardcover` line:

```python
    path("import/storygraph", views.import_storygraph, name="import_storygraph"),
```

- [ ] **Step 5: Run the wiring tests**

Run: `pytest src/integrations/tests/imports/test_storygraph.py::StoryGraphWiring -v`
Expected: PASS, 3 tests.

- [ ] **Step 6: Add the logo**

Create `src/static/img/storygraph-logo.svg` — a simple three-bar mark in StoryGraph's palette, no trademarked wordmark:

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32" role="img" aria-label="StoryGraph">
  <rect width="32" height="32" rx="6" fill="#0f1c2e"/>
  <rect x="7" y="18" width="5" height="8" rx="1.5" fill="#f4b942"/>
  <rect x="13.5" y="12" width="5" height="14" rx="1.5" fill="#e8734a"/>
  <rect x="20" y="6" width="5" height="20" rx="1.5" fill="#5bc0be"/>
</svg>
```

- [ ] **Step 7: Add the source display, UI card, task-name map, and API entry**

In `src/users/templatetags/user_tags.py`, after the `"hardcover"` entry:

```python
    "storygraph": {
        "name": "StoryGraph",
        "logo": static("img/storygraph-logo.svg"),
    },
```

In `src/templates/users/import_data.html`, after the Hardcover card's closing `</div>`:

```html
        {# StoryGraph #}
        <div class="bg-[#39404b] p-4 rounded-lg"
             x-show="sourceSupports(['reading'])"
             x-transition.opacity.duration.150ms>
          <div class="flex items-center mb-3">{% source_display "storygraph" %}</div>
          <p class="text-sm text-gray-400 mb-3"
             x-text="importFrequency === 'once' ? 'Import from StoryGraph export (Profile -> Manage Account -> Export StoryGraph Library)' : 'File uploads are not available for periodic imports'">
          </p>
          <form method="post"
                action="{% url 'import_storygraph' %}"
                enctype="multipart/form-data">
            {% csrf_token %}
            <input type="hidden" name="frequency" x-model="importFrequency">
            <input type="hidden" name="time" x-model="importTime">
            <input type="hidden" name="mode" x-model="importMode">
            <label class="flex items-center justify-center w-full px-4 py-2 text-sm rounded-md transition-colors"
                   :class="importFrequency === 'once' && !standardImportsDisabled() ? 'bg-indigo-600 text-white hover:bg-indigo-700 cursor-pointer' : 'bg-gray-600 text-gray-400 cursor-not-allowed'"
                   :disabled="importFrequency !== 'once' || standardImportsDisabled()">
              <input name="storygraph_csv"
                     accept=".csv"
                     class="hidden"
                     type="file"
                     :disabled="importFrequency !== 'once' || standardImportsDisabled()"
                     @change="importFrequency === 'once' && !standardImportsDisabled() && $el.form.submit()">
              Select CSV File
            </label>
          </form>
        </div>
```

In `src/users/models.py`, after the `"hardcover"` entry in `result_task_names`:

```python
            "storygraph": ["Import from StoryGraph"],
```

In `src/api/fork_views_integrations.py`, after the `"hardcover"` entry in `_FILE_IMPORTS`:

```python
    "storygraph": (tasks.import_storygraph, "StoryGraph CSV"),
```

and extend the `ImportDispatchView` docstring's service list to read `goodreads, hardcover, storygraph)`.

- [ ] **Step 8: Run the full import and users test suites**

Run: `pytest src/integrations/tests -q && pytest src/users/tests -q`
Expected: PASS. Investigate any failure before continuing — `src/users/tests/views/test_import_data.py` renders the page that the new card lives on.

- [ ] **Step 9: Lint**

Run: `ruff check src/integrations/imports/storygraph.py src/integrations/views.py src/integrations/tests/imports/test_storygraph.py`
Expected: no findings. Fix anything reported.

- [ ] **Step 10: Commit**

```bash
git add src/integrations/tasks src/integrations/views.py src/integrations/urls.py src/users/templatetags/user_tags.py src/static/img/storygraph-logo.svg src/templates/users/import_data.html src/users/models.py src/api/fork_views_integrations.py src/integrations/tests/imports/test_storygraph.py
git commit -m "Wire up StoryGraph CSV import"
```

---

### Task 8: Verify against the real export

The fixture is synthetic. This checks the importer against the 280-row export in the repo root, without touching a database or a provider.

**Files:**
- No production changes expected. Fix `src/integrations/imports/storygraph.py` if this surfaces a bug.

- [ ] **Step 1: Parse every row of the real export**

Run:

```bash
cd src && python -c "
import csv, django, os
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.test_settings')
django.setup()
from integrations.imports import storygraph
rows = list(csv.DictReader(open('../ea51fe84545edfba6d019e36d854f71015e870866ab83ddc54da3bd7afc274d1.csv', encoding='utf-8-sig')))
reads = statuses = 0
for row in rows:
    parsed = storygraph.parse_reads(row['Dates Read'])
    reads += len(parsed)
    storygraph.determine_status(row['Read Status'])
    storygraph.parse_rating(row['Star Rating'])
    storygraph.parse_tags(row['Tags'])
    storygraph.normalize_isbn(row['ISBN/UID'])
    statuses += 1
print('rows', len(rows), 'reads', reads, 'parsed', statuses)
"
```

Expected: `rows 280 reads 210 parsed 280` — 209 dated reads plus the second read of the one re-read book. No exception. If the read count differs, print the rows whose `Dates Read` is non-empty but parses to nothing and fix the parser.

- [ ] **Step 2: Commit any fix**

Only if Step 1 required a change:

```bash
git add src/integrations/imports/storygraph.py
git commit -m "Fix StoryGraph date parsing found against a real export"
```

---

## Notes for the implementer

- `wiki/` is an empty submodule in this checkout, so there is no wiki page to update. The card's help text in `import_data.html` is the user-facing documentation.
- `helpers.bulk_create_media` calls `bulk_create_with_history`, which bypasses `Model.save()`. That is why progress is computed in the importer instead of relying on `process_progress`, and why `_history_date` must be set on each instance.
- The `Read Count` column is intentionally unused: `Dates Read` is the authoritative record of individual reads, and the two disagree in real exports.
