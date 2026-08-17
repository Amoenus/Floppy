# Product Requirements Document (PRD) & Master Programme Plan
# Floppy–Nuvio Integration & Unified Declarative Add-on Platform

**Programme Title:** Floppy Master State Authority, Nuvio Sync & Unified Add-on Platform  
**Owner:** Ryan Winkler (Senior Product Manager)  
**Status:** 100% AUDITED, AUTOPLANNED & APPROVED  
**Target Repository:** `dannyvfilms/Floppy`  
**Integration Repositories:** `NuvioMedia/NuvioTV`, `NuvioMedia/self-host`  
**Integration Target & PR Policy:** **Single Pull Request (#791)** on branch `plan/nuvio-integration-reviewed-2026-08-15` targeting `latest`. All PR0–PR10 items are sequential work package commits within PR #791.

---

## 1. Executive Summary & Core Requirements

Floppy is the definitive self-hosted media tracker and state authority. This programme establishes Floppy as the **master state authority, scrobble coordinator, catalog publisher, and declarative add-on platform** for external streaming clients (Nuvio, Stremio, Kodi).

### Key Architectural Requirements
1. **Extensible & Provider-Agnostic Core**: Modular media identity and tracking core supporting IMDb, TMDB, TVDB, MAL, AniList, Kitsu, and future custom providers without modifying core view logic.
2. **Nuvio Interoperability**: Seamlessly interfaces with Nuvio TV and Nuvio Self-Host using public discovery (`<BACKEND_URL>/.well-known/nuvio`) while keeping Floppy's state isolated from Nuvio SQL internals.
3. **Advanced Granular Watched-State Actions (Exceeding Simkl)**:
   - **Mark Episode**: Single episode watch toggle.
   - **Mark Season**: Marks all episodes in a specified season as watched.
   - **Mark Previous Seasons**: Marks all episodes in seasons `1..N-1` as watched.
   - **Mark Previous Episodes in Season**: Marks episodes `1..E-1` in season `S` as watched.
   - **Mark All Directly**: Marks all seasons and episodes for a series as completed in a single atomic transaction.
4. **Master State Authority (Non-Competing)**: Floppy coordinates watch state, scrobbles, and resume positions. It does NOT compete as a video player. It provides native **"Play on {Player}"** deep links (`nuvio://`, `stremio://`, `kodi://`).
5. **Offline & Packaged-App First**: Core state transitions, scrobble queuing, and local media operations function 100% offline without hard dependencies on Docker, Redis, or Celery.
6. **Rigorous Performance Benchmarks**: Zero O(N²) scans or unindexed joins. Microsecond atomic database transactions. SQLite WAL mode enforcement.
7. **Standards & Cognitive Accessibility**: OpenAPI 3.2 (OAS 3.2), OpenAPI Overlays, AsyncAPI 3.0, JSON-LD, ASD-STE100 Simplified Technical English, AuDHD & ADHD friendly layouts, Nielsen's 10 Usability Heuristics, and Gestalt Visual Principles.

---

## 2. Ubiquitous Language (Domain-Driven Design)

| Domain Term | Strict Definition | Prohibited Usage |
|---|---|---|
| **PlaybackProgress** | Ephemeral, durable resume position (seconds, duration, completion bit) for a specific user and media item. | *Do not confuse with watch history.* |
| **History Play (Movie/Episode)** | Immutable historical record of a completed viewing event. | *Do not delete when progress resets.* |
| **IntegrationToken** | High-entropy scoped API credential storing only SHA-256 digests in the database. | *Never store raw token strings.* |
| **IntegrationEventReceipt** | Idempotency receipt storing `(token_id, client_event_id)` and SHA-256 payload digest. | *Never execute duplicate payloads twice.* |
| **PlaybackProgressChange** | Append-only event feed tracking upserts and explicit deletes with monotonic `sequence_id`. | *Never drop events or use wall timestamps.* |
| **SafeFetch** | Outbound HTTP client performing pre-connection DNS validation against SSRF / DNS rebinding. | *Never use raw `requests.get()` on untrusted URLs.* |
| **Declarative Add-on** | Pure JSON manifest HTTP endpoint (`kind: addon`). | *Strictly prohibit executing untrusted Python/JS.* |

---

## 3. Work Package Execution Sequence (PR0 – PR10 on #791)

```text
PR0: Evidence, Regression Baseline, and Conformance Protection
 ├── Planning fixtures & test harness (test_fork_nuvio_baseline.py)
 └── Invariant verification across existing scrobble & progress endpoints

PR1: Scoped Third-Party Credentials (#636)
 ├── IntegrationToken model with SHA-256 digest lookup
 └── Granular read/write scopes with legacy User.token backward compatibility

PR2: Authenticated Client Identity and Durable Idempotency
 ├── IntegrationEventReceipt model with payload SHA-256 digests
 └── Atomic deduplication interceptor returning cached responses / 409 conflicts

PR3: Ordered Playback-Progress Changes
 ├── PlaybackProgressChange append-only model with monotonic sequence_id
 └── AsyncAPI / GET /api/v1/playback/progress/changes?cursor=<base64> endpoint

PR4: Saved-Library / Watchlist Incremental State
 ├── Bidirectional watchlist sync (Planning status mapping)
 └── Explicit delete enforcement (missing page items never trigger mass deletes)

PR5: Exact Watched State (#723, #599, #619) & Granular Batch Marking & Nuvio Conformance (#532)
 ├── Bitfield-accurate season/episode completion without false fan-out
 ├── Granular Batch Marking: Mark Season, Previous Seasons, Previous Episodes, Mark All
 ├── Defensive Stremio/Cinemeta payload parser (skips malformed video entries)
 ├── Centralized MediaIdentityService (provider-prefixed ID normalizer)
 └── Complete OAS 3.2 & AsyncAPI conformance test suite

PR6: Reconciliation, Diagnostics, and Recovery UI
 ├── Dry-run reconciliation engine for out-of-sync libraries
 └── Accessible connection diagnostics UI (last sync, error counters, receipt IDs)

PR7: Offline Behavior, Packaged-Runtime Compatibility, and Release 1.0 Stabilization
 ├── Decoupled sync transition engine callable without Celery/Redis
 ├── Local SQLite WAL concurrency hardening & memory safety
 └── Full test matrix: clean install, migration replay, SQLite/PostgreSQL parity

PR8: Read-Only Floppy Stremio / Nuvio Catalog Surface (#635)
 ├── Stremio Addon Protocol manifest.json, /catalog, /meta endpoints
 └── Standardized "Play on {Player}" deep link templates (nuvio://, stremio://)

PR9: Safe Remote Fetch, Transparent Caching, and Read-Only Metadata Projection
 ├── SafeFetch socket-level pre-DNS gateway (SSRF/DNS rebinding defense)
 ├── Freshness budgets & negative caching policy
 └── JSON-LD semantic annotations on media detail projections

PR10: Local Shared Media Workspace Primitives
 ├── Typed, foldered declarative Add-on manifest management
 └── Validated workspace overrides (artwork, titles, localized overviews)
```

---

## 4. Performance & Concurrency Invariants

1. **Microsecond Database Transactions**: `transaction.atomic()` spans only database row writes (`PlaybackProgress`, `PlaybackProgressChange`, `IntegrationEventReceipt`). All external network lookups and provider calls execute strictly outside the transaction.
2. **SQLite WAL Mode**: Forces `journal_mode=WAL` with busy timeouts to eliminate `database is locked` contention during multi-client scrobble bursts.
3. **No Unbounded Queries**: All change feeds and list endpoints enforce `limit <= 100` and use composite indexes on `(user_id, sequence_id)` and `(token_id, client_event_id)`.
4. **Offline Resilience**: Offline queues buffer events locally in SQLite; reconnects replay changes idempotently without duplicates.

---

## 5. Verification Plan

```bash
# 1. Targeted Unit & Integration Tests
scripts/test.sh api.tests.test_fork_playback_progress
scripts/test.sh api.tests.test_fork_scrobble
scripts/test.sh api.tests.test_fork_nuvio_baseline
scripts/test.sh integrations.tests

# 2. Code Style & Ruff Checks
uv run --no-sync ruff check src

# 3. Migration Hygiene & Graph Checks
uv run --no-sync python src/manage.py check_migration_hygiene --strict

# 4. Fast Test Suite
scripts/test.sh
```
