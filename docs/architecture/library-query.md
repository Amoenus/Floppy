# Library query engine

`src/app/library_query/` is the one engine for list-shaped library surfaces:
the media list, the API, smart lists and Home shelves. Surfaces describe what
they want as a `LibraryQuery` and ask `LibraryQueryExecutor` for a page.

It replaces four implementations that each had their own filters, sorts and
pagination. Because of that, performance fixes (#691, #1004) reached one
surface and missed the others (#1248). Surfaces move onto the engine one at a
time. Until a surface has moved, its old path is still live.

## Contract

- **Candidates are `Item` rows.** Tracker state (status, score, dates) comes
  from correlated subqueries. An item is one candidate however many tracker
  rows (repeat viewings) it has. `trackers.tracker_sources` is the only place
  that knows which tracker model feeds which library, including anime-library
  routing.
- **`page(offset, limit)` returns ordered `Item`s and the total.** Decorating
  them (tracker rows, card art, progress) is the surface's job, and it only
  ever handles one page. `ids()` returns the full match set for smart-list
  membership.
- **Order is value, then lower-cased title, then id**, with nulls last, in the
  requested direction, on both paths. Equal values cannot move between pages.
  `random` is a seeded hash of the id, so a shuffled shelf pages without
  repeats. Keep the seed fixed across a surface's load-more requests.

## Two paths, derived rather than listed

`uses_sql` is true when the sort has a SQL expression and no active filter
needs a Python predicate. No list of "SQL-safe" filters is kept anywhere.

- **SQL:** filtering, ordering, `COUNT` and `LIMIT`/`OFFSET` all run in the
  database.
- **Scan:** every SQL condition narrows the candidates first. The rest are
  then read in batches (`DEFAULT_BATCH_SIZE`), keeping only
  `(value, title, id)`. Tracker rows are loaded one batch at a time, only
  when a predicate or the sort needs them. The page's items are loaded last.
  Memory is bounded by the batch and the page. Computing values in Python is
  still one pass over the narrowed candidates.

## Adding a filter or sort

- **Filter:** add a `FilterDef` to `filters.FILTERS`. Give it the form it can
  be evaluated in:
  - `row`: a condition on one tracker row. All row conditions share one
    `Exists`, so they must hold on the same row.
  - `sql`: a condition on the item.
  - `predicate`: Python, as a last resort. Declare `needs` for what it reads.

  Then add a field to `spec.FilterValues` and map it in `adapters`.
- **Sort:** add a `SortDef` to `sorts.SORTS` with a `sql` expression. Set
  `tracker=True` if the value comes from tracker rows. A key without `sql`
  is computed in Python from the hydrated candidate.

`app.tests.test_library_query` checks that every SQL sort orders the same way
on the scan path. A new sort is covered automatically.

## Status semantics

`FilterValues.status_match` decides what a status or rating filter compares
against:

- `latest`: the item's most recent row by activity (end date, then progress
  time, then creation). This is what the media list and Home show.
- `any`: any tracker row.

Smart lists saved before `status_match` existed are evaluated with `any`, so
their membership does not change.

## Still O(n)

Python predicates (provider availability, author, progress) and Python-only
sorts (runtime, time to beat, next episode, time left) scan the SQL-narrowed
candidates. `ids()` for smart-list sync is O(n) by definition and runs in the
background.
