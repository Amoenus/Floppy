"""Shared bulk-creation stage for media-server importers.

Plex and Jellyfin differ in how they enumerate watch history, but once each
importer has normalized its rows into ``_movie_records`` / ``_episode_records``
dicts the rest is identical: warm TMDB metadata, resolve anime routing, build
unsaved Item/Movie/TV/Season/Episode instances, and hand them to
``helpers.bulk_create_media``. That shared stage lives here.

Subclasses own the collection phase and must provide:

* ``self.processor`` -- a ``BaseWebhookProcessor`` for id resolution
* ``SOURCE_KEY`` -- short slug used in per-run dedupe keys
* ``_build_anime_payload(record)`` -- a source-shaped payload for the
  processor's anime handler

Records use source-neutral keys: ``source_season_number``,
``source_episode_number`` and ``rating_key`` carry the media server's own
numbering, which may differ from TMDB's.
"""

import logging
import re
from collections import defaultdict
from datetime import datetime
from http import HTTPStatus

from django.conf import settings
from django.utils import timezone

import app
from app.log_safety import exception_summary
from app.models import MediaTypes, Sources, Status
from app.providers import services
from integrations import episode_remap
from integrations.imports import helpers
from integrations.webhooks import anime_mappings

logger = logging.getLogger(__name__)

RATING_SCALE_MAX = 10
RATING_PERCENTAGE_SCALE_MAX = 100


class MediaServerBulkImporter:
    """Turn normalized media-server history records into Floppy media rows."""

    SOURCE_KEY = "media_server"
    SOURCE_LABEL = "media server"

    def _init_bulk_state(self, user, mode, *, fast_mode=True):
        """Initialize the state the shared bulk stage relies on."""
        self.user = user
        self.mode = mode
        self.fast_mode = fast_mode
        self.existing_media = helpers.get_existing_media(user)
        self.to_delete = defaultdict(lambda: defaultdict(set))
        self.bulk_media = defaultdict(list)
        self.media_instances = defaultdict(lambda: defaultdict(list))
        self.counts = defaultdict(int)
        self.summary_counts = defaultdict(int)
        self.warnings = []
        self._movie_records: list[dict] = []
        self._episode_records: list[dict] = []
        self._movie_ids: set[str] = set()
        self._tv_ids: set[str] = set()
        self._existing_movie_keys: set[tuple[str, datetime]] = set()
        self._existing_episode_keys: set[tuple[str, int, int, datetime]] = set()
        self._import_movie_keys: set[tuple[str, datetime]] = set()
        self._import_episode_keys: set[tuple] = set()
        self._movie_metadata_cache: dict[str, dict] = {}
        self._tv_metadata_cache: dict[str, dict] = {}
        self._tv_seasons_loaded: dict[str, set[int]] = defaultdict(set)
        self._existing_season_cache: dict[tuple[str, int], object | None] = {}
        self._library_ratings: dict[tuple[str, str], float] = {}
        self._anime_import_keys: set[tuple[str, int]] = set()
        self._preserved_scores: dict[tuple, float] = {}
        self._episode_find_cache: dict[tuple[str, str], tuple | None] = {}
        self._tv_genesis_cache: dict[tuple[str, int], tuple] = {}
        self._artists_for_prefetch: set[int] = set()
        self._unique_music_tracks: set[tuple[str, str]] = set()

    def _build_anime_payload(self, record: dict) -> dict:
        """Build a source-shaped played payload for the anime handler."""
        raise NotImplementedError

    def _record_missing_metadata(self, title: str | None, reason: str) -> None:
        """Record a record dropped because its metadata could not be resolved."""
        self.summary_counts["skipped_missing_ids"] += 1
        self.warnings.append(
            f"Skipping {self.SOURCE_LABEL} entry for "
            f"{title or 'Unknown title'}: {reason}",
        )

    def _should_process_media(self, media_type: str, media_id: str) -> bool:
        """Apply new/overwrite semantics for the resolved IDs."""
        return helpers.should_process_media(
            self.existing_media,
            self.to_delete,
            media_type,
            Sources.TMDB.value,
            str(media_id),
            self.mode,
        )

    def _normalize_rating(self, rating_value, title: str | None) -> float | None:
        """Normalize Plex rating values onto a 0-10 scale."""
        if rating_value in (None, ""):
            return None

        try:
            rating = float(rating_value)
        except (TypeError, ValueError):
            entry_title = title or "Unknown title"
            self.warnings.append(
                f"{entry_title}: invalid Plex rating '{rating_value}' - skipped",
            )
            return None

        if rating < 0:
            entry_title = title or "Unknown title"
            self.warnings.append(
                f"{entry_title}: invalid Plex rating '{rating_value}' - skipped",
            )
            return None

        if rating <= RATING_SCALE_MAX:
            pass  # value already in the expected range
        elif rating <= RATING_PERCENTAGE_SCALE_MAX:
            rating /= 10
        else:
            entry_title = title or "Unknown title"
            self.warnings.append(
                f"{entry_title}: invalid Plex rating '{rating_value}' - skipped",
            )
            return None

        rating = round(rating, 1)
        if rating < 0 or rating > RATING_SCALE_MAX:
            entry_title = title or "Unknown title"
            self.warnings.append(
                f"{entry_title}: invalid Plex rating '{rating_value}' - skipped",
            )
            return None

        return rating

    def _resolve_movie_tmdb_id(self, ids: dict) -> str | None:
        """Resolve a TMDB ID for a movie entry."""
        tmdb_id = ids.get("tmdb_id")
        if tmdb_id:
            return str(tmdb_id)

        imdb_id = ids.get("imdb_id")
        if not imdb_id:
            return None

        try:
            response = app.providers.tmdb.find(imdb_id, "imdb_id")
        except services.ProviderAPIError as exc:
            self.warnings.append(f"TMDB lookup failed for IMDB {imdb_id}: {exc}")
            return None

        if response.get("movie_results"):
            return str(response["movie_results"][0]["id"])
        return None

    def _try_import_episode_record_as_anime(
        self,
        record: dict,
        tv_metadata: dict,
    ) -> bool:
        """Route confirmed Plex anime history through the anime webhook path."""
        if not getattr(self.user, "anime_enabled", False):
            return False

        # AniBridge mappings and Plex libraries both follow TVDB numbering;
        # fall back to the TMDB-validated numbers when Plex omitted them.
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
        tmdb_id = str(tv_metadata.get("media_id", record["tmdb_id"]))
        # The episode-level Guid tvdb id is an episode id, useless for
        # tvdb_show mappings — only use show-level TVDB ids here.
        tvdb_id = record.get("tvdb_show_id") or tv_metadata.get("tvdb_id")

        anime_section = bool(record.get("anime_section"))
        if not anime_section and self._has_existing_non_anime_tv_tracking(
            tmdb_id,
            tvdb_id,
        ):
            return False

        for _source, mal_id, mapped_episode in self._anime_mapping_candidates(
            tmdb_id,
            tvdb_id,
            season_number,
            episode_number,
        ):
            if mal_id and self._import_mapped_anime_record(
                record,
                mal_id,
                mapped_episode,
            ):
                return True

        resolved_tvdb_id = self._resolve_tvdb_id_for_anime_probe(
            tmdb_id,
            tvdb_id,
            tv_metadata,
        )
        if not resolved_tvdb_id:
            return False

        if not anime_section and self._has_existing_non_anime_tv_tracking(
            tmdb_id,
            resolved_tvdb_id,
        ):
            return False

        try:
            tvdb_metadata = app.providers.tvdb.tv(resolved_tvdb_id)
        except Exception as exc:  # pragma: no cover - defensive network guard
            logger.warning(
                "Failed TVDB anime probe for Plex import show %s via TVDB ID %s: %s",
                tmdb_id,
                resolved_tvdb_id,
                exception_summary(exc),
            )
            return False

        if not app.providers.tvdb.series_has_anime_genre(
            resolved_tvdb_id,
            tv_data=tvdb_metadata,
        ):
            return False

        # The probe may have found a TVDB id the mapping pass didn't have;
        # retry AniBridge with it so multi-season shows map to the right MAL
        # entry instead of the show-level MAL id below.
        if str(resolved_tvdb_id) != str(tvdb_id or ""):
            for _source, mal_id, mapped_episode in self._anime_mapping_candidates(
                tmdb_id,
                resolved_tvdb_id,
                season_number,
                episode_number,
            ):
                if mal_id and self._import_mapped_anime_record(
                    record,
                    mal_id,
                    mapped_episode,
                ):
                    return True

        if int(season_number) == 0:
            self.warnings.append(
                f"Skipping Plex anime special for {record['series_title']}: "
                "no MAL episode mapping found.",
            )
            self.summary_counts["skipped_missing_ids"] += 1
            return True

        mal_id = (tvdb_metadata.get("provider_external_ids") or {}).get("mal_id")
        if not mal_id:
            logger.info(
                "TVDB anime probe matched Plex import show %s but no MAL ID was available",
                tmdb_id,
            )
            return False

        return self._import_mapped_anime_record(record, mal_id, episode_number)

    def _has_existing_non_anime_tv_tracking(self, tmdb_id, tvdb_id=None) -> bool:
        """Return whether this user already tracks the show as regular TV.

        Items are shared across users and survive media deletion, so a global
        Item lookup would let one stale import block anime routing forever.
        Only the user's own TV rows (and shows already routed to TV earlier in
        this run) should pin a show to the TV path.
        """
        tmdb_id = str(tmdb_id)

        if tmdb_id in self.media_instances[MediaTypes.TV.value]:
            tv_obj = self.media_instances[MediaTypes.TV.value][tmdb_id][0]
            item = getattr(tv_obj, "item", None)
            if item is None or item.library_media_type != MediaTypes.ANIME.value:
                return True

        user_tv = app.models.TV.objects.filter(user=self.user).exclude(
            item__library_media_type=MediaTypes.ANIME.value,
        )

        if user_tv.filter(
            item__source=Sources.TMDB.value,
            item__media_id=tmdb_id,
        ).exists():
            return True

        if user_tv.filter(
            item__provider_links__provider=Sources.TMDB.value,
            item__provider_links__provider_media_type=MediaTypes.TV.value,
            item__provider_links__provider_media_id=tmdb_id,
        ).exists():
            return True

        return bool(
            tvdb_id not in (None, "")
            and user_tv.filter(
                item__provider_links__provider=Sources.TVDB.value,
                item__provider_links__provider_media_type=MediaTypes.TV.value,
                item__provider_links__provider_media_id=str(tvdb_id),
            ).exists(),
        )

    def _anime_mapping_candidates(
        self,
        tmdb_id: str,
        tvdb_id,
        season_number: int,
        episode_number: int,
    ):
        """Yield explicit anime mapping candidates for a Plex episode record."""
        yield (
            "stored TMDB",
            *self.processor._get_mal_id_from_provider_links(
                Sources.TMDB.value,
                tmdb_id,
                season_number,
                episode_number,
            ),
        )
        yield (
            "stored TVDB",
            *self.processor._get_mal_id_from_provider_links(
                Sources.TVDB.value,
                tvdb_id,
                season_number,
                episode_number,
            ),
        )

        if not tvdb_id:
            return

        try:
            mapping_data = anime_mappings.fetch_mapping_data()
        except Exception as exc:  # pragma: no cover - defensive network guard
            logger.warning(
                "Failed to fetch anime mappings during Plex import: %s",
                exception_summary(exc),
            )
            return
        yield (
            "TVDB",
            *anime_mappings.get_mal_id_from_tvdb(
                mapping_data,
                tvdb_id,
                season_number,
                episode_number,
            ),
        )

    def _resolve_tvdb_id_for_anime_probe(
        self,
        tmdb_id: str,
        tvdb_id,
        tv_metadata: dict,
    ):
        """Return a TVDB ID for conservative anime genre probing."""
        if not app.providers.tvdb.enabled():
            return None
        if tvdb_id:
            return tvdb_id
        return app.providers.tmdb.resolve_tvdb_id_for_tmdb_show(tmdb_id, tv_metadata)

    def _import_mapped_anime_record(self, record: dict, mal_id, mapped_episode) -> bool:
        """Import one Plex history row as flat Anime progress."""
        if not mal_id or mapped_episode is None:
            return False

        try:
            mapped_episode = int(mapped_episode)
        except (TypeError, ValueError):
            return False
        if mapped_episode <= 0:
            return False

        dedupe_key = (str(mal_id), mapped_episode)
        if dedupe_key in self._anime_import_keys:
            self.summary_counts["skipped_existing"] += 1
            return True
        self._anime_import_keys.add(dedupe_key)

        existing = app.models.Anime.objects.filter(
            user=self.user,
            item__source=Sources.MAL.value,
            item__media_id=str(mal_id),
        ).first()
        if existing and existing.progress >= mapped_episode:
            self.summary_counts["skipped_existing"] += 1
            return True

        if not self.processor._handle_anime(
            str(mal_id),
            mapped_episode,
            self._build_anime_payload(record),
            self.user,
        ):
            return False

        anime = app.models.Anime.objects.filter(
            user=self.user,
            item__source=Sources.MAL.value,
            item__media_id=str(mal_id),
        ).first()
        if anime:
            self._apply_import_timestamp(anime, record["watched_at"])

        self.counts[MediaTypes.ANIME.value] += 1
        self.summary_counts["created"] += 1
        return True

    def _apply_import_timestamp(self, anime, watched_at: datetime):
        """Preserve Plex history time on Anime rows created through webhook handlers."""
        update_fields = []
        if anime.status == Status.COMPLETED.value:
            if anime.end_date != watched_at:
                anime.end_date = watched_at
                update_fields.append("end_date")
        elif anime.start_date != watched_at:
            anime.start_date = watched_at
            update_fields.append("start_date")

        if update_fields:
            anime._history_date = watched_at
            anime.save(update_fields=update_fields)

    def _capture_existing_scores(self):
        """Snapshot user scores before overwrite deletion wipes the rows.

        Plex only supplies ratings present in its own history/library, so a
        rating set in Floppy would otherwise vanish on every periodic
        overwrite import.
        """
        model_by_type = {
            MediaTypes.MOVIE.value: app.models.Movie,
            MediaTypes.TV.value: app.models.TV,
        }
        for media_type, model in model_by_type.items():
            for source, media_ids in self.to_delete.get(media_type, {}).items():
                if not media_ids:
                    continue
                rows = model.objects.filter(
                    user=self.user,
                    item__source=source,
                    item__media_id__in=media_ids,
                    score__isnull=False,
                ).select_related("item")
                for row in rows:
                    key = (media_type, source, row.item.media_id)
                    self._preserved_scores[key] = row.score

        tv_ids = self.to_delete.get(MediaTypes.TV.value, {}).get(
            Sources.TMDB.value,
            set(),
        )
        if tv_ids:
            seasons = app.models.Season.objects.filter(
                user=self.user,
                item__source=Sources.TMDB.value,
                item__media_id__in=tv_ids,
                score__isnull=False,
            ).select_related("item")
            for season in seasons:
                key = (
                    MediaTypes.SEASON.value,
                    Sources.TMDB.value,
                    season.item.media_id,
                    season.item.season_number,
                )
                self._preserved_scores[key] = season.score

        if self._preserved_scores:
            logger.info(
                "Preserved %d user scores ahead of overwrite cleanup",
                len(self._preserved_scores),
            )

    def _preserved_score(self, media_type: str, media_id: str, season_number=None):
        """Return the captured score for a row recreated by this import."""
        if media_type == MediaTypes.SEASON.value:
            key = (media_type, Sources.TMDB.value, str(media_id), season_number)
        else:
            key = (media_type, Sources.TMDB.value, str(media_id))
        return self._preserved_scores.get(key)

    def _build_existing_dedupe_sets(self):
        """Collect existing movie/episode keys for replay-safe imports."""
        if self._movie_ids:
            existing_movies = app.models.Movie.objects.filter(
                user=self.user,
                item__media_id__in=self._movie_ids,
                item__source=Sources.TMDB.value,
            ).select_related("item")
            for movie in existing_movies:
                if not movie.end_date:
                    continue
                key = (movie.item.media_id, self._round_datetime(movie.end_date))
                self._existing_movie_keys.add(key)

        if self._tv_ids:
            existing_episodes = app.models.Episode.objects.filter(
                related_season__user=self.user,
                item__media_id__in=self._tv_ids,
                item__source=Sources.TMDB.value,
            ).select_related("item", "related_season")
            for episode in existing_episodes:
                if not episode.end_date:
                    continue
                key = (
                    episode.item.media_id,
                    episode.item.season_number,
                    episode.item.episode_number,
                    self._round_datetime(episode.end_date),
                )
                self._existing_episode_keys.add(key)

    def _build_bulk_media(self):
        """Convert collected history records into bulk media instances."""
        logger.info("Bulk importing movie entries: %d", len(self._movie_records))
        for record in sorted(
            self._movie_records,
            key=lambda item: item["watched_at"],
        ):
            if self._should_skip_movie_record(record):
                continue

            metadata = self._get_movie_metadata(record["tmdb_id"], record["title"])
            if not metadata:
                self._record_missing_metadata(
                    record["title"],
                    f"not found in {Sources.TMDB.label} with ID {record['tmdb_id']}",
                )
                continue

            actual_tmdb_id = str(metadata.get("media_id", record["tmdb_id"]))
            if actual_tmdb_id in self.media_instances[MediaTypes.MOVIE.value]:
                continue

            # Check if it already exists in the database (e.g. if ID was resolved to existing)
            existing = self.existing_media[MediaTypes.MOVIE.value][
                Sources.TMDB.value
            ].get(
                actual_tmdb_id,
            )
            if existing and self.mode == "new":
                self.media_instances[MediaTypes.MOVIE.value][actual_tmdb_id] = [
                    existing
                ]
                continue

            item = self._get_or_create_item(
                MediaTypes.MOVIE.value,
                actual_tmdb_id,
                metadata,
            )

            movie_obj = app.models.Movie(
                item=item,
                user=self.user,
                end_date=record["watched_at"],
                status=Status.COMPLETED.value,
            )
            # Apply rating from history if available, otherwise try library rating
            if record["rating"] is not None:
                movie_obj.score = record["rating"]
            else:
                # Try to get rating from library items
                rating = self._library_ratings.get(("tmdb", actual_tmdb_id))
                if rating is None and record.get("imdb_id"):
                    rating = self._library_ratings.get(("imdb", record["imdb_id"]))
                if rating is None:
                    rating = self._preserved_score(
                        MediaTypes.MOVIE.value,
                        actual_tmdb_id,
                    )
                if rating is not None:
                    movie_obj.score = rating

            movie_obj._history_date = record["watched_at"]
            self.bulk_media[MediaTypes.MOVIE.value].append(movie_obj)
            self.media_instances[MediaTypes.MOVIE.value][actual_tmdb_id] = [movie_obj]
            self.summary_counts["created"] += 1

        logger.info("Bulk importing tv entries: %d", len(self._episode_records))
        for record in sorted(
            self._episode_records,
            key=lambda item: item["watched_at"],
        ):
            if self._should_skip_episode_record(record):
                continue

            tv_metadata = self._tv_metadata_cache.get(record["tmdb_id"])
            if not tv_metadata:
                self._record_missing_metadata(
                    record["title"],
                    f"not found in {Sources.TMDB.label} with ID {record['tmdb_id']}",
                )
                continue

            if self._try_import_episode_record_as_anime(record, tv_metadata):
                continue

            season_metadata = self._validate_or_remap_episode(record, tv_metadata)
            if season_metadata is None:
                continue

            actual_tmdb_id = str(tv_metadata.get("media_id", record["tmdb_id"]))
            # Honors the user's TV metadata provider preference (issue #387):
            # a never-before-tracked show is genesis'd under TVDB instead of
            # TMDB when preferred and a matching TVDB show/season resolves;
            # falls back to today's TMDB identity otherwise.
            (
                item_source,
                item_media_id,
                item_tv_metadata,
                item_season_metadata,
            ) = self._resolve_tv_genesis(
                actual_tmdb_id,
                tv_metadata,
                season_metadata,
                record["season_number"],
            )
            tv_key = f"{item_source}:{item_media_id}"
            # Shows from an anime library that lack a MAL mapping still belong
            # in the anime view; the item classification drives list routing.
            anime_class = (
                MediaTypes.ANIME.value
                if record.get("anime_section")
                and getattr(self.user, "anime_enabled", False)
                else None
            )

            if tv_key in self.media_instances[MediaTypes.TV.value]:
                tv_obj = self.media_instances[MediaTypes.TV.value][tv_key][0]
            else:
                # Check if it already exists in the database, under either
                # source — a show already tracked (e.g. added manually, or via
                # an earlier import before the preference changed) must not be
                # duplicated under the other provider.
                existing = self.existing_media[MediaTypes.TV.value][item_source].get(
                    item_media_id,
                )
                if existing is None:
                    other_source = (
                        Sources.TVDB.value
                        if item_source == Sources.TMDB.value
                        else Sources.TMDB.value
                    )
                    other_media_id = (
                        actual_tmdb_id
                        if other_source == Sources.TMDB.value
                        else str(tv_metadata.get("tvdb_id") or "")
                    )
                    if other_media_id:
                        existing = self.existing_media[MediaTypes.TV.value][
                            other_source
                        ].get(other_media_id)
                        if existing:
                            item_source, item_media_id = other_source, other_media_id
                            tv_key = f"{item_source}:{item_media_id}"
                if existing and self.mode == "new":
                    tv_obj = existing
                    # Apply rating from library items if available and different
                    rating = self._library_ratings.get(("tmdb", actual_tmdb_id))
                    if rating is None:
                        # Title/search fallback can resolve a different show ID than the
                        # original Plex GUID, so keep using the resolved metadata payload
                        # if the cache is not also keyed by the final TMDB ID.
                        resolved_tv_metadata = (
                            self._tv_metadata_cache.get(actual_tmdb_id) or tv_metadata
                        )
                        tvdb_id = resolved_tv_metadata.get("tvdb_id")
                        if tvdb_id:
                            rating = self._library_ratings.get(("tvdb", str(tvdb_id)))
                    if rating is not None and tv_obj.score != rating:
                        tv_obj.score = rating
                        tv_obj.save(update_fields=["score"])
                        logger.debug(
                            "Applied library rating to existing TV show during Plex import",
                        )
                    self.media_instances[MediaTypes.TV.value][tv_key] = [tv_obj]
                else:
                    tv_item = self._get_or_create_item(
                        MediaTypes.TV.value,
                        item_media_id,
                        item_tv_metadata,
                        library_media_type=anime_class,
                        source=item_source,
                    )
                    tv_obj = app.models.TV(
                        item=tv_item,
                        user=self.user,
                        status=Status.IN_PROGRESS.value,
                    )
                    # Apply rating from library items if available
                    rating = self._library_ratings.get(("tmdb", actual_tmdb_id))
                    if rating is None:
                        # Try TVDB fallback
                        tvdb_id = tv_metadata.get("tvdb_id")
                        if tvdb_id:
                            rating = self._library_ratings.get(("tvdb", str(tvdb_id)))
                    if rating is None:
                        rating = self._preserved_score(
                            MediaTypes.TV.value,
                            actual_tmdb_id,
                        )
                    if rating is not None:
                        tv_obj.score = rating
                    tv_obj._history_date = record["watched_at"]
                    self.bulk_media[MediaTypes.TV.value].append(tv_obj)
                    self.media_instances[MediaTypes.TV.value][tv_key] = [tv_obj]

            season_key = f"{tv_key}:{record['season_number']}"
            if season_key not in self.media_instances[MediaTypes.SEASON.value]:
                season_obj = None
                if self.mode == "new":
                    season_obj = self._get_existing_season(
                        item_media_id,
                        record["season_number"],
                        tv_obj,
                        source=item_source,
                    )

                if season_obj is None:
                    season_image = item_season_metadata.get(
                        "image",
                    ) or item_tv_metadata.get("image")
                    season_item = self._get_or_create_item(
                        MediaTypes.SEASON.value,
                        item_media_id,
                        {
                            "title": item_tv_metadata["title"],
                            "original_title": item_tv_metadata.get("original_title"),
                            "localized_title": item_tv_metadata.get("localized_title"),
                            "image": season_image,
                        },
                        season_number=record["season_number"],
                        library_media_type=anime_class,
                        source=item_source,
                    )
                    season_obj = app.models.Season(
                        item=season_item,
                        user=self.user,
                        related_tv=tv_obj,
                        status=Status.IN_PROGRESS.value,
                    )
                    season_score = self._preserved_score(
                        MediaTypes.SEASON.value,
                        actual_tmdb_id,
                        record["season_number"],
                    )
                    if season_score is not None:
                        season_obj.score = season_score
                    season_obj._history_date = record["watched_at"]
                    self.bulk_media[MediaTypes.SEASON.value].append(season_obj)
                self.media_instances[MediaTypes.SEASON.value][season_key] = [
                    season_obj,
                ]
            else:
                season_obj = self.media_instances[MediaTypes.SEASON.value][season_key][
                    0
                ]

            episode_image = self._get_episode_image(
                record["episode_number"],
                item_season_metadata,
            )
            # Episode items are historically keyed by the record's originally
            # resolved TMDB id, which can differ from the show/season's final
            # `item_media_id` (e.g. title-search fallback landed on another
            # show) — preserved as-is for the TMDB path. TVDB genesis has no
            # equivalent per-record id, so it keys episodes the same as the
            # show/season.
            episode_media_id = (
                record["tmdb_id"]
                if item_source == Sources.TMDB.value
                else item_media_id
            )
            episode_item = self._get_or_create_item(
                MediaTypes.EPISODE.value,
                episode_media_id,
                {
                    "title": item_tv_metadata["title"],
                    "original_title": item_tv_metadata.get("original_title"),
                    "localized_title": item_tv_metadata.get("localized_title"),
                    "image": episode_image,
                },
                season_number=record["season_number"],
                episode_number=record["episode_number"],
                library_media_type=anime_class,
                source=item_source,
            )
            episode_obj = app.models.Episode(
                item=episode_item,
                related_season=season_obj,
                end_date=record["watched_at"],
            )
            episode_obj._history_date = record["watched_at"]
            self.bulk_media[MediaTypes.EPISODE.value].append(episode_obj)
            self.summary_counts["created"] += 1

            self._update_completion_status(
                season_obj,
                tv_obj,
                record["season_number"],
                record["episode_number"],
                item_season_metadata,
                item_tv_metadata,
            )

    def _validate_or_remap_episode(self, record: dict, tv_metadata: dict):
        """Return the season payload for a record, remapping numbering if needed.

        Plex libraries follow TVDB numbering while TMDB may split or merge
        seasons. When the record's numbers don't exist in TMDB, try to recover
        the real TMDB (season, episode) instead of dropping the watch.
        """
        season_metadata = tv_metadata.get(f"season/{record['season_number']}")
        if season_metadata and self._episode_in_season(
            record["episode_number"],
            season_metadata,
        ):
            return season_metadata

        remapped = self._remap_episode_via_tmdb_find(record, tv_metadata)
        if remapped is None:
            remapped = self._remap_episode_via_cumulative_numbering(
                record,
                tv_metadata,
            )

        if remapped is not None:
            season_number, episode_number, remapped_season_metadata = remapped
            logger.info(
                "Remapped Plex episode %s S%sE%s to TMDB S%sE%s",
                record["tmdb_id"],
                record["season_number"],
                record["episode_number"],
                season_number,
                episode_number,
            )
            record["season_number"] = season_number
            record["episode_number"] = episode_number
            return remapped_season_metadata

        item_identifier = (
            f"{tv_metadata.get('title') or record['series_title']} "
            f"S{record['season_number']}E{record['episode_number']}"
        )
        self.warnings.append(
            f"{item_identifier}: not found in {Sources.TMDB.label} with ID "
            f"{record['tmdb_id']} - Plex/TVDB and TMDB likely split this "
            "show's seasons differently and no remap was found.",
        )
        self.summary_counts["skipped_numbering_mismatch"] += 1
        return None

    def _episode_in_season(self, episode_number, season_metadata: dict) -> bool:
        """Return whether the episode number exists in the season payload."""
        return episode_remap.episode_in_season(episode_number, season_metadata)

    def _season_loader(self, record: dict):
        """Return a season-payload loader bound to this record's show."""

        def load_season(season_number):
            return self._ensure_season_payload(
                record["tmdb_id"],
                season_number,
                record.get("series_title"),
            )

        return load_season

    def _remap_episode_via_tmdb_find(self, record: dict, tv_metadata: dict):
        """Resolve TMDB numbering from the episode-level TVDB/IMDB Guid."""
        return episode_remap.remap_via_tmdb_find(
            record.get("external_ids"),
            tv_metadata.get("media_id", record["tmdb_id"]),
            self._season_loader(record),
            find_cache=self._episode_find_cache,
        )

    def _remap_episode_via_cumulative_numbering(self, record: dict, tv_metadata: dict):
        """Carry a TVDB-numbered episode into the right TMDB split season."""
        return episode_remap.remap_via_cumulative_numbering(
            record["season_number"],
            record["episode_number"],
            tv_metadata,
            self._season_loader(record),
        )

    def _ensure_season_payload(
        self,
        tmdb_id: str,
        season_number: int,
        series_title: str | None,
    ):
        """Fetch and cache a season payload that the warm pass didn't load."""
        cached = self._tv_metadata_cache.get(tmdb_id)
        season_key = f"season/{season_number}"
        if cached and cached.get(season_key):
            return cached[season_key]
        if season_number in self._tv_seasons_loaded[tmdb_id]:
            return None

        self._tv_seasons_loaded[tmdb_id].add(season_number)
        metadata = self._get_tv_metadata(tmdb_id, {season_number}, series_title)
        if not metadata:
            return None

        if cached:
            if metadata.get(season_key):
                cached[season_key] = metadata[season_key]
        else:
            self._tv_metadata_cache[tmdb_id] = metadata

        return self._tv_metadata_cache[tmdb_id].get(season_key)

    def _should_skip_movie_record(self, record: dict) -> bool:
        """Check for duplicate movie history records."""
        key = (record["tmdb_id"], self._round_datetime(record["watched_at"]))
        if key in self._import_movie_keys:
            self.summary_counts["skipped_existing"] += 1
            return True

        self._import_movie_keys.add(key)

        if self.mode == "new" and key in self._existing_movie_keys:
            self.summary_counts["skipped_existing"] += 1
            return True

        return False

    def _should_skip_episode_record(self, record: dict) -> bool:
        """Check for duplicate episode history records."""
        import_key = self._build_episode_import_key(record)
        if import_key in self._import_episode_keys:
            self.summary_counts["skipped_existing"] += 1
            return True

        self._import_episode_keys.add(import_key)

        if self.mode == "new":
            existing_key = (
                record["tmdb_id"],
                record["season_number"],
                record["episode_number"],
                self._round_datetime(record["watched_at"]),
            )
            if existing_key in self._existing_episode_keys:
                self.summary_counts["skipped_existing"] += 1
                return True

        return False

    def _get_existing_season(
        self,
        tmdb_id: str,
        season_number: int,
        tv_obj,
        source: str = Sources.TMDB.value,
    ):
        """Reuse an already-imported season when a fallback TV ID resolves to it."""
        if not getattr(tv_obj, "pk", None):
            return None

        cache_key = (source, tmdb_id, season_number)
        if cache_key not in self._existing_season_cache:
            self._existing_season_cache[cache_key] = (
                app.models.Season.objects.filter(
                    user=self.user,
                    related_tv_id=tv_obj.pk,
                    item__season_number=season_number,
                    item__media_id=tmdb_id,
                    item__source=source,
                )
                .select_related("item", "related_tv")
                .first()
            )

        return self._existing_season_cache[cache_key]

    def _build_episode_import_key(self, record: dict) -> tuple:
        """Build a dedupe key for episode imports."""
        if record.get("rating_key") and record.get("viewed_at_ts"):
            return (self.SOURCE_KEY, record["rating_key"], record["viewed_at_ts"])

        return (
            "tmdb",
            record["tmdb_id"],
            record["season_number"],
            record["episode_number"],
            self._round_datetime(record["watched_at"]),
        )

    def _round_datetime(self, value: datetime) -> datetime:
        """Round datetimes to minute precision for replay-safe matching."""
        return timezone.localtime(value).replace(second=0, microsecond=0)

    def _pre_warm_movie_metadata(self):
        """Pre-fetch TMDB metadata for all pending movie records before overwrite deletion."""
        for record in self._movie_records:
            self._get_movie_metadata(record["tmdb_id"], record.get("title"))

    def _warm_tv_metadata_cache(self):
        """Fetch TV metadata with season payloads in bulk."""
        seasons_by_show: dict[str, set[int]] = defaultdict(set)
        series_titles: dict[str, str | None] = {}
        for record in self._episode_records:
            seasons_by_show[record["tmdb_id"]].add(record["season_number"])
            if record["tmdb_id"] not in series_titles:
                series_titles[record["tmdb_id"]] = record.get(
                    "series_title"
                ) or record.get("title")

        for tmdb_id, seasons in seasons_by_show.items():
            missing_seasons = seasons - self._tv_seasons_loaded[tmdb_id]
            if not missing_seasons and tmdb_id in self._tv_metadata_cache:
                continue

            metadata = self._get_tv_metadata(
                tmdb_id,
                missing_seasons or seasons,
                series_titles.get(tmdb_id),
            )
            if not metadata:
                continue

            if tmdb_id in self._tv_metadata_cache:
                existing = self._tv_metadata_cache[tmdb_id]
                for season_number in missing_seasons:
                    season_key = f"season/{season_number}"
                    if metadata.get(season_key):
                        existing[season_key] = metadata[season_key]
                self._tv_metadata_cache[tmdb_id] = existing
            else:
                self._tv_metadata_cache[tmdb_id] = metadata

            self._tv_seasons_loaded[tmdb_id].update(seasons)

    def _get_movie_metadata(self, tmdb_id: str, title: str | None) -> dict | None:
        """Fetch and cache movie metadata."""
        if tmdb_id in self._movie_metadata_cache:
            return self._movie_metadata_cache[tmdb_id]

        try:
            metadata = services.get_media_metadata(
                MediaTypes.MOVIE.value,
                tmdb_id,
                Sources.TMDB.value,
            )
        except services.ProviderAPIError as error:
            if getattr(error, "status_code", None) == HTTPStatus.NOT_FOUND:
                self.warnings.append(
                    f"{title or tmdb_id}: not found in {Sources.TMDB.label} with ID {tmdb_id}.",
                )
                return None
            raise

        self._movie_metadata_cache[tmdb_id] = metadata
        return metadata

    def _get_tv_metadata(
        self,
        tmdb_id: str,
        season_numbers: set[int],
        series_title: str | None = None,
    ) -> dict | None:
        """Fetch TV metadata for the selected seasons, with title search fallback."""
        try:
            return services.get_media_metadata(
                "tv_with_seasons",
                tmdb_id,
                Sources.TMDB.value,
                season_numbers=sorted(season_numbers),
            )
        except services.ProviderAPIError as error:
            if getattr(error, "status_code", None) == HTTPStatus.NOT_FOUND:
                # If ID lookup failed, try title search fallback if we have a title
                if series_title:
                    logger.info(
                        "Plex TMDB ID lookup failed; trying title fallback search",
                    )
                    try:
                        search_results = services.search(
                            MediaTypes.TV.value,
                            series_title,
                            page=1,
                        )
                        if search_results and search_results.get("results"):
                            new_tmdb_id = str(search_results["results"][0]["media_id"])
                            logger.info(
                                "Resolved Plex TV metadata via title fallback search",
                            )
                            # Retry with new ID
                            return services.get_media_metadata(
                                "tv_with_seasons",
                                new_tmdb_id,
                                Sources.TMDB.value,
                                season_numbers=sorted(season_numbers),
                            )

                        # If title has year in parenthesis like "Show (YYYY)", try stripping it
                        clean_title = re.sub(r"\s*\(\d{4}\)$", "", series_title[:500])
                        if clean_title != series_title:
                            logger.info(
                                "Retrying Plex TV title fallback search with normalized title"
                            )
                            search_results = services.search(
                                MediaTypes.TV.value,
                                clean_title,
                                page=1,
                            )
                            if search_results and search_results.get("results"):
                                new_tmdb_id = str(
                                    search_results["results"][0]["media_id"]
                                )
                                logger.info(
                                    "Resolved Plex TV metadata via normalized title fallback search",
                                )
                                return services.get_media_metadata(
                                    "tv_with_seasons",
                                    new_tmdb_id,
                                    Sources.TMDB.value,
                                    season_numbers=sorted(season_numbers),
                                )
                    except Exception as fallback_exc:
                        logger.warning(
                            "Plex TV title fallback search failed: %s",
                            exception_summary(fallback_exc),
                        )

                self.warnings.append(
                    f"{series_title or tmdb_id}: not found in {Sources.TMDB.label} with ID {tmdb_id}.",
                )
                return None
            raise

    def _resolve_tv_genesis(
        self,
        actual_tmdb_id: str,
        tv_metadata: dict,
        season_metadata: dict,
        season_number: int,
    ):
        """Memoized wrapper around the processor's TV genesis-identity resolver.

        Bulk import can process hundreds of episode records for the same
        show/season; without caching, each would repeat a live TVDB lookup.
        """
        cache_key = (actual_tmdb_id, season_number)
        if cache_key not in self._tv_genesis_cache:
            self._tv_genesis_cache[cache_key] = (
                self.processor._resolve_tv_genesis_identity(
                    self.user,
                    actual_tmdb_id,
                    tv_metadata,
                    season_metadata,
                    season_number,
                )
            )
        return self._tv_genesis_cache[cache_key]

    def _get_or_create_item(
        self,
        media_type: str,
        tmdb_id: str,
        metadata: dict,
        season_number: int | None = None,
        episode_number: int | None = None,
        library_media_type: str | None = None,
        source: str = Sources.TMDB.value,
    ):
        """Get or create an item in the database."""
        item_kwargs = {
            "media_id": tmdb_id,
            "source": source,
            "media_type": media_type,
            "library_media_type": library_media_type or media_type,
        }

        if season_number is not None:
            item_kwargs["season_number"] = season_number

        if episode_number is not None:
            item_kwargs["episode_number"] = episode_number

        defaults = {
            **app.models.Item.title_fields_from_metadata(metadata),
            "image": metadata["image"],
        }

        item, _ = helpers.retry_on_lock(
            lambda: app.models.Item.objects.get_or_create(
                **item_kwargs,
                defaults=defaults,
            ),
        )
        return item

    def _get_episode_image(self, episode_number: int, season_metadata: dict) -> str:
        """Extract episode image URL from season metadata."""
        for episode in season_metadata.get("episodes", []):
            if episode.get("episode_number") == episode_number:
                if episode.get("still_path"):
                    return f"https://image.tmdb.org/t/p/w500{episode['still_path']}"
                if episode.get("image"):
                    return episode["image"]
                break
        return settings.IMG_NONE

    def _update_completion_status(
        self,
        season_obj,
        tv_obj,
        season_number: int,
        episode_number: int,
        season_metadata: dict,
        tv_metadata: dict,
    ):
        """Update completion status for season and TV show if applicable."""
        if episode_number == season_metadata.get("max_progress"):
            season_obj.status = Status.COMPLETED.value

            last_season = tv_metadata.get("last_episode_season")
            if last_season and last_season == season_number:
                tv_obj.status = Status.COMPLETED.value
