# Jellyfin Integration & Import Logic

Floppy talks to Jellyfin in four directions. This document covers the **import**
path (Jellyfin → Floppy); see `plex_integration.md` for the equivalent Plex flow,
which shares most of its machinery.

| Direction | Code | Purpose |
| --- | --- | --- |
| Import | `integrations/imports/jellyfin.py` | Backfill watched state, ratings, favorites and music |
| Webhook | `integrations/webhooks/jellyfin.py` | Real-time play/pause/stop and mark-played events |
| Push sync | `integrations/jellyfin_sync.py` | Write Floppy's watched state back to Jellyfin |
| REST client | `integrations/jellyfin_client.py` | Shared HTTP layer for all of the above |

## The central constraint: Jellyfin has no play-history API

Jellyfin stores only **per-item `UserData`** — `Played`, `PlayCount`,
`LastPlayedDate`, `Rating`, `IsFavorite`. There is no endpoint that returns "every
play, with a timestamp". That data exists only if the server admin has installed
the optional **Playback Reporting** plugin, which keeps a `PlaybackActivity` table.

The importer therefore runs in two layers:

1. **Baseline — library walk.** `/Users/{id}/Items` with
   `Fields=ProviderIds,UserData`, paged. Anything with `Played: true` becomes a
   record dated from `LastPlayedDate`.
2. **Enrichment — Playback Reporting.** `POST /user_usage_stats/submit_custom_query`
   against `PlaybackActivity`. When it answers, real play timestamps replace the
   single `LastPlayedDate`. When it does not, the run continues and appends a
   warning — a missing plugin is never an error.

The probe result is cached on `JellyfinAccount.playback_reporting_available`
(nullable: `null` = never probed) so the modal can explain the limitation before
the user starts a run.

> **Note on the plugin's response shape:** most releases misspell the column-list
> key as `colums`. `JellyfinClient.fetch_playback_activity` accepts both spellings.

### What the plugin does and does not buy you

Floppy models **one row per media item** — a `Movie` row, or a `TV`/`Season`/`Episode`
tree. Repeat watches do *not* become extra rows; this is existing behavior shared
with the Plex importer, not a Jellyfin limitation.

So the plugin's actual benefit is **date accuracy**, not extra rows. Records are
sorted ascending by `watched_at` and the first one wins, so:

- **With the plugin:** the entry is dated from the user's real *first* play.
- **Without it:** the entry is dated from `LastPlayedDate` — the most recent play.

The user-facing warning says exactly this. Do not describe the plugin as enabling
"full rewatch history"; it does not, and the model would have to change first.

## Identity resolution

Same rule as Plex: **TMDB IDs are canonical**. Jellyfin `ProviderIds` map as
`Tmdb → tmdb_id`, `Imdb → imdb_id`, `Tvdb → tvdb_id`, then resolution proceeds
through the shared `BaseWebhookProcessor` helpers.

**Episodes are the subtle case.** A Jellyfin `Episode` item carries *episode-level*
provider ids (e.g. the TVDB episode id), never the show's. Floppy matches shows on
the series-level id, so the importer:

1. indexes every `Series` item's `ProviderIds` by its `Id` during the walk,
2. defers episode processing until the walk finishes,
3. resolves each episode against `self._series_provider_ids[item["SeriesId"]]`.

`JellyfinPushSyncService._build_indexes` solves the same problem in the opposite
direction; the two are intentionally parallel.

## What gets imported

| Jellyfin state | Floppy result |
| --- | --- |
| `UserData.Played` on a Movie/Episode | `COMPLETED` entry dated per the rules above |
| `UserData.Rating` (0–10) | Score, via the shared `_normalize_rating` |
| `IsFavorite` **and not** `Played` | `PLANNING` entry |
| `IsFavorite` **and** `Played` | Stays `COMPLETED` — favorites never downgrade a watched item |
| `Audio` items with `Played` | `music_scrobble.MusicPlaybackEvent` → `record_music_playback` |

A rated-but-unwatched item must **never** become `COMPLETED`. The Plex importer
regressed on exactly this (ratings were harvested for every library item), so
`test_rating_on_unplayed_movie_does_not_mark_it_completed` guards it here.

### Music

Jellyfin music does **not** go through `JellyfinWebhookProcessor`: that class has no
`Audio` type mapping, and the base processor's music path expects Plex-shaped
payloads. Instead the importer builds `MusicPlaybackEvent` directly — that dataclass
is already source-agnostic.

MusicBrainz ids map as `MusicBrainzTrack`/`MusicBrainzRecording` →
`musicbrainz_recording`, `MusicBrainzAlbum` → `musicbrainz_release`,
`MusicBrainzReleaseGroup` → `musicbrainz_release_group`,
`MusicBrainzAlbumArtist`/`MusicBrainzArtist` → `musicbrainz_artist`.

Expect **lower matching precision than Plex music imports**: many Jellyfin libraries
have no MusicBrainz tags at all, in which case `_resolve_metadata` falls back to a
title search.

## Shared bulk stage

Everything after record collection lives in
`integrations/imports/media_server.py::MediaServerBulkImporter`, shared with Plex:
TMDB metadata warming, `Item`/`Movie`/`TV`/`Season`/`Episode` construction, anime
routing, TVDB↔TMDB numbering remaps, and overwrite-mode score preservation.

Subclasses supply:

- `self.processor` — a `BaseWebhookProcessor` for id resolution
- `SOURCE_KEY` / `SOURCE_LABEL` — dedupe-key slug and warning text
- `_build_anime_payload(record)` — a source-shaped payload for `_handle_anime`

Records use source-neutral keys: `source_season_number`, `source_episode_number`
and `rating_key` carry the media server's own numbering, which may differ from
TMDB's.

**Dedupe parity is deliberate.** Movies key on `(tmdb_id, watched_at-to-the-minute)`
and episodes on `(tmdb_id, season, episode, minute)`, identical to Plex. A user who
imports the same library from both Plex and Jellyfin must not end up with doubled
entries.

## Modes and scheduling

`new` and `overwrite` behave as they do everywhere else. In `overwrite`,
`_preserve_unresolvable_ids` keeps any row whose TMDB metadata failed to resolve —
the importer must never delete a row it cannot rebuild — and `_capture_existing_scores`
preserves scores Jellyfin cannot supply.

Recurring runs go through `helpers.create_import_schedule(source="Jellyfin")`,
creating a `PeriodicTask` bound to `Import from Jellyfin`. Both task names are
registered in `User.get_import_tasks()` so runs appear in the Import Activity panel.

## UI

Settings → Import Data hosts the tile and modal. Connection state and the library
list load through two async probes (`import_data_jellyfin_status`,
`import_data_jellyfin_libraries`) so a slow or unreachable server never blocks the
page render — the same pattern as Plex. The library list is cached on
`JellyfinAccount.libraries` with a TTL.

When no account exists the modal shows an inline connect form posting to
`jellyfin_connect` with `next=import_data`.

> **Dashboard API keys have no user context.** `/Users/Me` returns 4xx for them, so
> `get_current_user()` returns `None` and the user must supply an exact username for
> `find_user_by_name` to resolve. The connect form surfaces this.

## Testing

`integrations/tests/test_jellyfin_import.py` follows the house pattern: Django
`TestCase`, seams patched at their point of use, hand-written Jellyfin-shaped dicts
inline, assertions against real ORM rows.

Two fixture gotchas worth remembering:

- TV metadata uses **`season/{n}` keys**, not a `seasons` list. A `seasons` list
  silently yields `skipped_numbering_mismatch`.
- To simulate an unresolvable TMDB id, raise a 404 `ProviderAPIError`. Returning
  `None` from the mock caches the key and makes the id look resolvable, which
  defeats overwrite-preservation tests.
