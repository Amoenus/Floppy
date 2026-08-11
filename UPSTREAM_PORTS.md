# Upstream ports and divergence ledger

> **Status:** Initial baseline under review  
> **Parent issue:** [#645](https://github.com/dannyvfilms/Floppy/issues/645)  
> **Floppy baseline:** `latest` at `ffa267c0479ba4776c43a907e6318b4803d99afb`  
> **Yamtrack baseline:** `dev` at `85646a36298d61d39544f80eacf541c232c4df7b` (`0.26.1`)  
> **Common ancestor:** `88c92c9cfb5b41f807a8e9b82c4dd77f3d7723c4`  
> **Last upstream review:** 2026-08-11  
> **Next comparison range:** `85646a36298d61d39544f80eacf541c232c4df7b..upstream/dev`

## Purpose

Floppy is a substantial fork of Yamtrack, not a lightly modified downstream branch. At the comparison baseline, Yamtrack had 138 commits after the common ancestor while Floppy had 1,695 fork-only commits. Both repositories changed models, migrations, providers, integrations, templates, Docker, CI, and application behaviour.

A branch merge or rebase is therefore not a useful definition of “up to date”. It would combine incompatible histories, create large conflict surfaces, and risk silently removing Floppy-specific functionality.

This document defines a different contract:

> Floppy is current with upstream when every reviewed upstream **outcome** has a recorded decision, evidence, owner, and validation path.

The unit of review is a coherent product or engineering outcome, not an individual commit. Merge commits, version bumps, generated lock/CSS changes, tests, migrations, and follow-up repairs that belong to one outcome are evaluated together.

## Non-goals

This programme does **not**:

- merge or rebase Yamtrack into Floppy;
- promise database reversibility from Floppy back to Yamtrack;
- cherry-pick upstream migrations into Floppy’s current migration graph;
- copy Yamtrack’s monolithic model changes into Floppy’s split model package;
- treat every upstream UI or product choice as automatically desirable;
- import generated assets, release metadata, or dependency-bot commits for their own sake;
- begin implementation before the decision ledger is reviewed.

Issue [#10](https://github.com/dannyvfilms/Floppy/issues/10) remains useful historical context: schema reversibility and semantic upstream compatibility are separate concerns. This ledger governs the latter.

## Decision states

Every upstream outcome must have exactly one current state.

| State | Meaning | Required evidence |
|---|---|---|
| **Pending** | The gap exists, but implementation has not started. | Upstream evidence, Floppy gap evidence, a target phase, and an issue where the work is active. |
| **In progress** | A scoped Floppy issue or PR owns the outcome. | Linked issue/PR, acceptance criteria, and upstream attribution. |
| **Ported** | Equivalent behaviour is merged. | A Floppy PR and regression test proving the outcome. |
| **Superseded** | Floppy already has an equal or stronger implementation. | Specific Floppy code, test, issue, or PR demonstrating that the upstream result is already covered. |
| **Discarded** | The outcome is intentionally not applicable. | A concrete reason from the discard taxonomy below. “Not needed” is insufficient. |
| **Deferred** | The outcome may be valuable but is not in the current sequence. | Rationale, dependency or trigger for reconsideration, and no claim that it is already implemented. |

“Partially ported” is not a terminal state. A mixed upstream change must be split into separate outcomes so each can receive a real state.

## Discard taxonomy

Use these reason codes in the ledger and PR descriptions.

| Code | Reason | Examples |
|---|---|---|
| **D1 — Superseded fork capability** | Floppy already implements the outcome more completely. The correct state is usually **Superseded**, not Discarded. | SQLite WAL configuration, auto-login, public lists, time-to-beat. |
| **D2 — Generated or release-only change** | The commit changes versions, generated CSS/lock output, merge history, or release metadata without a distinct behaviour to port. | Yamtrack version bumps, generated Tailwind churn, merge commits. |
| **D3 — Upstream-specific product/tooling choice** | The change is valid for Yamtrack but not part of Floppy’s chosen product or tooling direction. | A documentation stack migration or Yamtrack-specific image-publishing workflow. |
| **D4 — Unsafe or historical migration implementation** | The desired final behaviour is valid, but the upstream migration is tied to an old schema, release window, or known unsafe intermediate state. Port semantics and tests; generate a Floppy-native migration. | Yamtrack date-truncation repair and April 2026 completed-show repair. |
| **D5 — Dependency update must be re-resolved** | Individual Dependabot commits are not meaningful ports. Re-resolve under Floppy’s lockfile and test each risk group. | Gunicorn, Django, cryptography, Actions version bumps. |
| **D6 — Architecture/path incompatibility** | The upstream implementation targets files or architecture Floppy has replaced. Port tests and behaviour manually rather than cherry-picking code. | Changes to Yamtrack’s monolithic `src/app/models.py`. |
| **D7 — Deliberate product divergence** | The outcome conflicts with an explicit Floppy product decision. The reason must name that decision and its owner. | A UI simplification that would remove Floppy-specific capabilities. |
| **D8 — Independently implemented** | Floppy solved the same issue separately. The state is **Superseded** or **Ported**, with attribution to both histories. | Goodreads decimal ratings in Floppy #379. |

## Review rules

1. **Ledger first.** Add or update this document before opening implementation work for a newly reviewed upstream batch.
2. **Outcomes, not SHAs.** Group commits that implement and repair the same behaviour.
3. **Tests are portable even when code is not.** A superseded or manually reimplemented outcome should still reuse upstream regression cases where relevant.
4. **No raw upstream migrations.** Generate new Floppy migrations against the current schema and migration graph.
5. **No dependency upgrades during the uv conversion.** Reproduce the current dependency graph first; upgrade later in isolated lockfile PRs.
6. **No silent data deletion.** Audit, repair, export, or quarantine ambiguous user data before enforcing stronger constraints.
7. **Closed Floppy issues remain closed.** Historical reports can prove reach or regression surfaces without being reopened.
8. **No automatic upstream merge.** Automated review may open or update the tracking issue, but a human must choose every decision state.
9. **Preserve attribution.** Adapted PRs must name upstream issues, PRs, commits, and authors where practical.
10. **Record the new upstream baseline after review.** Future reviews compare only the incremental range.

# Delivery roadmap

The ordering below is authoritative unless the parent issue records an explicit change. RICE efficiency informed the ordering, but release safety and data integrity take precedence over small, high-scoring UX changes.

## Phase 0 — Establish the source of truth

**Issue:** [#645](https://github.com/dannyvfilms/Floppy/issues/645)  
**Release effect:** Documentation only  
**Exit condition:** This document is merged and accepted as the upstream-review contract.

### Steps

1. Record the Floppy and Yamtrack baseline SHAs.
2. Define decision states and discard reasons.
3. Map each reviewed Yamtrack outcome to upstream issues/PRs/commits.
4. Search Floppy issues and PRs for exact matches, adjacent evidence, and superseding implementations.
5. Create only the scoped work-package issues that are necessary to deliver the current roadmap.
6. Link active Floppy issues to the new programme rather than creating duplicates.
7. Keep closed historical issues closed and reference them in this ledger.
8. Review the initial Pending, Superseded, Deferred, and Discarded decisions.
9. Merge this document before implementation starts.
10. Update the parent issue with the documentation PR and all work-package issues.

### Validation

- Every outcome in the initial comparison appears in the master ledger or discard register.
- Every Pending P0/P1 outcome has an active Floppy issue.
- Every Superseded outcome names concrete Floppy evidence.
- Every Discarded outcome has a reason code.

## Phase 1 — Add a publish-blocking image smoke gate

**Issue:** [#646](https://github.com/dannyvfilms/Floppy/issues/646)  
**Upstream precedent:** Yamtrack commit [`368fc461`](https://github.com/FuzzyGrim/Yamtrack/commit/368fc4611208b8987de17b4208429f81433ef21b)  
**Dependencies:** Phase 0  
**Exit condition:** The exact image that would be published must start, become healthy, serve key surfaces, validate MCP, and restart against persistent SQLite data.

### Steps

1. Add a pre-publish Docker job.
2. Build a local single-platform image with the production Dockerfile and build arguments.
3. Start Redis and Floppy in an isolated network.
4. Use a persistent volume for SQLite.
5. Wait for Docker health with bounded retries.
6. Verify `/health/`, login, a static asset, `VERSION`, and `COMMIT_SHA`.
7. Verify the bundled MCP package and console entry point from inside the image.
8. Restart Floppy against the same volume and verify a healthy second boot.
9. Print or upload logs on failure.
10. Make multi-architecture publication depend on the smoke test.

### Existing issue relationship

- [#604](https://github.com/dannyvfilms/Floppy/issues/604) is closed release-engineering context and should not be reopened.
- [#529](https://github.com/dannyvfilms/Floppy/issues/529) is closed image-tag context.
- [#512](https://github.com/dannyvfilms/Floppy/issues/512) remains the broader performance/startup audit.

## Phase 2 — Adopt uv without changing the dependency graph

**Issue:** [#647](https://github.com/dannyvfilms/Floppy/issues/647)  
**Upstream precedent:** Yamtrack PR [#1434](https://github.com/FuzzyGrim/Yamtrack/pull/1434), PR [#1282](https://github.com/FuzzyGrim/Yamtrack/pull/1282), commits [`e6765fa`](https://github.com/FuzzyGrim/Yamtrack/commit/e6765fa636272bfee883a7929c25b6974b843ff3) and [`368fc461`](https://github.com/FuzzyGrim/Yamtrack/commit/368fc4611208b8987de17b4208429f81433ef21b)  
**Dependencies:** Phase 1  
**Exit condition:** One locked dependency graph covers Floppy and bundled MCP; CI, pre-commit, and Docker use locked uv workflows; direct dependency versions have not been broadly upgraded.

### PR 2A — Project model and lockfile

1. Convert current runtime requirements into `[project].dependencies` at their existing versions.
2. Preserve Floppy-only API, MFA/QR, proxy, media, and MCP dependencies.
3. Define lint, test, docs, and dev groups.
4. Keep Python 3.12 for the first conversion.
5. Represent `mcp_server` as a workspace member or explicit local dependency.
6. Generate one `uv.lock`.
7. Add `uv lock --check`.
8. Keep compatibility requirements only as generated exports if still required.

### PR 2B — CI and pre-commit

1. Sync only the test group in application-test jobs.
2. Sync only the lint group in lint jobs.
3. Run tools through `uv run`.
4. Preserve the changed-line lint strategy in [#390](https://github.com/dannyvfilms/Floppy/issues/390) until its broader decision is resolved.
5. Cache by `uv.lock`.
6. Validate Django migrations and project checks in the locked environment.

### PR 2C — Multi-stage Docker build

1. Pin uv by version or digest.
2. Use matching Python and Alpine versions in builder and runtime stages.
3. Build the virtual environment in the dependency layer.
4. Copy it into the runtime image.
5. Preserve repo-owner metadata, `/yamtrack` compatibility, runtime profiles, nginx, Supervisor, entrypoint behaviour, version metadata, and bundled MCP.
6. Validate the result through #646.
7. Measure cold/warm builds, image size, startup-to-health, and idle memory.

### PR 2D onward — Controlled upgrades

1. Re-resolve dependencies under uv.
2. Group upgrades by risk and subsystem.
3. Keep framework, cryptography, process manager, database driver, and Actions major upgrades isolated.
4. Do not cherry-pick upstream Dependabot commits as historical units.

## Phase 3 — Ship isolated low-risk correctness fixes

**Dependencies:** Phase 1; uv is preferred but not required for source-only fixes  
**Exit condition:** Each change is an independently reviewable PR with a regression test.

### 3A — Imported episode history date

- **Owner issue:** #648
- **Upstream:** Yamtrack [#990](https://github.com/FuzzyGrim/Yamtrack/issues/990), commit [`3494dee`](https://github.com/FuzzyGrim/Yamtrack/commit/3494dee98e003931dff439ce277c66d6a48e7c15)
- **Action:** Use `progressed_at`, then `end_date`, then import time.
- **Why first:** Small change, direct user-history correctness, no schema migration.

### 3B — MAL search offset

- **Owner issue:** #649
- **Upstream:** commit [`8aaea2d`](https://github.com/FuzzyGrim/Yamtrack/commit/8aaea2d78409edeec5f6b4f842eb066e0cbd740a)
- **Action:** Add page offset while preserving Floppy title handling and validating total-page semantics.

### 3C — Open Library User-Agent

- **Owner issue:** #649
- **Upstream:** commit [`dc7271e`](https://github.com/FuzzyGrim/Yamtrack/commit/dc7271e22ca91f1400a73978b2ed80c5844019bb)
- **Action:** Add Floppy identity to all synchronous and asynchronous Open Library requests.

### 3D — Notes search

- **State:** Deferred until P0/P1 packages are underway.
- **Upstream:** Yamtrack [#1007](https://github.com/FuzzyGrim/Yamtrack/issues/1007), commit [`2af59c2`](https://github.com/FuzzyGrim/Yamtrack/commit/2af59c29e3766494c602c4ef736fd068d93e9b38)
- **Action:** Extend Floppy’s existing title/media-ID search with notes; do not replace current search behaviour.
- **Trigger:** Create a scoped issue when implementation starts.

### 3E — Goodreads shelf semantics

- **State:** Deferred.
- **Upstream:** Yamtrack [#1062](https://github.com/FuzzyGrim/Yamtrack/issues/1062), commits [`66cbf00`](https://github.com/FuzzyGrim/Yamtrack/commit/66cbf0070abe497c8d49f035b534307bc2963ff5) and [`4082a5f`](https://github.com/FuzzyGrim/Yamtrack/commit/4082a5f77dc93b3f383c937ae90f79219895af7f)
- **Action:** Map `did-not-finish` to Dropped and warn/skip truly unsupported shelves.
- **Do not port:** Decimal-rating parsing is already independently implemented and tracked by Floppy [#379](https://github.com/dannyvfilms/Floppy/issues/379).

## Phase 4 — Datetime and calendar integrity

**Issue:** [#648](https://github.com/dannyvfilms/Floppy/issues/648)  
**Upstream:** Yamtrack [#884](https://github.com/FuzzyGrim/Yamtrack/issues/884), [#990](https://github.com/FuzzyGrim/Yamtrack/issues/990), [#1512](https://github.com/FuzzyGrim/Yamtrack/issues/1512), [#1633](https://github.com/FuzzyGrim/Yamtrack/issues/1633)  
**Dependencies:** Phases 1 and 3A  
**Exit condition:** Final UTC-safe runtime semantics, a read-only audit, Floppy-native migrations, and SQLite/PostgreSQL fresh/upgrade validation.

### PR 4A — Specify and test final semantics

1. Define UTC minute normalization.
2. Define safe unknown-past and unknown-future sentinels.
3. Define undated TV episode behaviour.
4. Define the later-aired-episode heuristic.
5. Cover UTC, Europe/Dublin winter/summer, and extreme positive/negative offsets.
6. Cover Trakt, SIMKL, CSV import, form editing, deletion, dashboard progress, and completion status.

### PR 4B — Runtime implementation

1. Introduce one shared UTC normalization helper.
2. Apply it to Trakt and SIMKL editable media fields.
3. Preserve intentionally full-precision history events.
4. Replace unsafe boundary sentinels with helper methods.
5. Resolve missing TV dates explicitly before assigning sentinels.
6. Exclude unknown/unreleased episodes from released progress.

### PR 4C — Read-only audit

1. Count second/microsecond values.
2. Find legacy min/max placeholders.
3. Detect known timezone-shift patterns.
4. Report impossible or ambiguous values.
5. Support human-readable and machine-readable output.
6. Modify no data.

### PR 4D — Floppy-native migrations

1. Generate new migration numbers against current split models.
2. Port the final corrected state only.
3. Use bounded batches.
4. Preserve history where possible.
5. Test data-transform functions for idempotence.
6. Provide a no-op reverse when reversal would be unsafe.

### PR 4E — Upgrade matrix and recovery

1. Test fresh SQLite and PostgreSQL installs.
2. Test upgrades from representative older snapshots.
3. Validate first and second container boot through #646.
4. Re-run the audit after migration.
5. Document backup and recovery requirements.

### Historical Floppy evidence

- [#30](https://github.com/dannyvfilms/Floppy/issues/30) — local-day grouping.
- [#36](https://github.com/dannyvfilms/Floppy/issues/36) — UTC-only UI display.
- [#559](https://github.com/dannyvfilms/Floppy/issues/559) — watch/history time divergence.
- [#143](https://github.com/dannyvfilms/Floppy/issues/143) and [#283](https://github.com/dannyvfilms/Floppy/issues/283) — adjacent future/upcoming behaviour.

These issues remain closed.

## Phase 5 — Provider correctness

**Issue:** [#649](https://github.com/dannyvfilms/Floppy/issues/649)  
**Dependencies:** Phase 3B/3C; coordinate unknown dates with Phase 4  
**Exit condition:** Offline deterministic provider tests prove paging, unknown-count, and request-identity behaviour.

### PR 5A — Provider fixtures

1. Add MAL multi-page fixtures.
2. Add AniList outer and nested pagination fixtures.
3. Add unknown total-count fixtures.
4. Add MAL/AniList disagreement fixtures.
5. Assert Open Library headers for `requests` and `aiohttp`.

### PR 5B — AniList nested schedule pagination

1. Add independent nested page variables.
2. Accumulate nodes per MAL ID.
3. Preserve outer-page pagination.
4. Deduplicate and validate episode order.
5. Keep valid nodes when total episodes are unknown.
6. Do not invent a final episode from an untrusted fallback count.

### PR 5C — Remaining provider verification

1. Verify cache keys and call counts.
2. Ensure malformed provider data becomes warnings/empty results rather than task-wide crashes.
3. Run live-provider checks deliberately, outside normal offline CI.

## Phase 6 — Audit identity and enforce safe constraints

**Issue:** [#650](https://github.com/dannyvfilms/Floppy/issues/650)  
**Upstream:** commit [`bd0b4f5`](https://github.com/FuzzyGrim/Yamtrack/commit/bd0b4f5b3b89195511c9fa1c3da5d5e99b2137e8), Yamtrack [#1348](https://github.com/FuzzyGrim/Yamtrack/issues/1348)  
**Dependencies:** Phases 1 and 4  
**Exit condition:** Identity corruption is audited and safely repaired before `Episode.item` becomes non-null.

### PR 6A — Define and audit identity

1. Define valid TV, season, episode, provider, and library-bucket identity keys.
2. Distinguish repeated watches from duplicate identity rows.
3. Report null, mismatched, duplicate, and orphaned rows.
4. Include historical evidence for reconstruction.
5. Support machine-readable audit output.

### PR 6B — Deterministic repair

1. Reattach exact matching items.
2. Construct missing items only from deterministic evidence.
3. Merge duplicate identity trees transactionally.
4. Preserve dates, ratings, dropped state, notes, and history.
5. Reconcile status/progress and clear caches.

### PR 6C — Ambiguous recovery path

1. Export or quarantine ambiguous rows.
2. Document manual resolution.
3. Block the final constraint while unresolved invalid rows remain unless an explicit loss policy is approved.

### PR 6D — Schema enforcement

1. Make `Episode.item` non-null.
2. Add/verify identity constraints without preventing repeated watch rows.
3. Add import and webhook regression tests.
4. Validate SQLite/PostgreSQL upgrades and both container boots.

### PR 6E — Falsely reopened completed-show audit

1. Detect candidates from status history, events, and parent/child consistency.
2. Do not copy Yamtrack’s April 2026 release-window constants.
3. Dry-run before modification.
4. Repair only high-confidence cases.

### Historical Floppy evidence

- [#246](https://github.com/dannyvfilms/Floppy/issues/246) — duplicate item identity during CSV episode import.
- [#295](https://github.com/dannyvfilms/Floppy/issues/295) — duplicate season identity blocked episode tracking.

These are adjacent evidence, not duplicates of #650.

## Phase 7 — Product polish and intentional divergence

These outcomes are not allowed to delay release safety, reproducibility, or data integrity.

### Notes search

- **State:** Deferred.
- **Action:** Add notes to existing title/media-ID search with tests.

### Season image fallback

- **Upstream:** Yamtrack [#1353](https://github.com/FuzzyGrim/Yamtrack/issues/1353), commit [`9063ad4`](https://github.com/FuzzyGrim/Yamtrack/commit/9063ad439aa42ccce07086c0a25cd9d73ddb6c01)
- **Current decision:** Split outcome.
  - Runtime fallback during common season creation/refresh paths: **Superseded** by Floppy.
  - Manual-provider fallback and one-time backfill of existing placeholders: **Deferred** pending a focused audit.

### Steam overwrite

- **Upstream:** commit [`fb96b27`](https://github.com/FuzzyGrim/Yamtrack/commit/fb96b270c44320ba3bd28d3fb1943008995e3c2c)
- **Current decision:** Split outcome.
  - Updating existing games while preserving final statuses: **Superseded** by Floppy.
  - History-aware bulk updates and import counts that include updates: **Deferred**.

### Persistent automatic-change messages

- **Upstream:** commit [`f2ae691`](https://github.com/FuzzyGrim/Yamtrack/commit/f2ae691d889559abd2257900a708a5b2ab761667)
- **State:** Deferred.
- **Reason:** Useful transparency, but adds a model, retention task, context processing, toast flow, and integration surface. Reconsider after data-integrity automation is stable.

### Global change journal

- **Upstream:** commit [`4cb1ea0`](https://github.com/FuzzyGrim/Yamtrack/commit/4cb1ea02cf9e63ddf2f23d0c868462d5d460579c)
- **State:** Deferred.
- **Reason:** This is a genuine gap distinct from Floppy’s playback History and per-item history. It requires a product decision on scope, retention, pagination, and privacy rather than a blind port.

## Phase 8 — Ongoing upstream review

### Review cadence

Run an upstream review at least monthly and before a major Floppy release when upstream activity is material.

### Incremental process

1. Fetch Yamtrack `dev`.
2. Compare `last-reviewed-sha..upstream/dev`.
3. Group commits into outcomes.
4. Search both repositories for issues, PRs, and existing implementations.
5. Update the master ledger and discard register.
6. Open or update Floppy work-package issues only for accepted Pending work.
7. Add comments to active matching Floppy issues.
8. Keep closed historical issues closed.
9. Require a failing Floppy regression test or supersession evidence before implementation decisions are accepted.
10. Update the baseline SHA after review.

### Automation boundary

Automation may:

- fetch and group upstream commits;
- propose issue matches;
- draft ledger entries;
- flag stale Pending decisions.

Automation must not:

- merge upstream;
- choose Discarded or Superseded without evidence;
- apply migrations;
- publish images;
- close user issues solely because an upstream fix exists.

# Master outcome ledger

Priority tiers describe portfolio order, not only raw RICE efficiency.

| Outcome | Upstream evidence | Floppy evidence / owner | State | Priority | Decision and next action |
|---|---|---|---|---|---|
| Upstream decision ledger | This review | #645 and this document | **In progress** | P0 | Merge before implementation. |
| Built-image smoke gate | `368fc461` | #646; context #604, #529, #512 | **Pending** | P0 | Adapt and add MCP plus persistent-volume restart checks. |
| uv project and lockfile | PR #1434, PR #1282, `e6765fa` | #647; coordinate #390 and #512 | **Pending** | P0 | Reproduce current versions first; one lock boundary for app and MCP. |
| uv multi-stage Docker | `e6765fa` | #647, validated by #646 | **Pending** | P0 | Adapt, preserving Floppy runtime stages and compatibility behaviour. |
| Imported episode activity date | #990, `3494dee` | #648; historical #559 | **Pending** | P0 | Direct semantic port with regression test. |
| Trakt/SIMKL minute normalization | #1512, `60a4036` | #648 | **Pending** | P0 | Port final UTC-safe semantics only. |
| Repair unsafe truncation/timezone shifts | #1633, `e2ed720` | #648; historical #30, #36, #559 | **Pending** | P0 | Floppy-native audit/migration; D4 for upstream migration implementation. |
| Unknown TV episode release dates | #884, `7bb3a6f` | #648; adjacent #143, #283 | **Pending** | P0 | Explicit unknown/unreleased semantics. |
| Overflow-safe sentinels | #884, `791d800` | #648 | **Pending** | P0 | Adapt final helper semantics and timezone tests. |
| MAL search pagination | `8aaea2d` | #649 | **Pending** | P1 | Add offset; validate Floppy total-page contract. |
| AniList nested schedule pagination | #1369, `69454ff` | #649 | **Pending** | P1 | Manual provider port with offline fixtures. |
| Open Library User-Agent | `dc7271e` | #649 | **Pending** | P1 | Add Floppy identity to sync and async requests. |
| Enforce `Episode.item` identity | `bd0b4f5` | #650; adjacent #246, #295 | **Pending** | P1 | Audit/repair before non-null; do not silently delete history. |
| Repair falsely reopened shows | #1348, `82a1f30` | #650 | **Pending** | P1 | Detect by data evidence; D4 for upstream release-window migration. |
| Search notes | #1007, `2af59c2` | No exact Floppy issue | **Deferred** | P2 | Create a scoped issue when Phase 7 starts. |
| Goodreads unsupported shelves | #1062, `66cbf00` | No exact Floppy issue | **Deferred** | P2 | Map DNF and warn/skip unknown shelves. |
| Goodreads decimal ratings | #1577, `4082a5f` | Floppy #379 and current float parsing | **Superseded** | — | D8: independently implemented; no new issue. |
| Season poster fallback during creation | #1353, `9063ad4` | Current Floppy TV/season creation and refresh paths | **Superseded** | — | D1 for common runtime paths. |
| Manual season fallback / placeholder backfill | #1353, `9063ad4` | No focused audit | **Deferred** | P2 | Audit remaining placeholder rows before opening work. |
| Steam overwrite core behaviour | `fb96b27` | Current Floppy Steam importer | **Superseded** | — | D1: existing updates preserve completed/dropped state. |
| Steam history-aware updates/reporting | `fb96b27` | No scoped issue | **Deferred** | P2 | Reconsider as a small importer-quality PR. |
| Persistent automatic-change messages | `f2ae691` | No scoped issue | **Deferred** | P3 | Product/retention decision required. |
| Global change journal | `4cb1ea0` | Floppy has playback History, not a global change feed | **Deferred** | P3 | Separate product design; not a direct History replacement. |
| Dependency version convergence | Upstream dependency commits | #647 after baseline uv work | **Deferred** | P1 | D5: re-resolve and test under Floppy’s lockfile. |

# Upstream-to-Floppy issue map

| Yamtrack issue / PR | Upstream outcome | Floppy match | Match type | Action |
|---|---|---|---|---|
| PR #1434 / PR #1282 | uv migration | #647; active context #390 and #512 | New scoped owner plus active adjacent issues | Comment on #390 and #512; no duplicate uv issue beyond #647. |
| #990 | Episode CSV history date | #648; historical #559 | New owner plus closed evidence | Keep #559 closed. |
| #884 | Unknown episode dates / progress | #648; adjacent #143 and #283 | New owner plus closed adjacent evidence | Keep historical issues closed. |
| #1512 | Seconds block date editing | #648 | New owner | Port final semantics. |
| #1633 | Unsafe migration / restart loop | #648 and #646 | New owner plus release-safety dependency | Use upgrade fixtures and two-boot smoke test. |
| #1007 | Search notes | None exact | Untracked deferred gap | Create issue only when scheduled. |
| #1369 | AniList episode schedule | #649 | New scoped owner | Port with fixtures. |
| #1353 | Season poster fallback | Floppy runtime partially supersedes it | Partial match | Split runtime fallback from backfill gap. |
| #1062 | Unsupported Goodreads shelves | None exact | Untracked deferred gap | Port DNF/skip semantics later. |
| #1577 | Decimal Goodreads ratings | #379 | Exact historical match, already completed | Mark Superseded; no new issue. |
| #1348 | False reopened completed shows | #650 | New scoped owner | Audit by data characteristics, not release dates. |
| No issue; `8aaea2d` | MAL offset | #649 | New scoped owner | Port. |
| No issue; `dc7271e` | Open Library User-Agent | #649 | New scoped owner | Port with Floppy identity. |
| No issue; `368fc461` | Image smoke test | #646; context #604/#529/#512 | New narrow owner | Comment on active #512; keep closed issues closed. |
| No issue; `bd0b4f5` | Episode item non-null | #650; adjacent #246/#295 | New safe owner | Audit and repair before constraint. |

# Superseded register

These upstream outcomes are already covered by equal or stronger Floppy behaviour. They should not generate implementation PRs unless new evidence disproves the stated coverage.

| Upstream outcome | Floppy coverage | Decision |
|---|---|---|
| Configure SQLite for concurrent writes (`95800c9`) | Floppy configures busy timeout, WAL, and synchronous mode and has additional lock/retry handling. | **Superseded — D1** |
| Auto-login option (`a055a8a`) | Floppy supports `FLOPPY_AUTO_LOGIN_USERNAME` with legacy Yamtrack fallback. | **Superseded — D1** |
| Week-start preference (`1b40244`) | Floppy already exposes a week-start preference across relevant views. | **Superseded — D1** |
| Session age and expanded date preferences | Floppy has richer session-duration, date-format, and time-format preferences. | **Superseded — D1** |
| Hide/planned-home controls | Floppy has configurable home rows and planned-home display modes. | **Superseded — D1** |
| Obfuscate unseen episode content | Floppy already has spoiler/obfuscation behaviour and settings. | **Superseded — D1** |
| Time-to-beat (`32f47fe`) | Floppy includes time-to-beat metadata, sorting, and display surfaces. | **Superseded — D1** |
| Public medialists/private profiles (`fe51e8f`) | Floppy has richer public/private lists, slugs, profiles, feeds, recommendations, and smart lists. | **Superseded — D1** |
| Basic HTMX in-place updates and no-date episode entry (`3ee9ad8`, `83cdea8`) | Floppy’s current modal uses HTMX, local-time initialization, and explicit date clearing. | **Superseded — D1** |
| Top-rated deduplication (`1c48c27`) | Floppy aggregates duplicate entries across items and mixed media buckets in statistics. | **Superseded — D1** |
| Provider network failures without HTTP responses (`1c449bf`) | Floppy handles request exceptions without response objects, bounded retries, and Redis limiter fallback. | **Superseded — D1** |
| Hardcover query caps and token normalization | Floppy already caps queries at word boundaries and normalizes bearer tokens. | **Superseded — D1** |
| Open Library abbreviated publication dates (`156c6f6`) | Floppy accepts full dates, month/year, and year-only values. | **Superseded — D1** |
| AniBridge webhook matching (`2fda336` and predecessors) | Floppy has a newer AniBridge v3 mapping layer and broader webhook/media-server logic. | **Superseded — D1/D8** |
| Goodreads decimal ratings (#1577) | Floppy #379 and current float parsing handle decimal exports. | **Superseded — D8** |

# Discard register

The following commits or implementation forms are intentionally not ported. This does not discard valid user-facing outcomes that appear separately in the master ledger.

| Upstream change/category | State | Reason |
|---|---|---|
| Direct merge/rebase of Yamtrack `dev` | **Discarded** | **D6:** histories and architectures have diverged substantially; semantic review replaces branch convergence. |
| Raw changes to Yamtrack’s monolithic `src/app/models.py` | **Discarded as implementation** | **D6:** Floppy split models into focused modules. Port tests/behaviour manually. |
| Yamtrack migration numbers and dependencies | **Discarded as implementation** | **D4/D6:** Floppy has a different migration graph and schema. |
| Original unsafe date truncation followed by repair | **Discarded as implementation** | **D4:** implement the final UTC-safe state once. |
| April 2026 release-window repair for falsely reopened shows | **Discarded as implementation** | **D4:** timestamps describe Yamtrack deployments, not reliable Floppy evidence. |
| Individual Dependabot commits | **Discarded as port units** | **D5:** upgrades must be re-resolved under Floppy’s lockfile and tested by risk group. |
| Automated Python 3.14 base-image bump | **Discarded for initial uv work** | **D5:** keep Python 3.12 while changing package management; consider interpreter upgrades separately. |
| Yamtrack version bumps and package-name metadata | **Discarded** | **D2/D3:** release metadata is upstream-specific. |
| Merge commits | **Discarded** | **D2:** no independent outcome. |
| Generated Tailwind CSS changes without a source change to port | **Discarded** | **D2:** regenerate from Floppy sources when required. |
| Yamtrack README branding and documentation links | **Discarded** | **D3:** use Floppy naming and information architecture. |
| Zensical documentation migration | **Discarded from this programme** | **D3:** unrelated tooling choice; reconsider only through a separate docs-platform decision. |
| Yamtrack stale-issue automation | **Discarded from this programme** | **D3:** repository-governance choice unrelated to product parity. |
| Worktree/editor settings | **Discarded from this programme** | **D3:** contributor tooling preference, not runtime parity. |
| Yamtrack API-image/release-channel workflows | **Discarded as implementations** | **D3/D6:** Floppy has distinct images, MCP bundling, tags, and release requirements. Port only specific validation outcomes such as #646. |
| Upstream statistics redesign as a whole | **Discarded as a wholesale port** | **D1/D7:** Floppy statistics are substantially richer. The global journal is tracked separately as Deferred. |

# PR structure and review requirements

## PR sizing

- One behavioural outcome per low-risk PR.
- One coherent semantic layer per high-risk PR: tests, runtime behaviour, audit, migration, or upgrade validation.
- Workflow-only changes may need separate PRs when repository protections reject workflow and source changes together.
- Generated lockfiles belong with the metadata change that produced them, not with unrelated source changes.

## Required PR description fields

Every upstream-derived PR must include:

1. Upstream issue, PR, and commit references.
2. Whether the code was cherry-picked, adapted, or independently reimplemented.
3. Intentional differences from Yamtrack.
4. The ledger outcome being moved to In progress or Ported.
5. Regression tests.
6. Database/backend impact.
7. Migration and rollback notes where applicable.
8. Performance measurements where the change affects build/startup/runtime cost.
9. AI-assistance disclosure consistent with repository policy.

## Merge gates

- Phase 0 documentation reviewed.
- CI provides a meaningful signal.
- Tests fail before and pass after the behaviour change, or supersession evidence is explicit.
- Data migrations are exercised on representative snapshots.
- Docker-affecting changes pass #646.
- No unresolved ambiguity is hidden behind warnings or silent deletion.

# Maintaining this document

When an outcome moves state:

1. Update the master ledger row.
2. Add the Floppy issue/PR.
3. Add validation evidence.
4. Update the baseline only after all commits in the reviewed range have decisions.
5. Preserve old decisions in Git history; do not erase rationale without explaining why it changed.

The parent issue [#645](https://github.com/dannyvfilms/Floppy/issues/645) is the programme index. Implementation details belong in the scoped child issues, while this file remains the durable source of truth for parity and divergence decisions.
