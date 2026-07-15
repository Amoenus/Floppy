"""Thin async REST client for the Yamtrack API used by the MCP tools.

Configured entirely from environment variables so the server can be pointed
at any Yamtrack instance:

- YAMTRACK_URL: base URL of the instance, e.g. https://yamtrack.example.com
- YAMTRACK_TOKEN: the user's API token (Settings -> Advanced in the web UI),
  sent as an X-API-Key header.
"""

from __future__ import annotations

import os
from typing import Any

import httpx

DEFAULT_TIMEOUT = 30.0


class YamtrackConfigError(RuntimeError):
    """Required environment variables are missing."""


class YamtrackAPIError(RuntimeError):
    """The Yamtrack API returned an error response."""

    def __init__(self, status_code: int, detail: Any):
        """Store the failed response's status code and parsed body."""
        self.status_code = status_code
        self.detail = detail
        super().__init__(f"Yamtrack API error {status_code}: {detail}")


def _base_url() -> str:
    url = os.environ.get("YAMTRACK_URL")
    if not url:
        msg = "YAMTRACK_URL environment variable is required."
        raise YamtrackConfigError(msg)
    return url.rstrip("/")


def _token() -> str:
    token = os.environ.get("YAMTRACK_TOKEN")
    if not token:
        msg = "YAMTRACK_TOKEN environment variable is required."
        raise YamtrackConfigError(msg)
    return token


class YamtrackClient:
    """Async client for /api/v1/ endpoints, reused across tool calls."""

    def __init__(self) -> None:
        """Create the client with no underlying connection yet (lazy)."""
        self._client: httpx.AsyncClient | None = None

    def _ensure_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=f"{_base_url()}/api/v1/",
                headers={"X-API-Key": _token()},
                timeout=DEFAULT_TIMEOUT,
            )
        return self._client

    async def aclose(self) -> None:
        """Close the underlying HTTP connection, if one was opened."""
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
        files: dict[str, Any] | None = None,
    ) -> Any:
        """Issue a request and return the parsed JSON body (or None for 204)."""
        client = self._ensure_client()
        # Drop None values so optional filters don't get sent as "None".
        clean_params = (
            {k: v for k, v in params.items() if v is not None} if params else None
        )
        response = await client.request(
            method,
            path.lstrip("/"),
            params=clean_params,
            json=json,
            files=files,
        )
        if response.status_code == httpx.codes.NO_CONTENT:
            return None
        try:
            body = response.json()
        except ValueError:
            body = response.text
        if response.is_error:
            raise YamtrackAPIError(response.status_code, body)
        return body


_client: YamtrackClient | None = None


def get_client() -> YamtrackClient:
    """Return the process-wide client instance (created lazily)."""
    global _client  # noqa: PLW0603 — single lazy module-level singleton
    if _client is None:
        _client = YamtrackClient()
    return _client
