# SQLite integrity recovery QA and release handoff

## Scope

Repository: `dannyvfilms/Floppy` (native Floppy only)

Branch: `codex/sqlite-integrity-recovery-options`

Base: `dbff5843b5257b1a6db38292325594595a085de8`

This change responds to a production startup failure where a large number of
SQLite foreign-key conflicts caused the entrypoint to print the same integrity
progress and conflict output indefinitely. Docker's `restart: unless-stopped`
could also repeat any fail-and-exit path.

Do not involve FloppyDesktop. Do not release until the independent gates below
are complete.

## Root causes

1. The entrypoint polled the checker with `kill -0`. An exited, unreaped child
   remains visible as a zombie, so the loop treated a completed failure as a
   running integrity check and continued logging.
2. Exiting on a detected conflict is not sufficient under
   `restart: unless-stopped`; Docker can restart the container and repeat the
   same diagnostics.
3. The previous repair policy recognized only orphaned `app_albumartist` rows.
   Other relationship conflicts had no bounded incident report or explicit,
   incident-scoped recovery choice.

## Implemented behavior

- The checker runs once under a 600-second bound. The shell uses one background
  child plus one blocking `wait` so BusyBox `ash` can handle container stop
  signals without polling.
- Failure produces no progress loop. Startup remains alive, idle, and unhealthy
  before migrations or services, preventing restart-driven log growth.
- TERM/INT traps kill and reap both the active checker and the parked child.
- Foreign-key diagnostics retain counts for every conflict and relationship but
  emit at most 20 row samples.
- A bounded JSON report is written beside the database.
- Default behavior changes no relationship rows and blocks startup.
- `accept:<incident-token>` explicitly accepts the current incident without
  changing rows.
- `quarantine:<incident-token>` creates and verifies a consistent full backup,
  writes a durable prepared report, deletes only identified orphan child rows,
  rechecks every relationship, commits, and publishes the resolved report.
- Incident tokens are random and retired after resolution, preventing an old
  destructive approval from applying to a later recurrence.
- Automatic `app_albumartist` repair remains, now with the same verified backup
  and recovery reporting.
- Quarantine is refused when row identity is ambiguous, a table has any trigger,
  the table is `WITHOUT ROWID`, or another safety check cannot be established.
- Report and backup publication use restrictive random staging, fsync, and
  collision-safe atomic publication without following destination symlinks.
- SQLite read-only connections use exact encoded file URIs, including paths with
  `?`, `#`, `%`, spaces, or Unicode.
- A failed final report publication restores the durable prepared report. A
  later startup reconciles that prepared report after confirming the committed
  database state and verified backup.

## Files changed

- `entrypoint.sh`
- `src/config/sqlite_integrity.py`
- `src/config/tests/test_sqlite_integrity.py`
- `README.md`
- `docs/agents/sqlite_integrity_recovery_handoff.md`

No models or migrations are changed.

## Test history and review status

The implementation followed red/green tests. The expanded focused suite first
failed on the missing recovery behavior and reproduced these safety bugs:

- unbounded output for 1,000 conflicts;
- a database named `db?real.sqlite3` backing up a different file;
- a predictable report-temp symlink overwriting another file;
- reuse of an old quarantine token on a later identical incident;
- DELETE-trigger collateral deletion;
- a declared `rowid` column deleting an unrelated valid row;
- a partial backup appearing under an official final name;
- a committed repair retaining a stale blocked report;
- a final resolved-report fsync failure overwriting the prepared report;
- a temporary-table name shadowing a real child table;
- an unresponsive PID 1 during checker and parked-container shutdown.

Latest implementer evidence:

- `34/34` focused tests passed:

  ```bash
  SECRET=qa-local-only \
    UV_PROJECT_ENVIRONMENT=/home/ryan/code/Floppy/.venv \
    scripts/test.sh config.tests.test_sqlite_integrity
  ```

- Python Ruff check passed:

  ```bash
  /home/ryan/code/Floppy/.venv/bin/ruff check \
    src/config/sqlite_integrity.py \
    src/config/tests/test_sqlite_integrity.py
  ```

- `/bin/sh -n entrypoint.sh` and `git diff --check` passed.
- The shell task passed independent spec and code-quality review after its signal
  and child-reaping fixes.
- The recovery task had independent adversarial review and spec review. Those
  reviews found and drove fixes for wrong-file backups, symlink writes, stale
  tokens, triggers, ambiguous row IDs, publication ordering, and prepared-report
  durability.

### Independent QA outcome

Independent review and QA ran against this branch and found three blocking
defects, all fixed on the branch with regression tests:

1. **Critical.** `sqlite_schema.tbl_name` stores the spelling used by
   `CREATE TRIGGER`, but `PRAGMA foreign_key_check` reports the canonical table
   name. The trigger guard compared them with `COLLATE BINARY`, so a trigger
   declared `ON CHILD` against table `child` was not detected: quarantine was
   advertised and performed and the trigger fired, deleting unrelated rows.
   Now compared with `COLLATE NOCASE`.
2. **Important.** A `prepared` report that could not be reconciled exited 1 and
   parked a healthy, already-committed database forever, with no documented
   remedy. Reconciliation failure is now a warning and startup continues.
3. **Important.** Operators were told to supply the fingerprint, but the code
   requires the separate one-time incident token, so the documented procedure
   could never succeed. Message and README now name the token.

The prepared-report restoration path was re-reviewed: the resolved report is
published only after the commit, a publication failure restores the durable
prepared report, and the next startup reconciles it after verifying the backup.

Gates completed: focused suite 36/36, fast suite 3543 tests OK, Ruff, shell
syntax, `git diff --check`, and container incident smoke against the real image
(blocked, 400k-conflict bounding, accept, quarantine, timeout, TERM during check,
TERM while parked, mismatched/retired tokens, trigger refusal). Hosted PR checks,
merge, and published-image verification are recorded on the pull request.

## Required independent QA gates

1. Review the full branch diff against the base for correctness, DRY, bounded
   contexts, unnecessary complexity, data loss, privilege-boundary filesystem
   behavior, concurrency, WAL consistency, and misleading operator output.
2. Re-run the focused suite, Ruff, shell syntax, and `git diff --check` from this
   branch. Treat any discrepancy from the evidence above as a blocker.
3. Re-run the final spec review for the prepared-report restoration path. Inject
   failure after the resolved report replaces the prepared report and verify:
   the database commit is present, the backup contains the original orphan, the
   on-disk report is actually `prepared`, and the next run reconciles it.
4. Run the fast suite:

   ```bash
   SECRET=qa-local-only \
     UV_PROJECT_ENVIRONMENT=/home/ryan/code/Floppy/.venv \
     scripts/test.sh
   ```

5. Build the real Docker image and exercise an orphan-heavy SQLite database with
   a restart policy. Verify all of the following:
   - only 20 conflict samples are logged;
   - there is no `Still checking SQLite integrity` loop;
   - migrations and services do not start on the blocked path;
   - the container stays alive and unhealthy without restarting;
   - `docker stop` exits promptly while checking and while parked;
   - a mismatched or retired token changes no rows;
   - accept preserves every row and starts;
   - quarantine creates a restorable backup before deleting orphans, then starts;
   - manual-only incidents do not advertise or perform quarantine.
6. Open a focused PR to `latest`. Do not modify `.github/workflows/**`. Require
   App Tests, Lint, CodeQL, and Docker Image smoke to be green at the final head.
7. Merge only after the independent review has no Critical or Important findings.

## Production release verification

A merge to `latest` triggers `.github/workflows/docker-image.yml` and publishes
`ghcr.io/dannyvfilms/floppy:latest` for `linux/amd64` and `linux/arm64` after its
built-image smoke test. This is native Floppy only.

After the workflow succeeds:

1. Confirm the workflow used the merge commit and both architectures published.
2. Pull `ghcr.io/dannyvfilms/floppy:latest` without relying on a cached local
   image.
3. Verify the image's `COMMIT_SHA` equals the merge commit.
4. Repeat the blocked/accept/quarantine smoke against the published image.
5. Record the immutable manifest digest and the QA evidence in the PR before
   declaring production complete.

If any gate fails, stop the release. Fix it on the branch, repeat independent
review, and require checks on the new final head.
