# What the test suite costs

The suite got slow enough that waiting on it became the bottleneck for both
people and agents. This records what was measured, what the causes actually
are, and what was changed.

All numbers below are from one cloud container: 4 CPUs, 16 GiB RAM, SQLite,
`--parallel` (so 4 workers), `--exclude-tag slow --exclude-tag network`.
6,115 tests across 420 test files.

## Headline

| | before | after |
| --- | --- | --- |
| test-database setup, every run | 141 s | 141 s (2.8 s with `FLOPPY_TEST_FAST_DB=1`) |
| `app.tests.views.test_history` (35 tests), execution only | 53.6 s | 31.0 s |
| whole suite, one app at a time | — | 398 s with `FLOPPY_TEST_FAST_DB=1` |
| whole suite, single invocation | 21 min+, sometimes never finishes | unchanged; now bounded by a timeout |

## Cause 1: 141 seconds of migrations before any test runs

`setup_databases()` takes 141 s, and 140.1 s of that is applying migrations —
422 of them. It is the same 141 s whether the run is `--parallel 1` or
`--parallel 4` (the migrate is serial; the workers then clone the result), and
the same 141 s for one targeted test as for the whole suite. That is the floor
under every single test command anyone runs.

Where it goes:

| app | migrations | time |
| --- | --- | --- |
| users | 121 | 88.8 s |
| app | 153 | 33.2 s |
| integrations | 50 | 10.7 s |
| everything else | 98 | 7.4 s |

`users` is two thirds of it for a third of the migrations. The reason is a
repeating pattern — seventeen migrations named
`users.NNNN_remove_user_tv_sort_valid_and_more`, each ~3.5 s:

```
RemoveConstraint x10   (tv_sort_valid, season_sort_valid, movie_sort_valid, ...)
AlterField       x10   (the matching *_sort CharField choices)
AddConstraint    x10
```

Every time a sort option was added to a choices list, `makemigrations`
regenerated the whole check-constraint set. On SQLite each of those ~30
operations rebuilds the entire `users_user` table, and `users_user` is wide.
The tables are empty — this is pure DDL overhead, thirty table rebuilds per
migration.

### What was done

`FLOPPY_TEST_FAST_DB=1` sets `MIGRATION_MODULES` to `None` for the first-party
apps, so the schema is created straight from the models: **141 s → 2.8 s**.

It is **opt-in, not the default**, for two honest reasons:

* it stops the suite exercising the migration graph at all, and
  `config.tests.test_migration_hygiene` fails under it (correctly — that test
  reads the migration graph, which is exactly what the flag skips);
* it skips `RunPython` data migrations, so anything depending on rows a
  migration creates would silently differ.

Use it while iterating. Do not use it as the final gate on a migration change,
and CI should not use it.

### What should be done next

Squash the `users` migrations. That is the real fix: it helps CI and every
contributor, permanently, with none of the flag's caveats, and would remove
most of 88.8 s. The repo has done this before (`users.0009_..._squashed_0022_...`),
and `check_migration_hygiene` plus `scripts/replay_upgrade_matrix.sh` are the
gates a squash has to satisfy. It deserves its own change, not a drive-by.

## Cause 2: password hashing, 42% of an auth-heavy module

Django's default `PBKDF2PasswordHasher` costs **296 ms per hash** on this
hardware. The suite has 631 `create_user`/`create_superuser` call sites, 210
`client.login(...)` calls (each of which verifies, another 296 ms), and 586
`setUp` methods against only 17 `setUpTestData` — so most of that cost is paid
per test method, not once per class.

Measured on `app.tests.views.test_history`: 72 encodes (21.8 s) + 35 verifies
(10.6 s) = **32.4 s of the 53.6 s** the module spent executing tests.

### What was done

`config/test_settings.py` now sets:

```python
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
```

`app.tests.views.test_history` went from 53.6 s to 31.0 s of execution, a 42%
cut, with no test changes. Tests assert on authorization, never on hash
strength, and this is test settings only — production is untouched.

### What should be done next

Move the expensive per-class fixtures from `setUp` to `setUpTestData`. 586
against 17 is the wrong ratio; `setUpTestData` builds once per class inside an
atomic block instead of once per test method. This is a mechanical but
file-by-file change and is not attempted here.

## Cause 3: the parallel runner can lose results and hang forever

This is the one that actually strands a session, and it is not slowness — it
is a hang.

Reproduced with `app` and `integrations` in a single `--parallel` invocation
(each passes on its own: 159 s and 38 s). Instrumenting
`ParallelTestSuite.run_subsuite` and the parent's result loop:

```
PARENT_DISPATCH total_subsuites=659 processes=4
WORKER_START:      659
WORKER_DONE:       659        <- every subsuite finished
PARENT_RECEIVED:   565        <- 94 results never arrived
```

Every test ran to completion. All four workers were then idle in
`multiprocessing.queues.get()`, and the parent sat in `IMapIterator.next()`
waiting for results that never came. A `py-spy` dump of the parent showed
`_handle_workers` and `_handle_tasks` but **no `_handle_results` thread** — the
pool's result-handler thread was gone, which is why delivery stopped dead.

Ruled out:

* **not unpicklable results.** Pickling every result in the worker succeeded;
  the whole run's results total 188 KB, the largest 5.2 KB.
* **not a stuck test.** All 659 subsuites reported done.
* **not the `FLOPPY_TEST_FAST_DB` flag.** The first full-suite run in this
  session, with real migrations and no flag, also ran 21 minutes without
  producing output.

It is **intermittent** — a later identical run of `app integrations` passed
(659/659 received). That matches the reported experience of the GitHub run
taking "about 30 minutes, sometimes 40".

This is a race in the interaction between Django's parallel runner and
`multiprocessing.Pool`, not a Floppy bug in the ordinary sense, and fixing it
properly is its own investigation. What is not acceptable is that it hangs
silently.

### What was done

`scripts/test.sh` now wraps the runner in `timeout --kill-after=30s`, default
2700 s, tunable with `FLOPPY_TEST_TIMEOUT` (`0` disables). A lost-result hang
now fails loudly with a non-zero exit instead of never returning. CI already
has `timeout-minutes` on its jobs.

### What should be done next

* Try `--parallel` with a `spawn` start method, or a smaller worker count, and
  see whether the race survives.
* Capture a reproduction with `faulthandler` armed in the parent so the
  `_handle_results` death can be attributed to a specific result.
* Until then, treat a suite run that produces no output well past its usual
  wall time as this bug, not as a slow test.

## How to run tests quickly now

```bash
# Iterating on non-migration code — the fast path.
FLOPPY_TEST_FAST_DB=1 SECRET=test-only scripts/test.sh app.tests.test_statistics_refresh_run

# The real gate: real migrations, real graph.
SECRET=test-only scripts/test.sh app.tests.test_statistics_refresh_run

# Whole fast suite.
SECRET=test-only scripts/test.sh
```

Running apps one at a time (`app`, then `users`, …) both avoids the
lost-result hang seen so far and gives usable per-app timings:

| app | tests | time (fast DB) |
| --- | --- | --- |
| app | 2,880 | 153 s |
| api | 715 | 142 s |
| integrations | 1,422 | 33 s |
| lists | 268 | 11 s |
| events | 174 | 10 s |
| config | 245 | 10 s |
| users | 411 | 6 s |

## Pre-existing failure worth knowing about

`config.tests.test_container_memory_sample.ReconciliationTests.test_complete_sample_reports_totals_as_reconciled`
fails in this container with and without any change here: it reads real
`/proc` PSS and finds one process without `smaps_rollup`
(`rss_only_processes` is 1, not 0). It is environment-dependent, not a
regression.
