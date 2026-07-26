# StoryGraph CSV Import — Design

Issue: [#957](https://github.com/FuzzyGrim/Yamtrack/issues/957) (StoryGraph half only; Ryot is out of scope).

## Context

StoryGraph has no public API ([roadmap post](https://roadmap.thestorygraph.com/features/posts/an-api));
third-party packages scrape HTML. The account export CSV is the supported path, so the
importer is a file upload like `goodreads.py` and `hardcover.py`.

### Export format

Columns, in order:

```
Title, Authors, Contributors, ISBN/UID, Format, Read Status, Date Added, Last Date Read,
Dates Read, Read Count, Moods, Pace, Character- or Plot-Driven?, Strong Character Development?,
Loveable Characters?, Diverse Characters?, Flawed Characters?, Star Rating, Review,
Content Warnings, Content Warning Description, Tags, Owned?
```

Observed in a real 280-row export:

| Field | Reality |
| --- | --- |
| `Read Status` | `read` (247), blank (26), `currently-reading` (5), `to-read` (2). StoryGraph also emits `did-not-finish`. |
| `ISBN/UID` | 164 ISBN-13, 5 ISBN-10, 56 Amazon ASINs (`B0851JCZYV`), 55 blank. ~40% unusable for ISBN lookup. |
| `Dates Read` | `2021/07/21` (one day), `2022/03/16-2022/04/01` (range), or comma-separated ranges for re-reads. 38 `read` rows have no dates. |
| `Star Rating` | 0–5 with halves (`4.5`). Yamtrack scores 0–10, so ×2. |
| `Tags` | Comma-separated free text (`management`, `spanish`). |
| Pages | **Absent** — unlike the Goodreads and Hardcover exports. |
| Book ID | **Absent** — no stable StoryGraph identifier to key on. |

Rows with a blank `Read Status` also have a blank `Date Added`; they carry only tags.

## Key finding: re-reads are extra `Book` rows

Yamtrack tracks multiple entries per item. `BasicMedia.filter_media` returns a queryset,
`total_medias` and `instance_id` thread through the track modal and history modal, and
`Media` has no unique constraint on `(user, item)`.

The history calendar is built from live rows, not from simple-history:
`history_cache_day_builder.py:176` reads `Book.start_date`/`Book.end_date` directly and never
touches `HistoricalBook`. Hand-written `HistoricalBook` rows would therefore appear nowhere in
the calendar or in statistics. A second `Book` row surfaces a re-read in the calendar, the
statistics, and the item timeline with no new mechanics.

**Decision:** one `Book` row per read.

## Components

### `src/integrations/imports/storygraph.py`

`importer(file, user, mode)` delegating to `StoryGraphImporter`, mirroring `goodreads.py`:
decode UTF-8 with a latin-1 fallback, `DictReader`, per-row try/except that converts
`services.ProviderAPIError` into a warning and any other exception into
`MediaImportUnexpectedError`, then `helpers.cleanup_existing_media` +
`helpers.bulk_create_media`, returning `(imported_counts, deduplicated_messages)`.

### Book resolution

Resolutions are cached within a run, keyed by the normalized ISBN or `title|authors`.

1. `ISBN/UID` counts as an ISBN only when it is 10 or 13 digits after stripping dashes.
   ASINs and blanks skip straight to text search.
2. Query ladder — for each provider in `(hardcover, openlibrary)`, try `isbn`, then
   `"{title} {first author}"`, then `title`.
3. A candidate is accepted only when its title fuzzy-matches the CSV title and its authors do
   not conflict with the CSV authors, the tiering `storyteller.py` uses. Reimplemented
   compactly inside this module: `storyteller.py` works today and its matcher is entangled
   with its own thresholds, so it is not refactored for reuse.
4. `services.get_media_metadata` on the winner supplies `max_progress` (page count).
5. No match produces a warning naming the title and the row is skipped.

OpenLibrary as the second provider also means self-hosters without `HARDCOVER_API`
configured still get results.

### Row to entries

`Dates Read` splits on commas; each part is either `A-B` (start = A, end = B) or a bare
`YYYY/MM/DD`, which StoryGraph writes when only the finish date is known — that becomes
`end_date` with `start_date` left null rather than inventing a same-day start. Reads are
sorted oldest to newest and created in that order, so the newest read ends up first under
`Media.Meta.ordering` (`-created_at`).

| CSV state | Result |
| --- | --- |
| `read`, N date ranges | N rows, each `Completed`, with that read's start/end, `_history_date` = its end date |
| `read`, no dates | 1 row, `Completed`, no dates, `_history_date` = `Date Added` or now |
| `currently-reading` | 1 row, `In progress`, **no dates** |
| `to-read` or blank | 1 row, `Planning`, no dates |
| `did-not-finish` | 1 row, `Dropped`, no dates |

`Date Added` is when a book was shelved, not when reading began — the export has
`currently-reading` rows added years earlier — so it never becomes a `start_date`. It is used
only as the simple-history timestamp for dateless rows, which feeds neither the calendar nor
statistics.

`Star Rating` ×2 and `Review` land on the newest entry only; earlier reads get `score=None`
and empty notes. `statistics_cache.py:458` aggregates every `Book` row with a non-null score,
so repeating one StoryGraph rating across re-read rows would count it twice.

Progress is the resolved provider's `max_progress` on `Completed` entries, 0 otherwise.

### Deduplication and modes

Existing `Book` rows for the user are preloaded, keyed by `(source, media_id)` to the set of
end dates (date granularity, not datetime) already tracked, plus a flag for dateless entries.

- **`new` mode:** create only reads whose end date is not already tracked for that item. A
  dateless read is created only when the item has no entries at all. This deliberately
  departs from `helpers.should_process_media`, which skips a known item wholesale — under
  that rule a read added in StoryGraph after the first import could never arrive.
- **`overwrite` mode:** matched items go through `cleanup_existing_media` as usual and every
  entry is rebuilt from the CSV.

Duplicate end dates within a single file are collapsed the same way.

### Tags to custom lists

`Tags` splits on commas. Per tag:
`CustomList.objects.get_or_create(owner=user, name=tag, source="local")` then
`CustomListItem.objects.get_or_create(item=item, custom_list=..., added_by=user)`, following
`lists/imports/trakt.py`. Membership is idempotent by the model's unique constraint.

### Format

`digital → ebook`, `audio → audiobook`, `paperback → paperback`, `hardcover → hardcover`,
written to `Item.format` **only when it is empty**, the `services/tracking_hydration.py:405`
pattern. `Item` rows are shared across users, so a provider value or another user's value is
never overwritten.

`Book.formatted_progress` renders progress as HH:MM when the format is `audiobook`, so
`audio` rows keep progress 0 rather than storing a page count that would display as a runtime.

### Wiring

- Celery task `Import from StoryGraph` in `integrations/tasks/_media_imports.py`, exported
  from `integrations/tasks/__init__.py`.
- `import_storygraph` view in `integrations/views.py` reading the `storygraph_csv` upload,
  plus the route in `integrations/urls.py`.
- `users/templatetags/user_tags.py` source entry and a `static/img/storygraph-logo.svg` mark.
- Upload card in `templates/users/import_data.html`, alongside Goodreads and Hardcover.
- Task-name entry in `users/models.py` so import history resolves the label.
- `api/fork_views_integrations.py` map entry, exposing `POST /api/integrations/import/storygraph`.
- Wiki import documentation.

### Incomplete-date report

StoryGraph exports are commonly missing read dates, and those gaps are fixable at the source.
The import summary therefore ends with two informational lines listing affected titles, so the
user can correct them in StoryGraph and re-import (the deduplication rules above make a
re-import safe):

- books imported as `read` with no read dates at all
- reads imported with a finish date but no start date

They are appended to the same warnings string the other CSV importers return, after any real
warnings, and prefixed so they read as informational rather than as failures.

## Error handling

- Unreadable upload → `MediaImportError("Invalid file format. Please upload a CSV file.")`.
- Provider failure on a row → warning, row skipped, import continues.
- Unresolvable book → warning naming the title, row skipped.
- Anything else → `MediaImportUnexpectedError` carrying the row, aborting the task.
- Warnings are deduplicated before being returned, as in the other CSV importers.

## Testing

`src/integrations/tests/mock_data/import_storygraph.csv`, hand-written, covering: ISBN-13 hit,
ASIN falling back to title search, missing ISBN, a two-range re-read, `currently-reading`,
`to-read`, `did-not-finish`, blank status with tags, `audio` format, a review, and a half-star
rating.

`src/integrations/tests/imports/test_storygraph.py` with `services.search` and
`services.get_media_metadata` mocked:

- Read counts and per-entry start/end dates, including two rows for the re-read.
- Rating and review on the newest entry only; earlier read has no score.
- Re-importing the same file creates nothing new.
- Re-importing a file with one extra read date creates exactly one row.
- `overwrite` mode rebuilds entries.
- Tags create lists and idempotent membership.
- Format written only when `Item.format` is empty; audio rows keep progress 0.
- Completed rows take page count from provider metadata.
- Unmatched book produces a warning and no entry.
- The incomplete-date report lists the dateless read and the finish-date-only read, and stays
  empty when every read has both dates.
- Status mapping for every `Read Status` value, blank included.

Task registration is covered by the existing `test_task_registration.py` pattern.

## Out of scope

- Ryot import (separate export format, separate issue scope).
- `Moods`, `Pace`, the five content-question columns, `Content Warnings`, and `Owned?` —
  Yamtrack has no field for them and cramming them into notes helps nobody.
- Scraping StoryGraph for periodic sync; this is a one-off file upload, and the import UI
  already blocks file uploads for scheduled imports.
