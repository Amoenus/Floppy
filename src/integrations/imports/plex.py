"""Plex history importer."""

import logging
from collections import defaultdict
from datetime import UTC, datetime

import urllib3
from django.conf import settings
from django.utils import timezone

from app.log_safety import exception_summary, presence_map
from app.models import MediaTypes, Sources
from app.services.music import prefetch_album_covers

# Suppress InsecureRequestWarning (Plex local connections often use self-signed certs)
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# The imports below deliberately follow the warning filter above so importing
# plexapi does not emit InsecureRequestWarning at import time.
# ruff: noqa: E402

import contextlib

from integrations import plex as plex_api
from integrations.imports import helpers
from integrations.imports.helpers import MediaImportError, MediaImportUnexpectedError
from integrations.imports.media_server import MediaServerBulkImporter
from integrations.webhooks.plex import PlexWebhookProcessor

logger = logging.getLogger(__name__)

MAX_SKIPPED_USER_SAMPLES = 5
RATING_SCALE_MAX = 10
RATING_PERCENTAGE_SCALE_MAX = 100


def importer(library, user, mode):
    """Import Plex watch/listen history for the user."""
    account = getattr(user, "plex_account", None)
    if not account or not account.plex_token:
        msg = "Plex is not connected for this user."
        raise MediaImportError(msg)

    plex_importer = PlexHistoryImporter(
        user=user,
        account=account,
        mode=mode,
        library=library,
    )
    return plex_importer.import_data()


class PlexHistoryImporter(MediaServerBulkImporter):
    """Importer that replays Plex history through TMDB-backed bulk creation."""

    SOURCE_KEY = "plex"
    SOURCE_LABEL = "Plex"

    def __init__(self, user, account, mode, library, fast_mode=True):
        """Store the extra keyword arguments this form needs."""
        self._init_bulk_state(user, mode, fast_mode=fast_mode)
        self.account = account
        self.library = library
        self.processor = PlexWebhookProcessor()
        self.resources = []
        self._metadata_cache: dict[str, dict] = {}
        self._account_id: str | None = (
            str(account.plex_account_id)
            if getattr(account, "plex_account_id", None)
            else None
        )
        self._allowed_usernames: list[str] = []
        self._allowed_account_ids: set[str] = set()
        self._account_id_to_username: dict[str, str] = {}
        self._skipped_user_count = 0
        self._skipped_user_samples: set[str] = set()
        self._current_section_uri: str = ""
        self._current_section_anime_hint = False
        self._current_server_owned = True

    def import_data(self):
        """Import history for the selected library."""
        self._ensure_username_matches()
        self._ensure_account_id()
        self._init_allowed_usernames()
        self._init_allowed_account_ids()
        try:
            self.resources = plex_api.list_resources(self.account.plex_token)
        except plex_api.PlexAuthError as exc:
            msg = "Plex token expired; reconnect and try again."
            raise MediaImportError(msg) from exc

        sections = self._get_target_sections()
        if not sections:
            msg = "No Plex libraries are available to import."
            raise MediaImportError(msg)

        for section in sections:
            try:
                self._import_section(section)
            except MediaImportError as exc:
                section_label = (
                    section.get("title") or section.get("id") or "unknown library"
                )
                server_label = section.get("server_name") or "unknown server"
                logger.warning(
                    "Failed to import Plex section '%s' on '%s': %s",
                    section_label,
                    server_label,
                    exc,
                )
                self.warnings.append(
                    f"Could not import library '{section_label}' from '{server_label}': {exc}",
                )
            except Exception as exc:  # pragma: no cover - defensive
                msg = f"Unexpected error importing Plex section {section.get('title')}: {exc}"
                raise MediaImportUnexpectedError(msg) from exc

        if self.mode == "new":
            self._build_existing_dedupe_sets()

        logger.info("Warming TV metadata cache...")
        self._warm_tv_metadata_cache()

        if self.mode == "overwrite":
            self._pre_warm_movie_metadata()
            unresolvable_tv_ids = self._tv_ids - set(self._tv_metadata_cache.keys())
            if unresolvable_tv_ids:
                logger.warning(
                    "Preserving %d TV show(s) in overwrite mode — TMDB metadata unavailable: %s",
                    len(unresolvable_tv_ids),
                    unresolvable_tv_ids,
                )
                for source_ids in self.to_delete.get(MediaTypes.TV.value, {}).values():
                    source_ids.difference_update(unresolvable_tv_ids)
            unresolvable_movie_ids = self._movie_ids - set(
                self._movie_metadata_cache.keys()
            )
            if unresolvable_movie_ids:
                logger.warning(
                    "Preserving %d movie(s) in overwrite mode — TMDB metadata unavailable: %s",
                    len(unresolvable_movie_ids),
                    unresolvable_movie_ids,
                )
                for source_ids in self.to_delete.get(
                    MediaTypes.MOVIE.value, {}
                ).values():
                    source_ids.difference_update(unresolvable_movie_ids)
            self._capture_existing_scores()
            helpers.cleanup_existing_media(self.to_delete, self.user)
        logger.info("Building bulk media instances...")
        self._build_bulk_media()
        logger.info("Finalizing bulk creation...")
        helpers.bulk_create_media(self.bulk_media, self.user)

        self._prefetch_collected_album_covers()
        self._enqueue_fast_runtime_backfill()
        self._enqueue_music_enrichment()

        result_counts = {
            media_type: len(media_list)
            for media_type, media_list in self.bulk_media.items()
        }
        if MediaTypes.MUSIC.value in self.counts:
            result_counts[MediaTypes.MUSIC.value] = self.counts[MediaTypes.MUSIC.value]
        if MediaTypes.MUSIC.value in result_counts:
            result_counts["music_unique_tracks"] = len(self._unique_music_tracks)

        result_counts.update(self.summary_counts)

        if self._skipped_user_count:
            samples = ", ".join(sorted(self._skipped_user_samples))
            if samples:
                self.warnings.append(
                    f"Skipped {self._skipped_user_count} Plex history entries for other users ({samples}).",
                )
            else:
                self.warnings.append(
                    f"Skipped {self._skipped_user_count} Plex history entries for other users.",
                )

        deduped_warnings = "\n".join(dict.fromkeys(self.warnings))
        return result_counts, deduped_warnings

    def _ensure_username_matches(self):
        """Persist the Plex username into the user's webhook allow list."""
        username = (self.account.plex_username or "").strip()
        if not username:
            return

        existing = [
            u.strip() for u in (self.user.plex_usernames or "").split(",") if u.strip()
        ]

        if username.lower() in [u.lower() for u in existing]:
            return

        updated = [*existing, username]
        self.user.plex_usernames = ", ".join(updated)
        self.user.save(update_fields=["plex_usernames"])

    def _ensure_account_id(self):
        """Fetch and persist the Plex account id if missing."""
        if self._account_id:
            return

        try:
            account_info = plex_api.fetch_account(self.account.plex_token)
        except plex_api.PlexAuthError as exc:
            msg = "Plex token expired; reconnect and try again."
            raise MediaImportError(msg) from exc
        except plex_api.PlexClientError as exc:
            logger.warning(
                "Could not fetch Plex account ID: %s",
                exception_summary(exc),
            )
            return

        account_id = account_info.get("id")
        if account_id:
            self._account_id = str(account_id)
            self.account.plex_account_id = self._account_id
            self.account.save(update_fields=["plex_account_id"])

    def _init_allowed_usernames(self):
        """Initialize the allowed Plex usernames list."""
        usernames = [
            u.strip() for u in (self.user.plex_usernames or "").split(",") if u.strip()
        ]
        if not usernames and self.account.plex_username:
            usernames = [self.account.plex_username]
        self._allowed_usernames = [u.lower() for u in usernames]

    def _init_allowed_account_ids(self):
        """Resolve allowed usernames to Plex account IDs for history filtering."""
        if not self._allowed_usernames:
            if self._account_id:
                self._allowed_account_ids.add(str(self._account_id))
            return

        allowed_usernames = {name.lower() for name in self._allowed_usernames}
        resolved_usernames: set[str] = set()
        for username in allowed_usernames:
            if username.isdigit():
                self._allowed_account_ids.add(username)
                resolved_usernames.add(username)

        account_username = (self.account.plex_username or "").strip()
        if self._account_id and account_username:
            self._account_id_to_username.setdefault(
                str(self._account_id), account_username
            )
            if account_username.lower() in allowed_usernames:
                self._allowed_account_ids.add(str(self._account_id))
                # NOTE: Plex history uses "1" as the server-local owner ID.
                # That alias is only the connected user on servers they own,
                # so it is resolved per-server in _is_allowed_history_user
                # instead of being allowed globally here.
                resolved_usernames.add(account_username.lower())

        unresolved = [
            name for name in allowed_usernames if name not in resolved_usernames
        ]

        try:
            plex_users = plex_api.list_users(self.account.plex_token)
        except plex_api.PlexAuthError as exc:
            if unresolved:
                msg = "Plex token expired; reconnect and try again."
                raise MediaImportError(msg) from exc
            logger.warning(
                "Could not fetch Plex users for history diagnostics: Token expired"
            )
            plex_users = []
        except plex_api.PlexClientError as exc:
            logger.warning(
                "Could not fetch Plex users for history filtering: %s",
                exception_summary(exc),
            )
            plex_users = []

        username_to_ids: dict[str, set[str]] = defaultdict(set)
        for user in plex_users:
            account_ids = {
                str(value)
                for key in ("id", "accountID", "accountId", "account_id", "uuid")
                if (value := user.get(key))
            }
            if not account_ids:
                continue

            for key in ("username", "title", "name", "friendlyName", "email"):
                value = user.get(key)
                if isinstance(value, str) and value.strip():
                    name = value.strip()
                    username_to_ids[name.lower()].update(account_ids)
                    for account_id in account_ids:
                        self._account_id_to_username.setdefault(account_id, name)

        for name in unresolved:
            for account_id in username_to_ids.get(name, set()):
                self._allowed_account_ids.add(account_id)

        missing = [name for name in unresolved if name not in username_to_ids]
        if missing:
            self.warnings.append(
                "Could not map Plex usernames to account IDs for history filtering: "
                + ", ".join(sorted(set(missing))),
            )

    def _get_target_sections(self):
        """Return the sections the user selected or all if requested."""
        sections = self.account.sections or []
        if not sections:
            sections = plex_api.list_sections(self.account.plex_token)
            self.account.sections = sections
            self.account.sections_refreshed_at = timezone.now()
            self.account.save(update_fields=["sections", "sections_refreshed_at"])

        if self.library == "all":
            return sections

        try:
            machine_id, section_id = self.library.split("::", 1)
        except ValueError:
            msg = "Invalid Plex library selection."
            raise MediaImportError(msg) from None

        filtered = [
            section
            for section in sections
            if section.get("machine_identifier") == machine_id
            and str(section.get("id")) == str(section_id)
        ]

        if not filtered:
            msg = "The selected Plex library is no longer available."
            raise MediaImportError(msg)
        return filtered

    def _import_section(self, section: dict):
        """Fetch and ingest history for a single Plex section."""
        section_token = section.get("access_token") or self.account.plex_token
        self._current_section_token = section_token
        self._current_section_anime_hint = "anime" in (
            (section.get("title") or "").lower()
        )
        self._current_server_owned = self._is_server_owned(
            section.get("machine_identifier"),
        )

        connections = self._connections_for_machine(section.get("machine_identifier"))
        if section.get("uri"):
            connections.insert(0, section.get("uri"))
        seen = []
        connections = [
            c for c in connections if c and not (c in seen or seen.append(c))
        ]
        if not connections:
            msg = f"Could not find a Plex connection for {section.get('server_name') or 'server'}."
            raise MediaImportError(
                msg,
            )

        section_type = (section.get("type") or "").lower()
        if section_type and section_type not in ("artist", "music", "movie", "show"):
            self.warnings.append(
                f"Plex library '{section.get('title') or section.get('id')}' "
                f"has unsupported type '{section_type}'; unsupported entries will be skipped.",
            )

        entries, uri_used = self._fetch_history_entries(
            connections, section.get("id"), token=section_token
        )
        self._current_section_uri = uri_used
        skipped_users_before = self._skipped_user_count

        for entry in entries:
            try:
                self._process_entry(entry, uri_used, section_type)
            except MediaImportError as exc:
                self.warnings.append(str(exc))
            except Exception as exc:  # pragma: no cover - defensive
                logger.warning(
                    "Failed to import a Plex history entry: %s",
                    exception_summary(exc),
                )
                self.warnings.append(f"Failed to import a Plex entry: {exc}")

        logger.info(
            "Processed %s Plex history entries from library %s on %s "
            "(owned=%s, Movies: %d, Episodes: %d, skipped other users: %d)",
            len(entries),
            section.get("title") or section.get("id"),
            section.get("server_name") or "unknown server",
            self._current_server_owned,
            len(self._movie_records),
            len(self._episode_records),
            self._skipped_user_count - skipped_users_before,
        )

        # Fetch and apply ratings from library items
        try:
            self._import_ratings_from_library(section, uri_used, token=section_token)
        except Exception as exc:
            logger.warning(
                "Failed to import ratings from Plex library items: %s",
                exception_summary(exc),
            )
            self.warnings.append(
                f"Failed to import ratings from library items: {exc}",
            )

    def _fetch_history_entries(
        self, connections: list[str], section_id: str | None, token: str | None = None
    ) -> tuple[list[dict], str]:
        """Pull all history pages up front to minimize per-page overhead, trying fallbacks."""
        effective_token = token or self.account.plex_token
        entries: list[dict] = []
        start = 0
        max_items = settings.PLEX_HISTORY_MAX_ITEMS
        if not max_items or max_items < 1:
            max_items = None  # No cap
        page_size = settings.PLEX_HISTORY_PAGE_SIZE
        failures = []
        uri_index = 0
        uri_used = ""

        while uri_index < len(connections):
            uri = connections[uri_index]
            try:
                while max_items is None or start < max_items:
                    page, total = plex_api.fetch_history(
                        effective_token,
                        uri,
                        section_id,
                        start,
                        size=page_size,
                    )

                    if not page:
                        break

                    entries.extend(page)
                    start += len(page)
                    if len(page) < page_size or start >= total:
                        break
                uri_used = uri
                break
            except plex_api.PlexAuthError as exc:
                msg = (
                    f"Authentication failed for Plex server at {uri}; "
                    "the token may be expired or this may be a shared server. "
                    "Reconnect Plex and try again."
                )
                raise MediaImportError(msg) from exc
            except plex_api.PlexClientError as exc:
                failures.append((uri, str(exc)))
                uri_index += 1
                start = 0
                entries = []
                continue

        logger.info(
            "Fetched %s Plex history entries for section %s (requested up to %s)",
            len(entries),
            section_id or "all",
            max_items if max_items is not None else "no limit",
        )
        if not entries and failures:
            msg = f"Could not fetch Plex history after trying connections: {failures}"
            raise MediaImportUnexpectedError(
                msg,
            )
        if max_items is None:
            return entries, uri_used
        return entries[:max_items], uri_used

    def _is_server_owned(self, machine_identifier) -> bool:
        """Return whether the user owns the server hosting this section."""
        for resource in self.resources:
            if resource.get("machine_identifier") == machine_identifier:
                owned = resource.get("owned")
                # Resources parsed before the owned flag existed stay owned
                return True if owned is None else bool(owned)
        # Unknown servers are treated as owned to preserve prior behavior
        return True

    def _connections_for_machine(self, machine_identifier):
        """Return the sorted connection URIs for a server."""
        uris: list[str] = []
        for resource in self.resources:
            if resource.get("machine_identifier") != machine_identifier:
                continue
            connections = resource.get("connections") or []
            sorted_conns = plex_api._sorted_connections(connections)
            uris.extend([c.get("uri") for c in sorted_conns if c.get("uri")])
        return uris

    def _process_entry(self, entry: dict, uri: str, section_type: str | None = None):
        """Process a single history entry."""
        metadata = self._build_metadata(entry)
        media_type = metadata.get("type")
        logger.debug(
            "Processing Plex history entry type=%s section=%s",
            media_type,
            section_type,
        )
        if not self._is_allowed_history_user(metadata):
            return
        metadata["Guid"] = self._normalize_guid_list(
            metadata.get("Guid") or metadata.get("guid"),
        )

        payload = {"Metadata": metadata}
        media_type = self.processor._get_media_type(payload)

        # Context-aware media type resolution
        if section_type == "show":
            # If in a TV library, prefer TV type but allow fallback to Movie
            # if season/episode info is missing.
            is_episode = bool(metadata.get("parentIndex") or metadata.get("index"))
            if not is_episode and (not media_type or media_type == MediaTypes.TV.value):
                # Try to see if it works better as a movie
                media_type = MediaTypes.MOVIE.value
            elif not media_type or media_type == MediaTypes.MOVIE.value:
                media_type = MediaTypes.TV.value
        elif section_type == "movie" and not media_type:
            media_type = MediaTypes.MOVIE.value

        if media_type == MediaTypes.MUSIC.value:
            self._process_music_entry(metadata)
            return

        if media_type not in (MediaTypes.MOVIE.value, MediaTypes.TV.value):
            self._track_unknown_type(metadata)
            return

        metadata, ids = self._ensure_external_ids(metadata, uri, section_type)
        logger.debug(
            "Resolved Plex history ID presence: %s",
            presence_map(ids, ("tmdb_id", "imdb_id", "tvdb_id", "anidb_id")),
        )

        if not self._has_external_ids(ids):
            logger.debug(
                "No external IDs found for Plex history entry",
            )

        if not self._has_external_ids(ids):
            # Last ditch effort for TV shows: if we forced it to MOVIE due to missing season
            # but it has no IDs, try it as TV if it's a show library.
            if (
                section_type == "show"
                and media_type == MediaTypes.MOVIE.value
                and not self._has_external_ids(ids)
            ):
                media_type = MediaTypes.TV.value
                metadata, ids = self._ensure_external_ids(metadata, uri, section_type)

            if not self._has_external_ids(ids):
                if section_type == "show":
                    # Proceed to _record_episode_entry which has its own title fallback
                    pass
                else:
                    self._track_missing_ids(metadata)
                    return

        if media_type == MediaTypes.MOVIE.value:
            # If we're processing as a movie but it's a show library,
            # make sure it doesn't have season/episode info that would make it a TV show
            if section_type == "show" and (
                metadata.get("parentIndex") or metadata.get("index")
            ):
                if not self._record_episode_entry(metadata, ids):
                    # Fallback: if episode recording failed (e.g. missing season/episode numbers),
                    # try recording as a movie. This handles cases like Anime Specials (Movies)
                    # that are in TV libraries but lack standard S/E numbering.
                    logger.debug(
                        "Episode recording failed during Plex import; falling back to movie",
                    )
                    self._record_movie_entry(metadata, ids)
            else:
                self._record_movie_entry(metadata, ids)
        elif not self._record_episode_entry(metadata, ids):
            # Fallback: if episode recording failed (e.g. missing season/episode numbers),
            # try recording as a movie. This handles cases like Anime Specials (Movies)
            # that are in TV libraries but lack standard S/E numbering.
            self._record_movie_entry(metadata, ids)

    def _process_music_entry(self, metadata: dict):
        """Replay music history entries through the webhook processor."""
        payload = {
            "event": "media.scrobble",
            "Account": {"title": self.account.plex_username or self.user.username},
            "Metadata": metadata,
            "_import_batch": True,
        }

        result = self.processor.process_payload(payload, self.user)
        if not result:
            return

        if getattr(result, "item", None):
            track_key = (result.item.media_id, result.item.source)
            self._unique_music_tracks.add(track_key)

        artist_id = getattr(result, "artist_id", None)
        if artist_id:
            self._artists_for_prefetch.add(artist_id)

        self.counts[MediaTypes.MUSIC.value] += 1

    def _is_allowed_history_user(self, metadata: dict) -> bool:
        """Return True when the history entry matches the selected Plex user."""
        account_id, username = self._extract_history_user(metadata)
        account_id_str = str(account_id) if account_id is not None else None
        logger.debug("Evaluating Plex history user against configured filters")

        if account_id_str == "1" and not username:
            # "1" is the server-local owner alias. On the user's own server
            # that is the connected account; on a friend's server it is the
            # friend, whose history must never import as this user's.
            if self._current_server_owned:
                if self._account_id:
                    account_id_str = str(self._account_id)
                username = (self.account.plex_username or "").strip() or None
            else:
                self._record_user_skip(
                    username="server owner",
                    account_id=account_id_str,
                )
                return False

        if not self._allowed_usernames and not self._account_id:
            if self._current_server_owned:
                return True
            self._warn_unverified_shared_server()
            self._record_user_skip(username=username, account_id=account_id_str)
            return False

        if self._allowed_usernames:
            if username:
                matches = username.lower() in self._allowed_usernames
                logger.debug(
                    "Checking Plex history username against configured username filters",
                )
                if not matches:
                    resolved_name = self._account_id_to_username.get(
                        account_id_str,
                        username,
                    )
                    self._record_user_skip(
                        username=resolved_name, account_id=account_id_str
                    )
                return matches

            if account_id_str:
                if self._allowed_account_ids:
                    matches = account_id_str in self._allowed_account_ids
                    logger.debug(
                        "Checking Plex history account ID against configured account filters",
                    )
                    if not matches:
                        resolved_name = self._account_id_to_username.get(
                            account_id_str,
                            username,
                        )
                        self._record_user_skip(
                            account_id=account_id_str,
                            username=resolved_name,
                        )
                    return matches

                logger.debug(
                    "Skipping Plex history entry; account ID mapping missing for configured usernames",
                )
                self._record_user_skip(username=username, account_id=account_id_str)
                return False

        if account_id_str and self._account_id:
            matches = account_id_str == str(self._account_id)
            logger.debug(
                "Checking Plex history account ID against connected account: %s",
                matches,
            )
            if not matches:
                resolved_name = self._account_id_to_username.get(
                    account_id_str,
                    username,
                )
                self._record_user_skip(
                    account_id=account_id_str, username=resolved_name
                )
            return matches

        logger.debug(
            "Skipping Plex history entry; unable to determine user (keys: %s)",
            sorted(metadata.keys()),
        )
        self._record_user_skip(username=username, account_id=account_id_str)
        return False

    def _extract_history_user(self, metadata: dict) -> tuple[str | None, str | None]:
        """Extract account/user identity from Plex history metadata."""
        account_id = (
            metadata.get("accountID")
            or metadata.get("accountId")
            or metadata.get("account_id")
        )

        username_candidates: list[str] = []
        for key in (
            "username",
            "user",
            "account",
            "accountName",
            "userName",
            "friendlyName",
        ):
            value = metadata.get(key)
            if isinstance(value, str) and value.strip():
                username_candidates.append(value.strip())

        for block_key in ("account", "Account", "user", "User"):
            block = metadata.get(block_key)
            if isinstance(block, dict):
                for key in ("title", "username", "name", "email", "friendlyName"):
                    value = block.get(key)
                    if isinstance(value, str) and value.strip():
                        username_candidates.append(value.strip())

        username = username_candidates[0] if username_candidates else None
        if not username and account_id is not None:
            username = self._account_id_to_username.get(str(account_id))
        return account_id, username

    def _warn_unverified_shared_server(self):
        """Warn once when shared-server history can't be attributed to a user."""
        message = (
            "Could not verify your Plex account identity; history from shared "
            "servers was skipped to avoid importing other users' watches. "
            "Reconnect Plex or set your Plex username in settings."
        )
        if message not in self.warnings:
            self.warnings.append(message)

    def _record_user_skip(self, username: str | None, account_id: str | None):
        """Track skipped entries that belong to other Plex users."""
        self._skipped_user_count += 1
        self.summary_counts["skipped_other_user"] += 1
        sample = None
        if username and account_id:
            sample = f"{username} (accountID={account_id})"
        elif username:
            sample = username
        elif account_id:
            sample = f"accountID={account_id}"
        if sample and len(self._skipped_user_samples) < MAX_SKIPPED_USER_SAMPLES:
            self._skipped_user_samples.add(sample)

    def _track_unknown_type(self, metadata: dict):
        """Record a skipped entry with an unsupported media type."""
        self.summary_counts["skipped_unknown_type"] += 1
        media_type = metadata.get("type") or "unknown"
        title = self._get_entry_title(metadata)
        self.warnings.append(
            f"Skipping Plex entry with unsupported type '{media_type}': {title}",
        )

    def _track_missing_ids(self, metadata: dict, reason: str | None = None):
        """Record a skipped entry due to missing identifiers."""
        self.summary_counts["skipped_missing_ids"] += 1
        title = self._get_entry_title(metadata)
        if reason:
            self.warnings.append(f"Skipping Plex entry for {title}: {reason}")
        else:
            self.warnings.append(f"Skipping Plex entry without external IDs: {title}")

    def _get_entry_title(self, metadata: dict) -> str:
        """Return the best-effort title for a Plex history entry."""
        return (
            metadata.get("title")
            or metadata.get("grandparentTitle")
            or metadata.get("parentTitle")
            or "Unknown title"
        )

    def _ensure_external_ids(
        self,
        metadata: dict,
        uri: str,
        section_type: str | None = None,
    ) -> tuple[dict, dict]:
        """Ensure external IDs are populated, fetching Plex metadata if needed."""
        # Allow title search fallback for TV/Movie libraries to improve matching yields
        allow_title_search = section_type in ("show", "movie")
        ids = self.processor.resolve_external_ids(
            {"Metadata": metadata},
            allow_title_search=allow_title_search,
        )
        if self._has_external_ids(ids):
            return metadata, ids

        rating_key = metadata.get("ratingKey") or metadata.get("ratingkey")
        if not rating_key:
            return metadata, ids

        if rating_key in self._metadata_cache:
            details = self._metadata_cache[rating_key]
        else:
            try:
                details = plex_api.fetch_metadata(
                    getattr(self, "_current_section_token", None)
                    or self.account.plex_token,
                    uri,
                    rating_key,
                )
            except plex_api.PlexAuthError as exc:
                msg = (
                    "Authentication failed fetching Plex metadata; "
                    "the token may be expired or this may be a shared server."
                )
                raise MediaImportError(
                    msg,
                ) from exc
            except plex_api.PlexClientError as exc:
                self.warnings.append(
                    f"Failed to fetch Plex metadata for {self._get_entry_title(metadata)}: {exc}",
                )
                details = None

            self._metadata_cache[rating_key] = details

        if not details:
            return metadata, ids

        merged = {**metadata, **details}
        merged["Guid"] = self._normalize_guid_list(
            merged.get("Guid") or merged.get("guid"),
        )
        ids = self.processor.resolve_external_ids(
            {"Metadata": merged},
            allow_title_search=False,
        )
        return merged, ids

    def _has_external_ids(self, ids: dict) -> bool:
        """Return True when any deterministic external ID is present."""
        return any(ids.get(key) for key in ("tmdb_id", "imdb_id", "tvdb_id"))

    def _resolve_show_level_ids(self, metadata: dict) -> tuple[dict, int | None]:
        """Fetch show-level external IDs and year via the grandparent metadata."""
        grandparent_key = metadata.get("grandparentRatingKey")
        if not grandparent_key:
            grandparent_path = metadata.get("grandparentKey") or ""
            grandparent_key = grandparent_path.rstrip("/").rsplit("/", 1)[-1] or None
        if not grandparent_key or not self._current_section_uri:
            return {}, None

        cache_key = f"show:{grandparent_key}"
        if cache_key in self._metadata_cache:
            details = self._metadata_cache[cache_key]
        else:
            try:
                section_token = getattr(self, "_current_section_token", None)
                details = plex_api.fetch_metadata(
                    section_token or self.account.plex_token,
                    self._current_section_uri,
                    str(grandparent_key),
                )
            except plex_api.PlexAuthError as exc:
                msg = (
                    "Authentication failed fetching Plex show metadata; "
                    "the token may be expired or this may be a shared server."
                )
                raise MediaImportError(
                    msg,
                ) from exc
            except plex_api.PlexClientError as exc:
                logger.debug(
                    "Failed to fetch Plex show metadata: %s",
                    exception_summary(exc),
                )
                details = None
            self._metadata_cache[cache_key] = details

        if not details:
            return {}, None

        show_payload = dict(details)
        show_payload["Guid"] = self._normalize_guid_list(
            show_payload.get("Guid") or show_payload.get("guid"),
        )
        show_payload["type"] = "show"
        ids = self.processor.resolve_external_ids(
            {"Metadata": show_payload},
            allow_title_search=False,
        )
        year = show_payload.get("year")
        try:
            year = int(year) if year is not None else None
        except (TypeError, ValueError):
            year = None
        return ids, year

    def _resolve_tv_via_title_search(
        self,
        ids: dict,
        series_title: str | None,
        show_year: int | None,
    ) -> str | None:
        """Last-resort title search, preferring a year-validated match."""
        if not series_title:
            return None

        media_id = None
        try:
            if show_year is not None:
                media_id, _, _ = self.processor._find_tv_media_id(
                    ids,
                    series_title,
                    allow_title_fallback=True,
                    year=show_year,
                )
            if not media_id:
                media_id, _, _ = self.processor._find_tv_media_id(
                    ids,
                    series_title,
                    allow_title_fallback=True,
                )
        except Exception as exc:
            logger.warning(
                "TV title fallback search failed during Plex import: %s",
                exception_summary(exc),
            )
            return None

        if media_id:
            self.warnings.append(
                f"{series_title}: matched by title search to "
                f"{Sources.TMDB.label} ID {media_id}; verify it is the right "
                "show if results look wrong.",
            )
        return media_id

    def _record_movie_entry(self, metadata: dict, ids: dict) -> bool:
        """Store a normalized movie history record for bulk import."""
        tmdb_id = self._resolve_movie_tmdb_id(ids)
        logger.debug(
            "Recording Plex movie entry with ID presence=%s",
            presence_map(ids, ("tmdb_id", "imdb_id")),
        )
        imdb_id = ids.get("imdb_id")
        if not tmdb_id:
            # Try title search fallback for movies if TMDB ID is missing
            title = self._get_entry_title(metadata)
            if title:
                logger.debug(
                    "Movie TMDB ID missing; attempting Plex title fallback search"
                )
                try:
                    from app.providers import services

                    search_results = services.search(
                        MediaTypes.MOVIE.value,
                        title,
                        page=1,
                    )
                    results = search_results.get("results") or []
                    if results:
                        tmdb_id = str(results[0].get("media_id"))
                        logger.info(
                            "Resolved Plex movie entry via title fallback search",
                        )
                except Exception as exc:
                    logger.warning(
                        "Movie title fallback search failed during Plex import: %s",
                        exception_summary(exc),
                    )

        if not tmdb_id:
            self._track_missing_ids(metadata, "missing TMDB/IMDB ID")
            return False

        tmdb_id = str(tmdb_id)
        if not self._should_process_media(MediaTypes.MOVIE.value, tmdb_id):
            self.summary_counts["skipped_existing"] += 1
            return True

        watched_at = self._get_played_at(metadata)
        if not watched_at:
            watched_at = timezone.now().replace(second=0, microsecond=0)

        # Plex history replays are treated as completed entries; partial progress is ignored.
        rating = self._normalize_rating(
            metadata.get("userRating"), metadata.get("title")
        )

        logger.debug("Recording normalized Plex movie history record")
        self._movie_records.append(
            {
                "tmdb_id": tmdb_id,
                "imdb_id": imdb_id,
                "watched_at": watched_at,
                "rating": rating,
                "title": metadata.get("title") or self._get_entry_title(metadata),
            },
        )
        self._movie_ids.add(tmdb_id)
        return True

    def _record_episode_entry(self, metadata: dict, ids: dict) -> bool:
        """
        Store a normalized episode history record for bulk import.

        Returns:
            bool: True if the entry was successfully recorded, False otherwise.
        """
        logger.debug(
            "Recording Plex episode entry with ID presence=%s",
            presence_map(ids, ("tmdb_id", "imdb_id", "tvdb_id")),
        )
        # Use grandparentTitle (Series Title) for Tv search, falling back to title
        series_search_title = metadata.get(
            "grandparentTitle",
        ) or self._get_entry_title(metadata)
        media_id = None
        found_season = None
        found_episode = None
        try:
            media_id, found_season, found_episode = self.processor._find_tv_media_id(
                ids,
                series_search_title,
            )
        except Exception as exc:
            logger.warning(
                "TV ID resolution failed during Plex import: %s",
                exception_summary(exc),
            )

        # Episode-level Guids often lack show IDs; resolve via the show's own
        # Plex metadata before falling back to ambiguous title search.
        show_ids: dict = {}
        show_year = None
        if not media_id or self._current_section_anime_hint:
            show_ids, show_year = self._resolve_show_level_ids(metadata)
        if not media_id and self._has_external_ids(show_ids):
            try:
                media_id, _, _ = self.processor._find_tv_media_id(
                    show_ids,
                    series_search_title,
                )
            except Exception as exc:
                logger.warning(
                    "Show-level TV ID resolution failed during Plex import: %s",
                    exception_summary(exc),
                )

        if not media_id:
            media_id = self._resolve_tv_via_title_search(
                ids,
                series_search_title,
                show_year,
            )

        if not media_id:
            logger.debug(
                "Failed to find TV match for Plex entry with ID presence=%s",
                presence_map(ids, ("tmdb_id", "imdb_id", "tvdb_id")),
            )
            self._track_missing_ids(metadata, "missing TMDB/TVDB/IMDB ID")
            return False

        plex_season_number = metadata.get("parentIndex")
        plex_episode_number = metadata.get("index")
        # tmdb.find on episode-level IDs returns TMDB numbering, which is what
        # the season payload validation below expects; Plex numbering follows
        # TVDB and is kept separately for anime mappings and remap fallbacks.
        season_number = found_season if found_season is not None else plex_season_number
        episode_number = (
            found_episode if found_episode is not None else plex_episode_number
        )
        if season_number is None or episode_number is None:
            # Don't log a warning yet; return False to allow fallback to Movie
            return False

        media_id = str(media_id)
        if not self._should_process_media(MediaTypes.TV.value, media_id):
            self.summary_counts["skipped_existing"] += 1
            return True

        watched_at = self._get_played_at(metadata)
        if not watched_at:
            watched_at = timezone.now().replace(second=0, microsecond=0)

        viewed_at_ts = metadata.get("viewedAt") or metadata.get("lastViewedAt")
        try:
            viewed_at_ts = int(viewed_at_ts) if viewed_at_ts is not None else None
        except (TypeError, ValueError):
            viewed_at_ts = None

        rating = self._normalize_rating(
            metadata.get("userRating"), metadata.get("title")
        )

        self._episode_records.append(
            {
                "tmdb_id": media_id,
                "external_ids": dict(ids),
                "season_number": season_number,
                "episode_number": episode_number,
                "source_season_number": plex_season_number,
                "source_episode_number": plex_episode_number,
                "tvdb_show_id": show_ids.get("tvdb_id"),
                "anime_section": self._current_section_anime_hint,
                "watched_at": watched_at,
                "viewed_at_ts": viewed_at_ts,
                "rating_key": metadata.get("ratingKey")
                or metadata.get("ratingkey"),
                "rating": rating,
                "title": metadata.get("title") or "Unknown Episode",
                "series_title": series_search_title,
                "guid": metadata.get("Guid") or metadata.get("guid"),
            },
        )
        self._tv_ids.add(media_id)
        return True

    def _get_played_at(self, metadata: dict):
        """Extract played-at timestamp if provided by Plex history."""
        ts = metadata.get("viewedAt") or metadata.get("lastViewedAt")
        try:
            ts_int = int(ts)
        except (TypeError, ValueError):
            return None

        played_at = datetime.fromtimestamp(ts_int, tz=UTC)
        return timezone.localtime(played_at)

    def _import_ratings_from_library(
        self, section: dict, uri: str, token: str | None = None
    ):
        """Fetch ratings from Plex library items and apply them to imported media instances.

        This complements history import by fetching ratings from library items,
        which may have ratings even if they weren't in the watch history.
        """
        effective_token = token or self.account.plex_token
        section_type = (section.get("type") or "").lower()
        if section_type not in ("movie", "show"):
            # Only import ratings for movies and TV shows
            return

        section_key = section.get("key") or section.get("id")
        if not section_key:
            logger.debug("No section key found, skipping rating import")
            return

        logger.info(
            "Fetching ratings from library items for section '%s'",
            section.get("title") or section.get("id"),
        )

        # Fetch all library items (paginated)
        ratings_map = {}  # Maps (source, media_id) -> rating
        start = 0
        page_size = settings.PLEX_HISTORY_PAGE_SIZE
        total_fetched = 0

        while True:
            try:
                items, total = plex_api.fetch_section_all_items(
                    effective_token,
                    uri,
                    str(section_key),
                    start=start,
                    size=page_size,
                )
            except plex_api.PlexAuthError as exc:
                msg = (
                    f"Authentication failed fetching ratings from Plex server at {uri}; "
                    "the token may be expired or this may be a shared server."
                )
                raise MediaImportError(msg) from exc
            except plex_api.PlexClientError as exc:
                logger.warning(
                    "Failed to fetch library items for rating import: %s",
                    exception_summary(exc),
                )
                break

            if not items:
                break

            for item in items:
                user_rating = item.get("userRating")
                if user_rating is None:
                    continue

                # Extract external IDs
                guids = item.get("Guid", [])
                if not guids:
                    single_guid = item.get("guid")
                    if single_guid:
                        guids = [{"id": single_guid}]

                external_ids = plex_api.extract_external_ids_from_guids(guids)

                # Normalize rating
                title = item.get("title") or "Unknown"
                normalized_rating = self._normalize_rating(user_rating, title)
                if normalized_rating is None:
                    continue

                # Store rating by external ID (prefer TMDB, fallback to IMDB/TVDB)
                if external_ids.get("tmdb_id"):
                    ratings_map[("tmdb", external_ids["tmdb_id"])] = normalized_rating
                if external_ids.get("imdb_id"):
                    ratings_map[("imdb", external_ids["imdb_id"])] = normalized_rating
                if external_ids.get("tvdb_id"):
                    ratings_map[("tvdb", external_ids["tvdb_id"])] = normalized_rating

            total_fetched += len(items)
            if len(items) < page_size or total_fetched >= total:
                break
            start += page_size

        if not ratings_map:
            logger.debug(
                "No ratings found in Plex library items for the selected section"
            )
            return

        logger.info(
            "Found %d ratings in library items for section '%s'",
            len(ratings_map),
            section.get("title") or section.get("id"),
        )

        # Store ratings to apply during bulk media creation
        self._library_ratings.update(ratings_map)

    def _build_anime_payload(self, record: dict) -> dict:
        """Build a minimal played Plex payload for anime mapping handlers."""
        plex_season = (
            record.get("source_season_number")
            if record.get("source_season_number") is not None
            else record["season_number"]
        )
        plex_episode = (
            record.get("source_episode_number")
            if record.get("source_episode_number") is not None
            else record["episode_number"]
        )
        metadata = {
            "type": "episode",
            "title": record["title"],
            "grandparentTitle": record["series_title"],
            "parentIndex": int(plex_season),
            "index": int(plex_episode),
            "ratingKey": record.get("rating_key"),
        }
        if record.get("viewed_at_ts"):
            metadata["viewedAt"] = int(record["viewed_at_ts"])
        if record.get("guid"):
            metadata["Guid"] = record["guid"]

        return {
            "event": "media.scrobble",
            "Account": {"title": self.account.plex_username or self.user.username},
            "Metadata": metadata,
            "_import_batch": True,
        }

    def _build_metadata(self, entry: dict) -> dict:
        """Normalize metadata shape expected by Plex webhook processor."""
        metadata = dict(entry)
        metadata.setdefault("Guid", entry.get("Guid") or [])

        # Standardize keys casing
        for key in list(metadata.keys()):
            lower_key = key[0].lower() + key[1:] if key and key[0].isupper() else key
            if lower_key not in metadata:
                metadata[lower_key] = metadata[key]

        # Fallback: some history rows come without ratingKey; use key if present
        if not metadata.get("ratingKey") and metadata.get("key"):
            metadata["ratingKey"] = metadata["key"]
            metadata["ratingkey"] = metadata["key"]

        # Ensure duration is set if available from nested Media block
        if not metadata.get("duration"):
            media_block = metadata.get("Media") or metadata.get("media")
            if isinstance(media_block, list) and media_block:
                dur = media_block[0].get("duration")
                if dur:
                    metadata["duration"] = dur
                elif media_block[0].get("Part"):
                    part = media_block[0]["Part"]
                    if isinstance(part, list) and part:
                        dur = part[0].get("duration")
                        if dur:
                            metadata["duration"] = dur

        # Cast numeric fields for consistency
        for key in (
            "parentIndex",
            "index",
            "duration",
            "viewedAt",
            "lastViewedAt",
            "viewOffset",
        ):
            if key in metadata and metadata[key] is not None:
                with contextlib.suppress(TypeError, ValueError):
                    metadata[key] = int(metadata[key])

        return metadata

    def _normalize_guid_list(self, guid_list):
        """Ensure GUID payload is a list of dicts with id keys."""
        if not guid_list:
            return []

        normalized = []
        if isinstance(guid_list, (dict, str)):
            guid_list = [guid_list]

        for guid in guid_list:
            if isinstance(guid, dict):
                guid_id = guid.get("id") or guid.get("Id") or guid.get("guid")
                if guid_id:
                    normalized.append({"id": guid_id})
            elif isinstance(guid, str):
                normalized.append({"id": guid})

        return normalized

    def _enqueue_fast_runtime_backfill(self):
        """Kick off fast runtime backfill immediately after import for statistics."""
        from app.tasks import fast_runtime_backfill_task  # local import to avoid cycles

        if MediaTypes.MUSIC.value not in self.counts:
            return  # No music imported, skip

        try:
            fast_runtime_backfill_task.delay(self.user.id)
        except Exception as exc:  # pragma: no cover - defensive
            logger.debug(
                "Could not enqueue fast runtime backfill task: %s",
                exception_summary(exc),
            )

    def _enqueue_music_enrichment(self):
        """Kick off a post-import enrichment/dedupe pass for this user's music."""
        from app.tasks import (  # local import to avoid cycles
            enrich_albums_task,
            enrich_music_library_task,
        )

        if MediaTypes.MUSIC.value not in self.counts:
            return  # No music imported, skip

        try:
            enrich_music_library_task.delay(self.user.id)
            # Schedule album enrichment to run after artist enrichment
            # This processes albums that don't have MBIDs (those that didn't match discography)
            enrich_albums_task.delay(self.user.id)
        except Exception as exc:  # pragma: no cover - defensive
            logger.debug(
                "Could not enqueue music enrichment task: %s",
                exception_summary(exc),
            )

    def _prefetch_collected_album_covers(self):
        """Fetch missing album covers after the full import completes."""
        if not self._artists_for_prefetch:
            return
        from app.models import (
            Artist,  # local import to avoid circular import at module load
        )

        for artist_id in self._artists_for_prefetch:
            try:
                artist = Artist.objects.get(id=artist_id)
            except Artist.DoesNotExist:
                continue
            try:
                prefetch_album_covers(artist, limit=None)
            except Exception as exc:  # pragma: no cover - defensive network guard
                logger.debug(
                    "Cover prefetch failed after Plex import: %s",
                    exception_summary(exc),
                )
