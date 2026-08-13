# Metadata & provider tokens: current architecture inventory

This inventory is the reviewed starting point for moving instance provider
credentials into Settings. It describes current code only. It does not define a
model, resolver implementation, form, or migration.

## Reviewed base

| Item | Reviewed value |
|---|---|
| Earlier planning baseline | `80844026` |
| Current base | `de20dd2e` (`origin/latest` when reviewed) |
| Delta | 22 commits |

The credential declarations and their defaults did not change in that delta.
The relevant changes were:

- PR #729 added boosted-navigation feedback in `src/templates/base.html`.
  `src/users/urls.py`, `src/users/views.py`, `src/templates/users/base.html`, and
  `src/templates/users/integrations.html` remained byte-unchanged.
- PR #730 added API/MCP progress fields and IGDB search output. It changed an
  IGDB search cache version, but not IGDB credential loading.
- PR #735 separated Redis roles: the Django cache uses `REDIS_CACHE_URL`, the
  Celery broker and result backend can use their own URLs, and `REDIS_URL`
  remains the fallback.
- PR #737 and its stack added configurable data paths and hardened generated
  `SECRET` handling. The provider `secret()` helper and provider declarations
  were not changed.

## Credential declarations and precedence

All declarations are in `src/config/settings.py`. A relative `_FILE` value is
read below `/run/secrets`; an absolute value is read directly. File contents are
stripped. Last.fm is the only family below without a `_FILE` input.

| Family | Django setting / primary environment | File environment | Built-in fallback |
|---|---|---|---|
| TMDB | `TMDB_API` | `TMDB_API_FILE` | non-empty shared key |
| TVDB | `TVDB_API_KEY` | `TVDB_API_KEY_FILE` | empty |
| TVDB | `TVDB_PIN` | `TVDB_PIN_FILE` | empty |
| MyAnimeList | `MAL_API` | `MAL_API_FILE` | non-empty shared client ID |
| IGDB | `IGDB_ID` | `IGDB_ID_FILE` | non-empty shared client ID |
| IGDB | `IGDB_SECRET` | `IGDB_SECRET_FILE` | non-empty shared client secret |
| Steam | `STEAM_API_KEY` | `STEAM_API_KEY_FILE` | empty |
| BoardGameGeek | `BGG_API_TOKEN` | `BGG_API_TOKEN_FILE` | non-empty shared token |
| Hardcover | `HARDCOVER_API` | `HARDCOVER_API_FILE` | non-empty shared `Bearer` token |
| Comic Vine | `COMICVINE_API` | `COMICVINE_API_FILE` | non-empty shared key |
| Last.fm | `LASTFM_API_KEY` | none | empty |
| Trakt | `TRAKT_API` | `TRAKT_API_FILE` | empty |
| Trakt | `TRAKT_API_SECRET` | `TRAKT_API_SECRET_FILE` | empty |
| AniList | `ANILIST_ID` | `ANILIST_ID_FILE` | empty |
| AniList | `ANILIST_SECRET` | `ANILIST_SECRET_FILE` | empty |
| SIMKL | `SIMKL_ID` | `SIMKL_ID_FILE` | non-empty shared client ID |
| SIMKL | `SIMKL_SECRET` | `SIMKL_SECRET_FILE` | non-empty shared client secret |

The current value order is explicit primary environment, `_FILE` contents, then
built-in fallback. The expression is `config(PRIMARY,
default=secret(FILE, fallback))`. Python evaluates `secret(...)` before calling
`config(...)`, so a configured primary value does **not** protect startup from
a configured but unreadable `_FILE`; the file read can raise first.

The future value order is **explicit environment -> `_FILE` -> app-managed ->
built-in/default**. Compatibility also requires preserving the current eager
startup failure exactly: initialization must read and validate a configured
`_FILE` even when an explicit environment value will win value resolution.

## Direct consumers

These are the production Python files found by the direct settings-read scan at
`de20dd2e`. The separate operation-boundary map below records verified indirect
paths by category; it is not presented as a complete static call graph.

| Family | Direct settings consumers |
|---|---|
| TMDB | `src/app/providers/tmdb.py`; `src/app/discover/providers/tmdb_adapter.py`; `src/app/management/commands/backfill_discover_metadata.py` |
| TVDB | `src/app/providers/tvdb.py`; `src/app/services/metadata_resolution.py` |
| MyAnimeList | `src/app/providers/mal.py`; `src/app/discover/provider_candidates.py`; `src/integrations/imports/mal.py` |
| IGDB | `src/app/providers/igdb.py`; `src/app/discover/provider_candidates.py`; `src/app/services/game_lengths.py`; `src/lists/models.py` |
| Steam | `src/integrations/imports/steam.py` |
| BoardGameGeek | `src/app/providers/bgg.py`; `src/app/discover/provider_candidates.py` |
| Hardcover | `src/app/providers/hardcover.py` |
| Comic Vine | `src/app/providers/comicvine.py`; `src/app/discover/provider_candidates.py` |
| Last.fm | `src/integrations/lastfm_api.py`; `src/app/discover/provider_candidates.py` |
| Trakt | `src/app/providers/trakt.py`; `src/app/discover/providers/trakt_adapter.py`; `src/integrations/imports/trakt.py`; `src/integrations/views.py`; `src/lists/imports/trakt.py`; `src/users/views.py`; `src/users/onboarding_views.py` |
| AniList | `src/integrations/imports/anilist.py`; `src/integrations/views.py` |
| SIMKL | `src/integrations/imports/simkl.py`; `src/integrations/views.py` |

`src/config/test_settings.py` supplies test-only Steam and Trakt overrides; it
is not a production source.

### Module-scope capture

`src/app/discover/providers/tmdb_adapter.py` builds `TMDB_BASE_PARAMS` at module
import with `settings.TMDB_API` and `settings.TMDB_LANG`. Every other direct
credential read above occurs inside a function, method, or instance
initializer. A runtime-editable credential cannot take effect in that TMDB
adapter until this module-scope capture is removed or rebuilt.

### Verified indirect operation boundaries

This category map records the contexts that must be exercised when consumers
move to the resolver. It names concrete verified edges without claiming that
every possible dynamic provider call is statically enumerable.

| Context | Verified indirect consumers and behavior |
|---|---|
| Interactive routing | `src/app/providers/services.py` dispatches search and metadata work to TMDB, TVDB, MAL, IGDB, BGG, Hardcover, and Comic Vine. `src/app/services/metadata_resolution.py` filters TVDB availability. Verified callers include `src/app/search_views.py`, metadata/detail/people views, `src/api/views.py`, `src/lists/views_recommendations.py`, and `src/lists/views_add_reorder.py`. |
| Discover and statistics | `src/app/discover/provider_candidates.py` and the TMDB/Trakt adapters fetch credentialed rows. `src/app/statistics_views.py` calls `tvdb.enabled()` for its page contexts. |
| TVDB background work | `src/app/tasks_genre.py` gates genre backfill on `tvdb.enabled()` and calls TVDB lookup/genre helpers. `src/app/tasks_metadata_cache.py` derives TVDB metadata cache keys. `src/app/tasks_tv_provider_migration.py` and `src/app/services/tv_provider_migration.py` gate and fetch TVDB migration data. |
| Other background work | `src/app/tasks_trakt.py` calls the Trakt provider for popularity and episode ratings. `src/app/tasks_providers.py`, `src/app/tasks_episode.py`, and `src/app/tasks_metadata_cache.py` fetch through provider services. Calendar modules under `src/events/calendar/` use provider services and direct TMDB, TVDB, MAL, and Comic Vine modules. Last.fm tasks in `src/integrations/tasks/_lastfm.py` call `src/integrations/lastfm_api.py`. |
| OAuth and imports | Trakt, AniList, and SIMKL redirects in `src/integrations/views.py` use instance client IDs; matching modules under `src/integrations/imports/` exchange tokens with instance secrets. MAL, Steam, Trakt, AniList, and SIMKL Celery entry points in `src/integrations/tasks/_media_imports.py` call their importers. Plex, SIMKL, and Trakt importers also call TVDB where source mapping requires it. |
| Webhooks and API ingestion | `src/integrations/webhooks/base.py` uses TVDB for anime/source resolution. `src/integrations/webhooks/plex.py`, `src/integrations/webhooks/stremio.py`, `src/api/fork_views_playback.py`, and `src/api/fork_views_scrobble.py` call TMDB directly or through provider services. |
| Cache and migration operations | `src/app/metadata_sync_views.py` derives TVDB invalidation keys. `src/app/management/commands/merge_duplicate_provider_items.py` checks TVDB availability before provider-item work. |
| Management backfills | `backfill_discover_metadata` reads TMDB directly. `backfill_trakt_popularity` calls the Trakt provider, which reads the instance Trakt client ID. |

Configuration inference is also observable UI behavior:

- `src/users/views.py` computes `tvdb_enabled` through metadata resolution for
  `src/templates/users/preferences.html`.
- `src/app/statistics_views.py` computes `tvdb_enabled` through
  `tvdb.enabled()` for `src/templates/app/statistics.html`.
- `src/users/views.py` and `src/users/onboarding_views.py` compute
  `trakt_configured` from the instance Trakt pair for
  `src/templates/users/import_data.html` and
  `src/templates/users/onboarding/components/connect_trakt.html`.
- `src/lists/views_list_browse.py` computes `trakt_has_credentials` from the
  per-user `TraktAccount` for `src/templates/lists/custom_lists.html`. This is
  the per-user exception below, not instance resolver state.

### Existing per-user Trakt exception

`src/integrations/models.py::TraktAccount` already stores an encrypted Trakt
client ID and secret per user for custom-list imports. The write/OAuth path is
`src/lists/views_trakt.py`; decryption is centralized in
`src/lists/views_helpers.py::_get_trakt_credentials`; the resulting client ID
is passed to `src/lists/tasks.py` and `src/lists/imports/trakt.py`.

This is separate from the instance `TRAKT_API` / `TRAKT_API_SECRET` used by
private-profile imports and provider metadata. A future instance resolver must
not replace, migrate, or reinterpret `TraktAccount` ciphertext.

## Cache and token invalidation boundaries

Current behavior uses static bearer-token keys:

- IGDB caches its client-credentials bearer token under
  `igdb_access_token`. It deletes that key after an unauthorized response and
  otherwise retains it until the provider-reported expiry minus 60 seconds.
- TVDB caches its bearer token under `tvdb_v4_access_token` for 12 hours. It
  deletes that key on an unauthorized response before one retry. TVDB metadata
  uses separate `tvdb_v4_*` keys.
- TMDB discovery captures the API key at module import as described above.
- Other provider response caches are not credential stores. Changing a
  credential should not imply a global cache clear.

Since PR #735, these static keys live in Django's default cache at
`REDIS_CACHE_URL` (falling back to `REDIS_URL`). Celery queue state uses
`CELERY_BROKER_URL`, and Celery results use `CELERY_RESULT_BACKEND`, each
falling back to `REDIS_URL`. Cache, broker, and result storage cannot be assumed
to share a URL.

Future IGDB and TVDB bearer caches must be namespaced by the resolver's
`configuration_version`; the current static key names are not the future
contract. A successful credential change captures the old
`configuration_version`, commits the new configuration, invalidates only the
old version's affected bearer-token namespace, and invalidates non-secret
resolver state across workers so they observe the new version. It must never
globally clear Django's cache or flush Redis.

## Current Settings boundary

- `django.contrib.auth.middleware.LoginRequiredMiddleware` protects Settings.
  The existing Settings views have no staff or superuser requirement.
- Provider credentials are currently instance-wide process configuration and
  are not writable through Settings. There is therefore no current
  application-level permission for changing them.
- Preferences rejects writes by demo users. The Integrations page and several
  of its POST endpoints do not establish an instance-administration boundary.
  A credential editor must define and test its own narrow permission instead
  of treating ordinary Settings access as authority over shared secrets.

## Settings and Integrations compatibility constraints

The reviewed domain label is **Metadata & provider tokens**.

- Keep `/settings/integrations`, URL name `integrations`,
  `users.views.integrations`, and `users/integrations.html` unchanged.
- Keep the Integrations page's API token, media-server/webhook content, copy,
  forms, and POST destinations. Preserve `?onboarding=...` and the
  `?open=<integration>` deep-link filter. Preserve redirects to `integrations`,
  submitted `next`, and the existing `/settings/integrations` referer fallback.
- Metadata language, watch-provider region, and TV/anime metadata-source
  defaults remain user Preferences. They are not instance credentials.
- `src/templates/users/base.html` marks items active by exact path. A new route
  needs its own exact-path entry.
- The shared Settings link in `src/templates/base.html` currently recognizes
  Account, Notifications, Sidebar/UI, Preferences, Home Screen, Integrations,
  Import, and Export. It does not include RSS, Advanced, or About. Add the new
  page deliberately; do not use this omission to relabel or fold existing
  pages together.
- Boosted navigation from PR #729 is part of the current shared shell and must
  continue to receive a full visible page response.

## Documentation and generated surfaces for later work

| Surface | Current state / later obligation |
|---|---|
| `AGENTS.md` | Only AGENTS file in the checkout; update repository map, validation, and Settings rules when implementation exists. No nested `AGENTS.md` was found. |
| `CLAUDE.md` | None was found. Do not add one only for this feature. |
| `CONTRIBUTING.md` | Contributor validation and UI screenshot rules apply; add a feature-specific rule only if implementation needs one. |
| `README.md` | Current operator credential list, `_FILE` examples, and Trakt OAuth guide must describe the final precedence and UI without removing environment compatibility. |
| `mcp_server/README.md` | Currently documents user `manage_settings` and the API token location. Update only if the MCP contract or token location changes. |
| `src/api/schema.py`, `src/api/serializers.py`, `src/api/views.py`, `src/config/urls.py` | OpenAPI is generated at `/api/schema/`; there is no checked-in generated schema file. Update source annotations only if a credential API is intentionally exposed. |
| `docs/agents/metadata-backfill.md`, `docs/agents/media_type_integration.md`, `docs/agents/lastfm_integration.md` | Provider/backfill guidance must use the resolver once it exists. |
| `docs/agents/dev_release_diff_report.md` | Temporary release/wiki staging document contains provider configuration references; reconcile it only if it remains active when the feature lands. |
| Project wiki | The local `wiki/` checkout is empty here. The README links external configuration and API pages; update the separate wiki repository during release work. |

## Future contract

Implement one provider-credential resolver used by every consumer in this
inventory. It must:

1. resolve values in this order: explicit environment, `_FILE`, app-managed,
   built-in/default;
2. preserve the eager configured-`_FILE` startup read/failure, environment
   names, `_FILE` path behavior, and built-in fallbacks;
3. allow direct credential access only during `src/config/settings.py`
   initialization and inside resolver internals. There are no current
   operator-only runtime consumer exceptions. Any future operator-only
   exception must be named by exact module, symbol, and setting in this
   document and in the direct-access contract test before it is allowed;
4. move every current runtime direct read behind the resolver and remove
   module-scope credential capture;
5. use `configuration_version`-namespaced IGDB/TVDB bearer caches, invalidate
   the captured old version's affected namespace, and invalidate non-secret
   resolver state across workers without a global cache clear; and
6. leave existing ciphertext and persisted data unchanged, including
   `TraktAccount` and encrypted OAuth/task values. No data rewrite is part of
   this contract.
