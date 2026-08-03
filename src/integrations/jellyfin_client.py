"""Thin REST client for pushing watched state to a Jellyfin server."""

import logging
from http import HTTPStatus

import requests

logger = logging.getLogger(__name__)

LIBRARY_PAGE_SIZE = 500


class JellyfinClientError(Exception):
    """Base Jellyfin API error."""


class JellyfinAuthError(JellyfinClientError):
    """Raised when the Jellyfin API key is invalid or unauthorized."""


class JellyfinClient:
    """Client for the subset of the Jellyfin REST API needed to push watched state."""

    def __init__(self, base_url: str, api_key: str, user_id: str | None = None):
        """Store the extra keyword arguments this form needs."""
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.user_id = user_id

    def _headers(self) -> dict[str, str]:
        return {
            "X-Emby-Token": self.api_key,
            "Accept": "application/json",
        }

    def _request(self, method: str, path: str, **kwargs):
        try:
            response = requests.request(
                method,
                f"{self.base_url}{path}",
                headers=self._headers(),
                timeout=15,
                **kwargs,
            )
        except requests.RequestException as exc:
            msg = f"Could not reach Jellyfin: {exc}"
            raise JellyfinClientError(msg) from exc

        if response.status_code == HTTPStatus.UNAUTHORIZED:
            msg = "Jellyfin API key is invalid or unauthorized"
            raise JellyfinAuthError(msg)
        if response.status_code >= HTTPStatus.BAD_REQUEST:
            body_snippet = (response.text or "").strip()[:200]
            logger.warning(
                "Jellyfin request failed: %s %s -> %s %s",
                method,
                path,
                response.status_code,
                body_snippet,
            )
            message = f"Jellyfin request failed ({response.status_code}) for {path}"
            if body_snippet:
                message = f"{message}: {body_snippet}"
            raise JellyfinClientError(message)
        return response

    def healthcheck(self) -> dict:
        """Verify the server is reachable and the API key is valid."""
        return self._request("GET", "/System/Info").json()

    def get_current_user(self) -> dict | None:
        """Resolve the Jellyfin user tied to this API key, if any.

        Dashboard API keys have no user context, so Jellyfin answers
        /Users/Me with a 4xx; treat that as "no user" rather than an error
        so callers can fall back to a username lookup.
        """
        try:
            response = self._request("GET", "/Users/Me")
        except JellyfinAuthError:
            raise
        except JellyfinClientError:
            return None
        if not response.content:
            return None
        return response.json()

    def find_user_by_name(self, username: str) -> dict | None:
        """Fall back lookup for server-admin API keys that can't resolve Users/Me."""
        users = self._request("GET", "/Users").json()
        for user in users:
            if str(user.get("Name", "")).strip().lower() == username.strip().lower():
                return user
        return None

    def get_views(self) -> list[dict]:
        """Return the user's top-level libraries (Movies, Shows, Music, ...)."""
        if not self.user_id:
            msg = "Jellyfin user id is not set"
            raise JellyfinClientError(msg)
        payload = self._request("GET", f"/Users/{self.user_id}/Views").json()
        return payload.get("Items") or []

    def iter_library_items(
        self,
        item_types: str = "Movie,Episode,Series",
        fields: str = "ProviderIds",
        parent_id: str | None = None,
        filters: str | None = None,
    ):
        """Yield library items with provider ids and play state.

        Defaults match what the push sync needs; the importer widens
        ``fields`` to include UserData and scopes to a single library
        with ``parent_id``.
        """
        if not self.user_id:
            msg = "Jellyfin user id is not set"
            raise JellyfinClientError(msg)

        start_index = 0
        while True:
            params = {
                "Recursive": "true",
                "IncludeItemTypes": item_types,
                "Fields": fields,
                "StartIndex": start_index,
                "Limit": LIBRARY_PAGE_SIZE,
            }
            if parent_id:
                params["ParentId"] = parent_id
            if filters:
                params["Filters"] = filters

            payload = self._request(
                "GET",
                f"/Users/{self.user_id}/Items",
                params=params,
            ).json()

            items = payload.get("Items") or []
            yield from items

            start_index += len(items)
            total = payload.get("TotalRecordCount", start_index)
            if not items or start_index >= total:
                break

    def fetch_playback_activity(self) -> list[dict] | None:
        """Return per-play rows from the Playback Reporting plugin.

        The plugin is optional, so any failure means "not installed" rather
        than a broken server: callers fall back to per-item LastPlayedDate.
        Returns None when unavailable, else a list of row dicts.
        """
        if not self.user_id:
            msg = "Jellyfin user id is not set"
            raise JellyfinClientError(msg)

        query = (
            "SELECT ItemId, ItemType, DateCreated, PlayDuration "  # noqa: S608
            "FROM PlaybackActivity "
            f"WHERE UserId = '{self.user_id}'"
        )
        try:
            payload = self._request(
                "POST",
                "/user_usage_stats/submit_custom_query",
                json={"CustomQueryString": query, "ReplaceUserId": False},
            ).json()
        except (JellyfinClientError, ValueError):
            logger.info(
                "Jellyfin Playback Reporting plugin unavailable; "
                "falling back to per-item last-played dates",
            )
            return None

        # The plugin spells the key "colums" (sic) in most releases.
        columns = payload.get("colums") or payload.get("columns") or []
        results = payload.get("results") or []
        if not columns:
            return None
        return [dict(zip(columns, row, strict=False)) for row in results]

    def mark_played(self, item_id: str) -> None:
        """Mark a Jellyfin item as played for the connected user."""
        if not self.user_id:
            msg = "Jellyfin user id is not set"
            raise JellyfinClientError(msg)
        self._request("POST", f"/Users/{self.user_id}/PlayedItems/{item_id}")

    def mark_unplayed(self, item_id: str) -> None:
        """Mark a Jellyfin item as unplayed for the connected user."""
        if not self.user_id:
            msg = "Jellyfin user id is not set"
            raise JellyfinClientError(msg)
        self._request("DELETE", f"/Users/{self.user_id}/PlayedItems/{item_id}")
