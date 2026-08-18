# Floppy–Nuvio Integration Programme

**Status:** Reviewed programme plan  
**Review date:** 2026-08-15  
**Floppy baseline:** `1bb6999a539679a27502c6514c3fdfec70f17091`  
**Target branch:** `latest`  
**Programme issue:** #532

## Decision

Build the programme in two release trains.

### Release Train A — Tracking interoperability

Ship this first:

- scoped client access;
- saved-library/watchlist membership;
- resume progress;
- exact watched state;
- explicit delete and reset;
- idempotent delivery;
- origin-loop prevention;
- ordered changes;
- reconciliation;
- diagnostics;
- conformance fixtures.

### Release Train B — Local Shared Media Workspace

Start this after Train A is stable:

- Floppy lists and Discover rows as read-only catalogs;
- normalized metadata projections;
- cache provenance and freshness;
- declarative add-on registration;
- portable Collection descriptors;
- optional writable list bindings;
- Nuvio self-host pairing through a supported external API.

Do not combine both trains in one release or one pull request.

## One-page operating view

### Now

1. Record current behavior.
2. Correct stale issue relationships.
3. Fix the open malformed Stremio payload defect.
4. Add scoped client credentials.
5. Add durable delivery identity and receipts.
6. Add ordered progress and saved-item changes.
7. Publish a Nuvio conformance kit.
8. Add dry-run reconciliation and diagnostics.
9. Release Tracking Interoperability 1.0.

### Next

1. Publish selected Floppy lists as read-only catalogs.
2. Publish normalized metadata with provenance.
3. Add safe remote fetch and transparent cache state.
4. Add a declarative add-on registry.

### Later

1. Add portable Nuvio Collection descriptors.
2. Add optional writable list bindings.
3. Add user-owned metadata preferences and overrides.
4. Add Nuvio self-host pairing after Nuvio exposes supported authorization and a versioned external contract.
5. Extend the activity contract to other Floppy media domains.

### Not in scope

- direct access to Nuvio PostgreSQL;
- Supabase service-role credentials;
- raw Nuvio account passwords;
- title-only authoritative matching;
- executable plugin synchronization;
- stream or debrid functionality in Floppy;
- a second Floppy database;
- a new microservice;
- unrestricted provider metadata replication;
- a broad identity-platform rewrite.

## Current issue state

Recheck issue state before each PR.

- #532 is the open programme epic.
- #599 is open and owns malformed Cinemeta/Stremio payload handling.
- #598 is open and owns recurring Stremio import visibility.
- #635 is open and owns read-only catalog publication.
- #636 is open and owns scoped API credentials.
- #619 is completed. Keep its behavior as a regression baseline.
- #723 is completed. Keep its watched-state and history rules as a regression baseline.
- #652 is closed as not planned. It is context only. It is not a blocker.

Do not reopen completed issues to recreate an architecture hierarchy.

## Repository rules

- Target `latest`.
- Never target `upstream` or `release`.
- Prefer the smallest maintainable change.
- Use existing patterns before new abstractions.
- Split large work into reviewable PRs.
- Validate models, migrations, authentication, permissions, webhooks, tasks, cache behavior, and external APIs.
- Keep the test and lint baseline at zero.
- Include screenshots for UI changes.
- Include the exact AI-assistance disclosure in each PR.
- Regenerate domain and OpenAPI artifacts when their contracts change.
- Run migration hygiene and upgrade replay when schema changes require them.

## External dependency

Floppy can publish its server contract.

A complete Nuvio user experience still needs one of:

- a Nuvio client that implements the Floppy contract;
- a compatible bridge;
- a supported versioned Nuvio self-host API.

Do not describe the programme as complete until an end-to-end client path passes the conformance suite.

## Review method

This plan was reviewed against:

- the official gstack sprint workflow;
- Floppy repository instructions;
- current Floppy issues;
- NuvioTV client behavior;
- Nuvio self-host behavior;
- OWASP Top 10:2025;
- OWASP API Security Top 10:2023;
- an adversarial red-team review;
- a defensive blue-team review;
- a frontier engineering panel;
- an ADHD/AuDHD panel;
- a synthetic 50-role streaming and tracking panel.

The panels are role-based reviews. They did not involve real named people.

## Gstack workflow

Use this sprint in the implementation worktree:

```text
Think
  /office-hours

Plan
  /autoplan
  /cso
  Codex Security threat model and scan

Build
  implement one approved PR boundary

Review
  /review
  Codex Security diff scan
  /codex review when available

Test
  targeted tests
  repository validation
  /qa
  accessibility checks

Ship
  /ship
  monitor CI
  verify the release candidate

Reflect
  /retro
  milestone post-mortem
```

`/autoplan` supplies the CEO, design, engineering, and developer-experience reviews. Re-run the engineering review only after a material plan change.

Production code must not start until:

- `/office-hours` is complete;
- `/autoplan` is complete;
- `/cso` is complete;
- the Codex Security threat model is complete;
- blocking findings are resolved;
- the engineering plan is a pass;
- the programme owner accepts the final plan.

The planning-doc PR can precede this gate because it changes no production behavior.

## Product vocabulary

Use one term for one concept.

| Term | Meaning |
|---|---|
| Saved item | An item the user intends to keep in a library or watchlist |
| Watchlist | A collection of saved screen-media items |
| Watched state | Whether an exact item or episode is completed |
| Progress | A resumable position and optional duration |
| History event | One durable consumption occurrence |
| Rewatch | A new history event for an item watched again |
| List | A Floppy-owned ordered set of items |
| Collection | A Nuvio layout with folders and source references |
| Add-on | A declarative remote HTTP capability; no code runs in Floppy |
| Plugin | Executable extension code |
| Connector | Internal code that translates one external protocol |
| Provider | A metadata or tracking source |
| Binding | An approved relation between one Floppy user and one external client/profile |
| Checkpoint | The last applied position in one resource and direction |
| Receipt | Durable proof of one accepted or rejected client operation |
| Tombstone | Durable proof of an explicit deletion |
| Projection | Normalized metadata derived from an external source |
| Override | An explicit user-owned metadata preference |

## Architecture boundary

Keep the current Floppy application.

```text
Nuvio / Stremio / Kodi / CrossWatch
                |
                v
Existing Floppy API and integration adapters
                |
                v
Small internal integration application boundary
                |
                v
Existing Floppy models and services
```

Share only behavior that must be identical across clients:

- client identity;
- scoped authorization;
- external media references;
- idempotency;
- delivery receipts;
- ordered changes;
- explicit deletes;
- cursor validation;
- checkpoint persistence;
- reconciliation results;
- safe outbound requests;
- cache provenance;
- stable public errors.

Keep source-specific behavior at each adapter:

- Stremio watched-bitfield parsing;
- Stremio `video_id` interpretation;
- Nuvio progress-key normalization;
- provider completion thresholds;
- provider rate limits;
- provider authentication;
- provider list semantics;
- provider metadata licensing;
- Nuvio Collection layout;
- executable plugin behavior.

Do not add:

- a universal provider state machine;
- direct Nuvio table access;
- a general plugin runtime;
- one class that owns every integration;
- one universal last-write-wins rule;
- a title/year fallback for authoritative writes;
- a cache-only event bus.

## Proposed durable records

Names are proposals. Reuse current records when they already satisfy the requirement.

### IntegrationClient

Stores stable external client identity and revocation state.

### ScopedAccessToken

Owned by #636.

Required behavior:

- show the secret once;
- store only a digest;
- compare in constant time;
- support explicit scopes;
- support expiry and revocation;
- update last-use state with bounded write frequency;
- keep the legacy account token during a measured migration period.

### SyncBinding

Binds one Floppy user to one external instance and profile.

It stores:

- client;
- external instance ID;
- external profile ID;
- approved capabilities;
- approved directions;
- status;
- created, updated, and disabled times.

A profile change requires explicit reapproval.

### SyncCheckpoint

Stores the last applied cursor for one binding, resource, and direction.

Advance it only after the page commits. Never store it only in cache.

### DeliveryReceipt

Makes mutating requests safe to retry.

```text
same binding + event ID + same digest -> prior result
same binding + event ID + changed digest -> conflict
new event ID -> new operation
```

Keep receipts for the documented retry guarantee. Compact them in bounded batches after expiry.

### ProgressChange

Exposes ordered progress upserts and deletes.

Use a server sequence. Do not order by client time. Keep `PlaybackProgress` as the current-state source.

### SavedItemChange and WatchedStateChange

Expose explicit additions, removals, watched upserts, and watched deletes.

Do not infer a delete from absence.

### UnresolvedExternalReference

Deduplicates unsupported or ambiguous IDs. It stores a reason code and occurrence count. It does not store a raw secret-bearing payload.

### SyncRun

Reuse or extend `ImportRun` only when its semantics fit.

Required result counts:

```text
created
updated
deleted
skipped
unresolved
failed
preserved_local
```

## Retention and compaction

### Receipts

- Keep them for at least the documented retry guarantee.
- Use a configurable retention period.
- Measure real retry intervals before fixing a default.
- Delete expired rows in bounded batches.
- Keep aggregate metrics after row deletion.

### Change logs

- Retain changes until every active checkpoint is beyond them.
- Require a new snapshot for a binding that remains inactive past the retention window.
- Compact below the safe watermark.
- Never compact an unapplied tombstone.
- Expose the oldest and newest retained sequence.
- Return a stable cursor-expired response.

### Unresolved items

- Deduplicate repeated unresolved references.
- Increment an occurrence count.
- Permit safe dismissal or manual resolution.
- Keep enough evidence to explain the problem without storing secrets.

## Cursor contract

Use an opaque cursor.

Bind it to:

- resource;
- user or binding;
- sequence;
- schema version;
- optional expiry.

Use either a signed cursor or a random server-backed cursor.

Rules:

- reject malformed cursors;
- reject a cursor for another binding or resource;
- return a stable expiry error;
- document snapshot recovery;
- commit a full page before advancing;
- order by server sequence;
- cap page size and limits.

## State and conflict rules

Use this safe default:

> Preserve local and user-authored state. Apply exact non-destructive changes. Skip and report ambiguity. Require explicit approval for destructive reconciliation.

### Progress

- A repeated event returns the prior result.
- A backward seek is valid only as an explicit progress event under the selected policy.
- An older event cannot silently undo completion.
- Progress does not create history by itself.

### Saved items

- Explicit add creates or preserves saved state.
- Explicit remove affects only the bound saved state.
- Absence from one page does not remove.
- An outage or partial snapshot does not remove.

### Watched state

- Exact movie and episode completion can synchronize.
- Stremio watched-bitfield evidence remains authoritative for Stremio episode completion.
- A current video is not proof of completion.
- External season completion must not invoke manual Floppy fan-out.

### History

- A retry is not a rewatch.
- A rewatch needs a distinct event identity and occurrence time.
- A lower-fidelity source does not replace a better existing date.
- Full rewatch-history parity is outside Release 1.0 unless the upstream contract proves it.

### Identity

- Accept exact verified IDs.
- Mark unsupported IDs unresolved.
- Mark conflicting verified IDs ambiguous.
- Never use title-only matching for a mutation.
- Preserve translation provenance.

### Delete

- Delete is explicit.
- Delete creates a tombstone or ordered delete event.
- An older upsert cannot resurrect a newer delete.
- Re-add needs a new explicit operation.

## API lifecycle

- Keep existing endpoints and shapes compatible.
- Add new behavior through optional fields, optional headers, or new endpoints.
- Publish the verified OpenAPI contract.
- Add contract fixtures.
- Document scopes and error codes.

Before legacy-token removal:

1. measure active use;
2. publish migration guidance;
3. show a user notice;
4. provide named-token creation;
5. permit parallel operation;
6. announce a removal release;
7. remove only after the compatibility period.

## Operational objectives

Measure these before release.

### Correctness

- No acknowledged mutation is lost.
- Replaying one request does not create a second mutation.
- Every explicit delete remains observable until active clients can apply it.
- Full reconciliation converges on supported state.
- No cross-user access is possible.

### Availability

- Provider or cache failure does not erase durable local state.
- User-requested work does not silently fail because Redis is unavailable.
- A failed page does not advance its checkpoint.
- A stale cursor has a snapshot recovery path.

### Performance and storage

Define and measure:

- page size;
- request and response size;
- JSON depth and member count;
- concurrent requests per binding and host;
- retry count;
- timeouts;
- reconciliation batch size;
- database query count;
- receipt and change-log growth.

Do not publish invented latency targets.

### Observability

Track:

- sync result counts;
- duplicate and conflicting receipt rates;
- cursor-expired rate;
- reconciliation drift;
- safe-fetch rejection reason;
- provider timeout and rate-limit count;
- cache hit, stale, and error counts;
- token use and revocation;
- event-log and receipt-table size;
- oldest active checkpoint.

Use low-cardinality labels. Do not use raw IDs or URLs as metric labels.

## Red-team and blue-team audit

This is a design audit. It does not claim that current code contains every listed weakness.

| Attack or failure | Required control | Verification |
|---|---|---|
| Cross-user or cross-profile access | User-scoped queries and approved binding | Two-user, multi-profile tests |
| Scope escalation | Endpoint scope map and explicit fields | Allowed and denied scope tests |
| Token theft or enumeration | Entropy, digest storage, constant-time compare, redaction | Secret and auth tests |
| Revocation race | Strict revocation check and cache invalidation | Revoke-under-load test |
| Replay and concurrent duplicates | Atomic receipt reservation and unique constraint | Timeout and concurrency tests |
| Event-ID reuse with changed payload | Payload digest and conflict response | Conflicting replay test |
| Out-of-order or clock-skewed events | Server sequence and stale-event rules | Reorder matrix |
| Tombstone resurrection | Sequence-aware tombstones | Delete-resurrection test |
| Delete by absence | Explicit delete only | Partial-page and empty-snapshot tests |
| Cursor tampering or cross-binding use | Opaque binding-bound cursor | Cursor abuse matrix |
| Cursor expiry | Stable expiry and snapshot recovery | Long-offline test |
| Oversized, compressed, or deep payload | Body, decoded-size, depth, count, time, rate limits | Boundary fixtures |
| Retry storm | Bounded backoff, jitter, circuit breaker | Fault injection |
| SSRF, rebinding, redirect bypass | Central safe-fetch boundary | Address and redirect matrix |
| Cloud metadata access | Block link-local metadata endpoints | Metadata endpoint tests |
| Credential forwarding | Per-request header allowlist | Capture-server test |
| Configured URL leakage | Encryption, masking, digest cache keys, query redaction | Log, UI, and cache tests |
| Cache poisoning or cross-user leak | Complete cache identity and private namespace | Isolation tests |
| Origin spoofing or infinite echo | Derive origin from credential; skip own-origin changes | Loop simulation |
| Partial transaction | Atomic state and receipt handling | Fault-injection test |
| DB lock amplification | Bounded batches and indexes | SQLite/Postgres load test |
| Migration collision | Audit, dry run, deterministic backfill | Upgrade matrix |
| Unbounded storage | Retention, watermark, compaction, metrics | Storage-growth test |
| Sensitive audit data | Minimal structured reason codes and access control | Log review |
| Remote code execution | Declarative add-ons only; reject plugins | Manifest tests |
| Supply-chain compromise | Lockfiles, pinned actions, CodeQL, dependency review | CI evidence |
| Backup and restore drift | Include new tables in restore drills | Restore test |
| Profile or account deletion | Disable binding and revoke credentials | Deletion tests |
| UI confusion and notification storm | Safe defaults, preview, grouped messages | Usability and large-error tests |

## OWASP review

The release must map controls and tests to OWASP Top 10:2025 and OWASP API Security Top 10:2023.

Required focus:

- access control and object authorization;
- secure configuration;
- dependency and action integrity;
- token and configured-URL protection;
- injection prevention;
- explicit security design;
- authentication lifecycle;
- data and manifest integrity;
- useful redacted logging and alerts;
- safe exceptional-condition handling;
- bounded resource use;
- SSRF prevention;
- versioned API inventory;
- strict validation of upstream APIs.

Do not claim absolute OWASP avoidance. Report the controls, tests, residual risk, and evidence.

## ADHD and AuDHD review

Use a three-step flow:

```text
1. Connect
2. Choose what to share
3. Review and start
```

Save progress between steps.

Use safe defaults:

```text
Progress        Two-way
Saved items     Two-way
Watched status  Two-way
Deletes         Explicit only
Conflicts       Preserve and report
Collections     Off
Add-ons         Off
Metadata        Off
Plugins         Never shared
```

Every important error uses:

```text
What happened
Data status
What you can do
Technical details
```

Acceptance criteria:

- no color-only state;
- one primary action per section;
- persistent important errors;
- grouped error counts;
- no per-item notification storm;
- clear labels;
- details collapsed by default;
- keyboard access and visible focus;
- focus stability after refresh;
- reduced motion;
- restrained live-region announcements;
- affected counts on destructive actions;
- explicit copy controls;
- no secrets in accessible names;
- resumable setup;
- dry-run preview before destructive reconciliation.

## Synthetic 50-role panel conclusion

The review covered Nuvio TV, mobile, desktop, web and TV-platform clients; Supabase/PostgREST, PostgreSQL, RLS, sync and profile engineering; Stremio, Trakt, SIMKL, CrossWatch, Kodi, Plex, Jellyfin, ListenBrainz and Last.fm integration roles; media identity, anime identity, metadata licensing and artwork; SQLite, PostgreSQL, Celery, Redis, SRE, performance, backup and release roles; API security, SSRF, secrets, supply chain, privacy, TV UX, ADHD/AuDHD, screen-reader and community-maintainer roles.

Panel consensus:

- keep Release 1.0 narrow;
- state authority explicitly;
- make retries and deletes predictable;
- never couple directly to Nuvio storage internals;
- provide preview and dry run;
- show cache freshness;
- publish a conformance kit;
- keep setup minimal;
- let future clients use stable public contracts without a Floppy source change.

## Release Train A

### Milestone A0 — Contract and safety baseline

#### PR A0 — Document this reviewed programme

Behavior change: none.

#### PR A1 — Harden malformed Stremio/Cinemeta input

Issue: #599

Deliver type validation, bounded logging, continuation, and regression fixtures.

Keep completed #619 and #723 behavior as baseline tests.

### Milestone A1 — Client security and delivery

#### PR A2 — Add scoped API credentials

Issue: #636

Deliver named tokens, scopes, digest storage, expiry, revocation, one-time display, legacy compatibility, OpenAPI scope documentation, and cross-user tests.

#### PR A3 — Add client identity, binding, and receipts

Deliver stable client identity, user/profile binding, optional idempotency, durable receipts, payload digests, replay handling, correlation IDs, retention, and cleanup.

### Milestone A2 — Ordered state

#### PR A4 — Add ordered progress changes

Relationships: #429 and #532

Deliver additive upsert/delete changes, server sequence, opaque cursor, page limits, snapshot recovery, and cursor expiry. Keep the current progress response compatible.

#### PR A5 — Add saved-item and watched-state changes

Issue: #532

Deliver explicit add/remove, exact watched changes, snapshots, tombstones, and no delete by absence. Split these resources if the reviewed diff becomes too large.

### Milestone A3 — Nuvio adoption package

#### PR A6 — Publish the Nuvio conformance kit

Relationships: #532, NuvioTV #2935, and NuvioTV #2484

Deliver capabilities, OpenAPI examples, request/response fixtures, retry and delete examples, origin rules, and a client implementation guide.

Do not claim upstream Nuvio adoption without an implementation.

### Milestone A4 — Reconciliation and diagnostics

#### PR A7 — Add dry-run reconciliation and diagnostics

Deliver dry run, categorized differences, safe apply, unresolved items, last success/error, grouped counts, a feature flag, a kill switch, accessibility support, and screenshots.

Default to preserve and report.

### Milestone A5 — Release 1.0 stabilization

#### PR A8 — Stabilize Tracking Interoperability 1.0

Run clean-install, upgrade, large-library, multi-device, multi-profile, offline, restart, timeout, revoked-token, replay, ordering, cursor-expiry, compaction, SQLite, PostgreSQL, performance, review, QA, ship, security, rollback, and post-mortem gates.

State which Nuvio client or bridge was tested end to end.

## Release Train B

Start after Train A is stable and its post-mortem is complete.

### PR B1 — Add read-only share grants

Relationships: #635 and #636

### PR B2 — Publish Floppy as a local Stremio-compatible add-on

Issue: #635

Publish selected catalogs and normalized metadata. Do not publish streams or mutation routes.

### PR B3 — Add safe fetch and cache transparency

Add network policy, limits, last-known-good behavior, provenance, freshness UI, and SSRF/cache-isolation tests.

### PR B4 — Add declarative add-on capability discovery

Add a manifest schema, version negotiation, declared media types, resources, permissions, configuration, validation, health, and conformance fixtures. Do not add executable plugin support.

### PR B5 — Add shared declarative installation records

Encrypt configured URLs. Keep per-application enabled state independent.

### PR B6 — Add portable Collection descriptors

Preserve folders, source references, order, ownership, unknown fields, preview, round trip, and safe unlink.

### PR B7 — Add optional writable list bindings

Use explicit operations, preview, confirmation, recovery, and conflict reporting.

### PR B8 — Add normalized metadata projections

Include exact identity, normalized fields, provenance, language, region, observation time, expiry, cache state, license and attribution.

### PR B9 — Add user metadata preferences and overrides

Keep user-owned fields separate from provider projections.

### PR B10 — Add Nuvio self-host pairing

Block this PR until Nuvio supplies supported external authorization, profile-bound scopes, a versioned API, OpenAPI, and stable change/delete semantics.

Never substitute direct database access.

## Issue graph

```text
#532 Nuvio programme
|
+-- #599 malformed Stremio input [open, independent]
+-- #636 scoped API credentials [open]
+-- #429 progress contract [relationship; verify state]
+-- #417 client API correctness [relationship; verify state]
+-- #635 read-only catalog publication [open, Train B]
+-- #598 import visibility [open, independent]
+-- #619 provider-prefixed IDs [completed baseline]
+-- #723 Stremio watched-state correctness [completed baseline]
`-- #652 architecture research [closed, never a blocker]
```

Search current issues before creating a new one. Use one issue for one testable behavior. Do not create one issue per compatible client.

## QA and release gates

### Per PR

Use the repository risk matrix.

For Python behavior:

- targeted tests;
- Ruff;
- relevant generated contracts;
- fast suite before finish;
- `/review`;
- Codex Security diff scan.

For models and migrations:

- migration hygiene;
- `makemigrations --check`;
- SQLite migration;
- PostgreSQL migration;
- upgrade replay;
- full relevant suite.

For UI:

- desktop screenshot;
- narrow screenshot;
- keyboard and focus evidence;
- loading, success, error and recovery states;
- reduced motion;
- screen-reader names;
- `/qa`.

For APIs:

- regenerate and validate OpenAPI;
- contract tests;
- scope tests;
- two-user tests;
- limit tests;
- error-code tests;
- backward-compatibility fixtures.

### Fault matrix

Test provider failure, Redis failure, worker failure, DB timeout before and after commit, duplicate and conflicting replay, out-of-order events, clock skew, cursor tampering and expiry, partial pages, empty snapshots, deleted profiles, revoked and expired credentials, wrong scope, large libraries, repeated unresolved IDs, upgrade, rollback, and compaction.

### QA finding policy

- Read every finding.
- Fix valid findings caused by the change.
- Add a regression test.
- Re-run affected checks.
- Re-run `/qa`.
- Record the result in the PR.
- Handle pre-existing test or lint failures under the baseline-zero policy.
- Keep a large unrelated repair in a separate commit or PR.

## Rollout and rollback

Use independent feature flags for each capability. Follow repository setting patterns.

Roll out through:

1. tests only;
2. local development;
3. shadow read;
4. dry-run reconciliation;
5. opt-in beta;
6. limited release;
7. default available;
8. default enabled only after evidence.

Rollback must stop new work, preserve acknowledged state, keep existing routes operational, disable background tasks, retain diagnostics, and avoid destructive down-migrations.

## PR and commit standard

Follow repository guidance and the existing PR template.

Each PR includes:

- Summary;
- AI Assistance;
- Validation;
- Contract Handoff;
- Human Review;
- Gstack QA;
- relevant issue relationships;
- screenshots for UI changes;
- migration and rollback details;
- security and accessibility evidence;
- post-mortem or post-implementation notes where applicable.

Use this AI disclosure:

```text
Generated and substantially shaped with ChatGPT (GPT-5.6 Pro).
Reviewed against current repository guidance and source evidence.
```

Do not include tokens, configured URLs, or private viewing data in screenshots.

## Stop conditions

Stop and request a decision for:

- a destructive migration;
- an existing API break;
- raw Nuvio password storage;
- service-role or direct database access;
- title-only authoritative matching;
- remote plugin execution;
- a new service or second database;
- material scope expansion;
- unresolved metadata license;
- conflict with maintainer direction;
- inability to test a high-risk change;
- a security finding that changes the approved design.

## GSTACK REVIEW REPORT

**Plan reviewed:** Floppy–Nuvio Integration Programme  
**Baseline:** `1bb6999a539679a27502c6514c3fdfec70f17091`  
**Manual source-based review date:** 2026-08-15

| Review | Status | Result |
|---|---|---|
| Office-hours equivalent | Complete | First wedge reduced to tracking interoperability |
| CEO/product equivalent | Complete | Two release trains; no all-at-once programme |
| Design equivalent | Complete | Three-step setup, progressive disclosure, clear states |
| Engineering equivalent | Complete | Added binding, checkpoints, receipts, retention, compaction and cursor rules |
| Developer-experience equivalent | Complete | Added OpenAPI, manifest schema, examples and conformance kit |
| Security design review | Complete | Added red/blue controls and OWASP mapping |
| ADHD/AuDHD review | Complete | Added safe defaults, grouped errors and resumable setup |
| 50-role panel | Complete as synthetic review | Consensus incorporated |
| Native `/office-hours` | Required in implementation worktree | Not run in this environment |
| Native `/autoplan` | Required in implementation worktree | Not run in this environment |
| Native `/cso` | Required in implementation worktree | Not run in this environment |
| Native `/review` | Required per code PR | Not applicable to this planning artifact |
| Native `/qa` | Required for integrated and UI behavior | Not run in this environment |
| Native `/ship` | Required before PR readiness | Not run in this environment |
| Native `/retro` | Required after each release | Not yet applicable |

**Plan status:** `PASS WITH EXECUTION GATES`

The planning-document PR can proceed now.

Production code must wait for the native plan and security gates in a runnable Floppy worktree.
