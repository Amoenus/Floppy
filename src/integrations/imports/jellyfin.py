"""Jellyfin library importer.

Jellyfin has no native play-history API: the server stores only per-item
``UserData`` (``Played``, ``PlayCount``, ``LastPlayedDate``). Real per-play
history exists only when the optional Playback Reporting plugin is installed.
So this importer walks the library as its baseline and enriches with plugin
rows when the plugin answers, falling back to a single ``LastPlayedDate``
entry per item otherwise.
"""

import logging
from datetime import UTC, datetime

from django.utils import timezone

import app
from app.log_safety import exception_summary
from app.models import MediaTypes, Sources, Status
from app.services import music_scrobble
from integrations.imports import helpers
from integrations.imports.helpers import MediaImportError, decrypt_or_raise
from integrations.imports.media_server import MediaServerBulkImporter
from integrations.jellyfin_client import (
    JellyfinAuthError,
    JellyfinClient,
    JellyfinClientError,
)
from integrations.models import JellyfinAccount
from integrations.webhooks.jellyfin import JellyfinWebhookProcessor

logger = logging.getLogger(__name__)

WATCHED_FIELDS = "ProviderIds,UserData"
MUSIC_FIELDS = "ProviderIds,UserData"
TICKS_PER_MS = 10_000

_MUSICBRAINZ_PROVIDER_MAP = {
    "MusicBrainzTrack": "musicbrainz_recording",
    "MusicBrainzRecording": "musicbrainz_recording",
    "MusicBrainzAlbum": "musicbrainz_release",
    "MusicBrainzReleaseGroup": "musicbrainz_release_group",
    "MusicBrainzAlbumArtist": "musicbrainz_artist",
    "MusicBrainzArtist": "musicbrainz_artist",
}


def importer(library, user, mode):
    """Import Jellyfin watch/listen state for the user."""
    return JellyfinImporter(user=user, mode=mode, library=library).import_data()


def _parse_jellyfin_date(value) -> datetime | None:
    """Parse a Jellyfin ISO-8601 timestamp into an aware datetime."""
    if not value:
        return None
    text = str(value).strip()
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    # Jellyfin emits 7-digit fractional seconds; Python accepts at most 6.
    if "." in text:
        head, _, tail = text.partition(".")
        digits = ""
        rest = ""
        for index, char in enumerate(tail):
            if char.isdigit():
                digits += char
            else:
                rest = tail[index:]
                break
        text = f"{head}.{digits[:6]}{rest}" if digits else f"{head}{rest}"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if timezone.is_naive(parsed):
        parsed = timezone.make_aware(parsed, UTC)
    return parsed


def _first_artist(jf_item: dict) -> str | None:
    """Return the first credited artist name, if Jellyfin supplied any."""
    artists = jf_item.get("Artists") or []
    return artists[0] if artists else None


class JellyfinImporter(MediaServerBulkImporter):
    """Import watched state, ratings, favorites and music from Jellyfin."""

    SOURCE_KEY = "jellyfin"
    SOURCE_LABEL = "Jellyfin"

    def __init__(self, user, mode, library, fast_mode=True):
        """Resolve the Jellyfin account and prepare the shared bulk state."""
        self._init_bulk_state(user, mode, fast_mode=fast_mode)
        self.library = library or "all"
        self.processor = JellyfinWebhookProcessor()

        try:
            self.account = user.jellyfin_account
        except JellyfinAccount.DoesNotExist as error:
            msg = "Connect Jellyfin before importing"
            raise MediaImportError(msg) from error

        try:
            self._api_key = decrypt_or_raise(self.account.api_key)
        except MediaImportError as error:
            self.account.connection_broken = True
            self.account.last_error_message = str(error)
            self.account.save(
                update_fields=["connection_broken", "last_error_message", "updated_at"],
            )
            raise

        self.client = JellyfinClient(
            self.account.base_url,
            self._api_key,
            self.account.jellyfin_user_id or None,
        )
        # Jellyfin item id -> parsed play timestamps from Playback Reporting.
        self._play_times: dict[str, list[datetime]] = {}
        self._series_provider_ids: dict[str, dict] = {}
        self._favorite_records: list[dict] = []

    # -- entry point ----------------------------------------------------

    def import_data(self):
        """Walk the Jellyfin library and bulk-create the resulting media."""
        self._ensure_user_id()
        self._load_playback_activity()

        parent_ids = self._get_target_parent_ids()
        self._collect_library(parent_ids)
        self._collect_music(parent_ids)

        if self.mode == "new":
            self._build_existing_dedupe_sets()

        logger.info("Warming TV metadata cache...")
        self._warm_tv_metadata_cache()

        if self.mode == "overwrite":
            self._pre_warm_movie_metadata()
            self._preserve_unresolvable_ids()
            self._capture_existing_scores()
            helpers.cleanup_existing_media(self.to_delete, self.user)

        logger.info("Building bulk media instances...")
        self._build_bulk_media()
        self._build_favorite_media()
        logger.info("Finalizing bulk creation...")
        helpers.bulk_create_media(self.bulk_media, self.user)

        self.account.last_sync_at = timezone.now()
        self.account.connection_broken = False
        self.account.save(
            update_fields=["last_sync_at", "connection_broken", "updated_at"],
        )

        return self._build_result()

    def _build_result(self):
        """Assemble the counts and warning text the task layer reports."""
        result_counts = {
            media_type: len(media_list)
            for media_type, media_list in self.bulk_media.items()
        }
        if MediaTypes.MUSIC.value in self.counts:
            result_counts[MediaTypes.MUSIC.value] = self.counts[MediaTypes.MUSIC.value]
            result_counts["music_unique_tracks"] = len(self._unique_music_tracks)

        result_counts.update(self.summary_counts)
        deduped_warnings = "\n".join(dict.fromkeys(self.warnings))
        return result_counts, deduped_warnings

    def _preserve_unresolvable_ids(self):
        """Keep rows whose TMDB metadata could not be resolved in overwrite mode."""
        unresolvable_tv = self._tv_ids - set(self._tv_metadata_cache.keys())
        if unresolvable_tv:
            logger.warning(
                "Preserving %d TV show(s) — TMDB metadata unavailable",
                len(unresolvable_tv),
            )
            for source_ids in self.to_delete.get(MediaTypes.TV.value, {}).values():
                source_ids.difference_update(unresolvable_tv)

        unresolvable_movies = self._movie_ids - set(self._movie_metadata_cache.keys())
        if unresolvable_movies:
            logger.warning(
                "Preserving %d movie(s) — TMDB metadata unavailable",
                len(unresolvable_movies),
            )
            for source_ids in self.to_delete.get(MediaTypes.MOVIE.value, {}).values():
                source_ids.difference_update(unresolvable_movies)

    # -- connection -----------------------------------------------------

    def _ensure_user_id(self):
        """Resolve and persist the Jellyfin user id when it is not cached."""
        if self.account.jellyfin_user_id:
            return

        try:
            current_user = self.client.get_current_user()
        except (JellyfinAuthError, JellyfinClientError) as exc:
            msg = f"Could not connect to Jellyfin: {exc}"
            raise MediaImportError(msg) from exc

        if not current_user or not current_user.get("Id"):
            msg = "Could not resolve a Jellyfin user for this API key."
            raise MediaImportError(msg)

        self.client.user_id = current_user["Id"]
        self.account.jellyfin_user_id = current_user["Id"]
        self.account.jellyfin_username = current_user.get("Name", "")
        self.account.save(
            update_fields=["jellyfin_user_id", "jellyfin_username", "updated_at"],
        )

    def _get_target_parent_ids(self) -> list[str | None]:
        """Return the library ids to walk, or [None] for the whole server."""
        if not self.library or self.library == "all":
            return [None]
        return [self.library]

    # -- playback reporting ---------------------------------------------

    def _load_playback_activity(self):
        """Load real per-play timestamps from the Playback Reporting plugin."""
        try:
            rows = self.client.fetch_playback_activity()
        except (JellyfinAuthError, JellyfinClientError) as exc:
            logger.info(
                "Playback Reporting probe failed: %s",
                exception_summary(exc),
            )
            rows = None

        available = rows is not None
        self.account.playback_reporting_available = available
        self.account.playback_reporting_checked_at = timezone.now()
        self.account.save(
            update_fields=[
                "playback_reporting_available",
                "playback_reporting_checked_at",
                "updated_at",
            ],
        )

        if not available:
            self.warnings.append(
                "Jellyfin's Playback Reporting plugin was not available, so each "
                "item was dated from its last-played date rather than its real "
                "first-watch date. Install the plugin for accurate watch dates.",
            )
            return

        for row in rows:
            item_id = str(row.get("ItemId") or "").strip()
            played_at = _parse_jellyfin_date(row.get("DateCreated"))
            if not item_id or not played_at:
                continue
            self._play_times.setdefault(item_id, []).append(played_at)

        logger.info(
            "Playback Reporting supplied %d play rows across %d items",
            sum(len(v) for v in self._play_times.values()),
            len(self._play_times),
        )

    def _watch_times(self, jf_item: dict) -> list[datetime]:
        """Return every timestamp this item should be imported at."""
        item_id = str(jf_item.get("Id") or "").strip()
        plugin_times = self._play_times.get(item_id)
        if plugin_times:
            return sorted(plugin_times)

        user_data = jf_item.get("UserData") or {}
        last_played = _parse_jellyfin_date(user_data.get("LastPlayedDate"))
        if last_played:
            return [last_played]
        return [timezone.now().replace(second=0, microsecond=0)]

    # -- library walk ---------------------------------------------------

    def _collect_library(self, parent_ids):
        """Walk movies, series and episodes, recording watched state."""
        episodes: list[dict] = []

        for parent_id in parent_ids:
            try:
                for jf_item in self.client.iter_library_items(
                    fields=WATCHED_FIELDS,
                    parent_id=parent_id,
                ):
                    item_type = jf_item.get("Type")
                    if item_type == "Series":
                        series_id = jf_item.get("Id")
                        if series_id:
                            self._series_provider_ids[series_id] = (
                                jf_item.get("ProviderIds") or {}
                            )
                        self._process_series(jf_item)
                    elif item_type == "Movie":
                        self._process_movie(jf_item)
                    elif item_type == "Episode":
                        episodes.append(jf_item)
            except (JellyfinAuthError, JellyfinClientError) as exc:
                msg = f"Could not read Jellyfin library: {exc}"
                raise MediaImportError(msg) from exc

        # Episodes are processed after the walk so every parent Series has
        # been indexed: Jellyfin episodes carry episode-level provider ids,
        # while Floppy matches shows on the series-level id.
        for jf_item in episodes:
            self._process_episode(jf_item)

    def _external_ids(self, provider_ids: dict) -> dict:
        """Map Jellyfin ProviderIds onto Floppy's external id names."""
        return {
            "tmdb_id": provider_ids.get("Tmdb"),
            "imdb_id": provider_ids.get("Imdb"),
            "tvdb_id": provider_ids.get("Tvdb"),
        }

    def _process_movie(self, jf_item: dict):
        """Record a watched movie, its rating and its favorite state."""
        user_data = jf_item.get("UserData") or {}
        title = jf_item.get("Name")
        ids = self._external_ids(jf_item.get("ProviderIds") or {})

        tmdb_id = self._resolve_movie_tmdb_id(ids)
        if not tmdb_id:
            self._record_missing_metadata(title, "missing TMDB/IMDB ID")
            return

        rating = self._normalize_rating(user_data.get("Rating"), title)
        if rating is not None:
            self._library_ratings[(Sources.TMDB.value, tmdb_id)] = rating

        if not user_data.get("Played"):
            if user_data.get("IsFavorite"):
                self._favorite_records.append(
                    {
                        "media_type": MediaTypes.MOVIE.value,
                        "tmdb_id": tmdb_id,
                        "title": title,
                    },
                )
            return

        if not self._should_process_media(MediaTypes.MOVIE.value, tmdb_id):
            self.summary_counts["skipped_existing"] += 1
            return

        for watched_at in self._watch_times(jf_item):
            self._movie_records.append(
                {
                    "tmdb_id": tmdb_id,
                    "imdb_id": ids.get("imdb_id"),
                    "watched_at": watched_at,
                    "rating": rating,
                    "title": title,
                },
            )
        self._movie_ids.add(tmdb_id)

    def _process_series(self, jf_item: dict):
        """Record a show-level rating and any unplayed favorite show."""
        user_data = jf_item.get("UserData") or {}
        title = jf_item.get("Name")
        show_ids = self._external_ids(jf_item.get("ProviderIds") or {})

        media_id, _, _ = self.processor._find_tv_media_id(
            show_ids,
            series_title=title,
            allow_title_fallback=False,
        )
        if not media_id:
            return
        media_id = str(media_id)

        rating = self._normalize_rating(user_data.get("Rating"), title)
        if rating is not None:
            self._library_ratings[(Sources.TMDB.value, media_id)] = rating

        if user_data.get("IsFavorite") and not user_data.get("Played"):
            self._favorite_records.append(
                {
                    "media_type": MediaTypes.TV.value,
                    "tmdb_id": media_id,
                    "title": title,
                },
            )

    def _process_episode(self, jf_item: dict):
        """Record a watched episode against its show-level provider ids."""
        user_data = jf_item.get("UserData") or {}
        if not user_data.get("Played"):
            return

        season_number = jf_item.get("ParentIndexNumber")
        episode_number = jf_item.get("IndexNumber")
        if season_number is None or episode_number is None:
            return

        series_title = jf_item.get("SeriesName")
        series_provider_ids = self._series_provider_ids.get(
            jf_item.get("SeriesId"),
            {},
        )
        show_ids = self._external_ids(series_provider_ids)

        media_id, _, _ = self.processor._find_tv_media_id(
            show_ids,
            series_title=series_title,
            allow_title_fallback=True,
        )
        if not media_id:
            self._record_missing_metadata(
                series_title or jf_item.get("Name"),
                "missing TMDB/TVDB/IMDB ID",
            )
            return

        media_id = str(media_id)
        if not self._should_process_media(MediaTypes.TV.value, media_id):
            self.summary_counts["skipped_existing"] += 1
            return

        rating = self._normalize_rating(user_data.get("Rating"), jf_item.get("Name"))

        for watched_at in self._watch_times(jf_item):
            self._episode_records.append(
                {
                    "tmdb_id": media_id,
                    "external_ids": dict(show_ids),
                    "season_number": int(season_number),
                    "episode_number": int(episode_number),
                    "source_season_number": int(season_number),
                    "source_episode_number": int(episode_number),
                    "tvdb_show_id": show_ids.get("tvdb_id"),
                    "anime_section": False,
                    "watched_at": watched_at,
                    "viewed_at_ts": int(watched_at.timestamp()),
                    "rating_key": jf_item.get("Id"),
                    "rating": rating,
                    "title": jf_item.get("Name") or "Unknown Episode",
                    "series_title": series_title,
                    "provider_ids": series_provider_ids,
                },
            )
        self._tv_ids.add(media_id)

    # -- favorites ------------------------------------------------------

    def _build_favorite_media(self):
        """Turn unplayed favorites into Planning entries."""
        model_by_type = {
            MediaTypes.MOVIE.value: app.models.Movie,
            MediaTypes.TV.value: app.models.TV,
        }

        for record in self._favorite_records:
            media_type = record["media_type"]
            tmdb_id = record["tmdb_id"]
            # A favorite that also has watch history is already tracked by
            # the main bulk stage; Planning must not overwrite that.
            if tmdb_id in self.media_instances[media_type]:
                continue
            if not self._should_process_media(media_type, tmdb_id):
                continue

            if media_type == MediaTypes.MOVIE.value:
                metadata = self._get_movie_metadata(tmdb_id, record["title"])
            else:
                metadata = self._tv_metadata_cache.get(
                    tmdb_id,
                ) or self._get_tv_metadata(tmdb_id, set(), record["title"])
            if not metadata:
                continue

            item = self._get_or_create_item(media_type, tmdb_id, metadata)
            media = model_by_type[media_type](
                item=item,
                user=self.user,
                status=Status.PLANNING.value,
            )
            self.bulk_media[media_type].append(media)
            self.media_instances[media_type][tmdb_id] = media
            self.summary_counts["created"] += 1

    # -- music ----------------------------------------------------------

    def _collect_music(self, parent_ids):
        """Import played audio tracks through the shared scrobble service."""
        for parent_id in parent_ids:
            try:
                for jf_item in self.client.iter_library_items(
                    item_types="Audio",
                    fields=MUSIC_FIELDS,
                    parent_id=parent_id,
                ):
                    self._process_track(jf_item)
            except (JellyfinAuthError, JellyfinClientError) as exc:
                logger.warning(
                    "Could not read Jellyfin music library: %s",
                    exception_summary(exc),
                )
                self.warnings.append(
                    f"Could not import Jellyfin music: {exc}",
                )
                return

    def _process_track(self, jf_item: dict):
        """Record one played Jellyfin audio item as a music scrobble."""
        user_data = jf_item.get("UserData") or {}
        if not user_data.get("Played"):
            return

        duration_ticks = jf_item.get("RunTimeTicks")
        duration_ms = (
            int(duration_ticks) // TICKS_PER_MS if duration_ticks is not None else None
        )

        external_ids = {}
        for provider, value in (jf_item.get("ProviderIds") or {}).items():
            key = _MUSICBRAINZ_PROVIDER_MAP.get(provider)
            if key and value:
                external_ids.setdefault(key, str(value))

        for played_at in self._watch_times(jf_item):
            event = music_scrobble.MusicPlaybackEvent(
                user=self.user,
                artist_name=jf_item.get("AlbumArtist") or _first_artist(jf_item),
                album_title=jf_item.get("Album"),
                track_title=jf_item.get("Name") or "Unknown Track",
                track_number=jf_item.get("IndexNumber"),
                duration_ms=duration_ms,
                external_ids=external_ids,
                completed=True,
                played_at=played_at,
                defer_cover_prefetch=True,
            )
            try:
                result = music_scrobble.record_music_playback(event)
            except Exception as exc:  # pragma: no cover - defensive
                logger.warning(
                    "Failed to import Jellyfin track %s: %s",
                    jf_item.get("Name"),
                    exception_summary(exc),
                )
                continue

            if not result:
                continue
            if getattr(result, "item", None):
                self._unique_music_tracks.add(
                    (result.item.media_id, result.item.source),
                )
            self.counts[MediaTypes.MUSIC.value] += 1

    # -- anime hook -----------------------------------------------------

    def _build_anime_payload(self, record: dict) -> dict:
        """Build a minimal played Jellyfin payload for anime mapping handlers."""
        season_number = (
            record.get("source_season_number")
            if record.get("source_season_number") is not None
            else record["season_number"]
        )
        episode_number = (
            record.get("source_episode_number")
            if record.get("source_episode_number") is not None
            else record["episode_number"]
        )
        return {
            "Event": "MarkPlayed",
            "Item": {
                "Type": "Episode",
                "Name": record["title"],
                "SeriesName": record["series_title"],
                "ParentIndexNumber": int(season_number),
                "IndexNumber": int(episode_number),
                "Id": record.get("rating_key"),
                "ProviderIds": record.get("provider_ids") or {},
                "UserData": {"Played": True},
            },
            "_import_batch": True,
        }
