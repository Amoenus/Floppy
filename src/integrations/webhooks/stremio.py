"""Stremio scrobbler addon processor.

Stremio has no playback webhook, so Yamtrack serves a minimal addon whose
``subtitles`` resource is requested when playback starts. The payload built
by the addon views is ``{"id": "tt123" | "tt123:season:episode", "type":
"movie" | "series"}``. That is a start-only signal: media is marked
in-progress here, and the recurring Stremio library sync flips items to
completed from real library state.
"""

import logging

from app.models import MediaTypes

from .base import BaseWebhookProcessor

logger = logging.getLogger(__name__)

VIDEO_ID_PARTS = 3


class StremioWebhookProcessor(BaseWebhookProcessor):
    """Processor for Stremio addon playback-start events."""

    MEDIA_TYPE_MAPPING = {
        "series": MediaTypes.TV.value,
        "movie": MediaTypes.MOVIE.value,
    }

    def process_payload(self, payload, user):
        """Process a playback-start event from the Stremio addon."""
        ids = self._extract_external_ids(payload)
        if not ids["imdb_id"]:
            logger.warning(
                "Ignoring Stremio scrobble with unsupported id: %s",
                payload.get("id"),
            )
            return

        self._process_media(payload, user, ids)

    def _is_supported_event(self, event_type):  # noqa: ARG002
        return True

    def _is_played(self, payload):  # noqa: ARG002
        # The subtitles request only proves playback started; completion is
        # picked up by the recurring library sync.
        return False

    def _get_media_type(self, payload):
        return self.MEDIA_TYPE_MAPPING.get(payload.get("type"))

    def _get_media_title(self, payload):
        return payload.get("id")

    def _extract_external_ids(self, payload):
        media_id = payload.get("id", "")
        imdb_id = media_id.split(":")[0] if media_id.startswith("tt") else None
        return {
            "tmdb_id": None,
            "imdb_id": imdb_id,
            "tvdb_id": None,
        }

    def _extract_season_episode_from_payload(self, payload):
        """Extract season and episode from a ``tt123:s:e`` video id."""
        parts = payload.get("id", "").split(":")
        if len(parts) != VIDEO_ID_PARTS:
            return None, None
        try:
            return int(parts[1]), int(parts[2])
        except ValueError:
            return None, None

    def _extract_series_title(self, payload):  # noqa: ARG002
        return None
