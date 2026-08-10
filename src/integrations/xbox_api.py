"""OpenXBL (xbl.io) API client for Xbox Live library data.

Xbox Live has no public API, so this goes through OpenXBL, a third-party
gateway. The user signs in at https://xbl.io with their Microsoft account and
copies their personal API key, which is sent as the ``X-Authorization`` header.

Endpoints used:

- ``GET  /api/v2/account``                     -> the key owner's profile (xuid, gamertag)
- ``GET  /api/v2/player/titleHistory/{xuid}``  -> recently played titles + ``lastTimePlayed``
- ``GET  /api/v2/achievements/player/{xuid}``  -> every title with achievement data
- ``POST /api/v2/player/stats``                -> per-title ``MinutesPlayed``

Xbox exposes no purchase library, so the union of the two title endpoints is the
closest available equivalent to "games owned": everything the account has played.
"""

import logging

import requests

from app.providers import services
from integrations.imports.helpers import MediaImportError

logger = logging.getLogger(__name__)

XBOX_API_BASE_URL = "https://xbl.io/api/v2"
PROVIDER = "OpenXBL"

# Xbox Live's batch user-stats endpoint. Titles are only included in the
# response when they actually publish the stat, so a missing entry means
# "unknown", not "zero".
MINUTES_PLAYED_STAT = "MinutesPlayed"
STATS_BATCH_SIZE = 100


def _headers(api_key):
    """Return the auth headers for an OpenXBL request."""
    return {"X-Authorization": api_key, "Accept": "application/json"}


def _content(response):
    """Unwrap OpenXBL's ``{"content": ..., "code": ...}`` envelope.

    Every v2 endpoint wraps its payload this way, including the ones whose
    documented examples show the bare object.
    """
    if isinstance(response, dict) and "content" in response:
        return response["content"]
    return response


def _unwrap(response, key):
    """Return ``payload[key]`` from inside the response envelope."""
    payload = _content(response)
    if isinstance(payload, dict):
        return payload.get(key) or []
    return []


def _describe(response):
    """Summarize a response's shape for error messages, without leaking values."""
    payload = _content(response)
    if isinstance(payload, dict):
        return f"object with keys {sorted(payload)}"
    if isinstance(payload, list):
        return f"list[{len(payload)}]"
    return type(payload).__name__


def _request(api_key, method, path, params=None):
    """Call OpenXBL and translate HTTP failures into import errors."""
    try:
        return services.api_request(
            PROVIDER,
            method,
            f"{XBOX_API_BASE_URL}{path}",
            params=params,
            headers=_headers(api_key),
        )
    except requests.HTTPError as e:
        status_code = e.response.status_code
        if status_code in {
            requests.codes.unauthorized,
            requests.codes.payment_required,
        }:
            msg = "Invalid or expired OpenXBL API key. Reconnect your Xbox account."
            raise MediaImportError(msg) from e
        if status_code == requests.codes.forbidden:
            msg = "OpenXBL denied access to this Xbox profile. Check its privacy settings."
            raise MediaImportError(msg) from e
        if status_code == requests.codes.too_many_requests:
            msg = "OpenXBL rate limit exceeded. Please try again later."
            raise MediaImportError(msg) from e
        msg = f"OpenXBL API error: {status_code}"
        raise MediaImportError(msg) from e


def get_account(api_key):
    """Return ``(xuid, gamertag)`` for the owner of the API key."""
    response = _request(api_key, "GET", "/account")

    profile_users = _unwrap(response, "profileUsers")
    if not profile_users:
        logger.error("Unexpected OpenXBL /account response: %s", _describe(response))
        msg = (
            "OpenXBL did not return a profile for this API key "
            f"(response was a {_describe(response)})."
        )
        raise MediaImportError(msg)

    profile = profile_users[0]
    settings_by_id = {
        setting.get("id"): setting.get("value")
        for setting in profile.get("settings") or []
    }
    return profile.get("id", ""), settings_by_id.get("Gamertag", "")


def get_played_titles(api_key, xuid):
    """Return every title the account has played, keyed by title ID.

    Merges ``titleHistory`` (recent, and the only source of ``lastTimePlayed``)
    with the per-player achievement list, which reaches further back.
    """
    titles = {}

    for path in (
        f"/achievements/player/{xuid}",
        f"/player/titleHistory/{xuid}",
    ):
        response = _request(api_key, "GET", path)
        parsed = _unwrap(response, "titles")
        if not parsed:
            # A 200 with no parseable titles is worth a shape note in the log:
            # it distinguishes an empty library from an unexpected payload.
            logger.warning(
                "OpenXBL %s returned no titles (%s)",
                path,
                _describe(response),
            )
        for title in parsed:
            title_id = str(title.get("titleId") or "")
            if not title_id:
                continue
            titles[title_id] = {**titles.get(title_id, {}), **title}

    logger.info("Found %d played Xbox titles for xuid %s", len(titles), xuid)
    return titles


def get_minutes_played(api_key, xuid, title_ids):
    """Return ``{title_id: minutes}`` for titles that publish the stat."""
    minutes = {}
    title_ids = list(title_ids)

    for start in range(0, len(title_ids), STATS_BATCH_SIZE):
        batch = title_ids[start : start + STATS_BATCH_SIZE]
        response = _request(
            api_key,
            "POST",
            "/player/stats",
            params={
                "xuids": [str(xuid)],
                "stats": [
                    {"name": MINUTES_PLAYED_STAT, "titleId": title_id}
                    for title_id in batch
                ],
            },
        )
        minutes.update(_parse_stats(response))

    logger.info(
        "Xbox reported MinutesPlayed for %d of %d titles",
        len(minutes),
        len(title_ids),
    )
    return minutes


def _parse_stats(response):
    """Extract ``{title_id: minutes}`` from a batch user-stats response."""
    parsed = {}

    for stat_list in _unwrap(response, "statlistscollection"):
        if not isinstance(stat_list, dict):
            continue
        for stat in stat_list.get("stats") or []:
            if stat.get("name") != MINUTES_PLAYED_STAT:
                continue
            title_id = str(stat.get("titleid") or stat.get("titleId") or "")
            try:
                value = int(float(stat.get("value")))
            except (TypeError, ValueError):
                continue
            if title_id and value >= 0:
                parsed[title_id] = value

    return parsed
