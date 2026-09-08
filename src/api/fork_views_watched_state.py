# FORK: canonical watched-state endpoints for external synchronizing clients.
# Deliberately separate from the playback and history endpoints: setting
# unwatched is not deleting history, and the two must not share a route.
import logging
from http import HTTPStatus as HTTP  # noqa: N814

from django.utils import timezone
from rest_framework import views as drf_views
from rest_framework.response import Response

from app.models import WatchStateOrigin
from app.services.watch_state import (
    RevisionConflictError,
    changes_since,
    effective_state,
    record_state_change,
)
from integrations.models import (
    StateConflict,
    StateConflictStatus,
    SyncBinding,
)

from .helpers import check_source_type, check_valid_type, resolve_item_queryset

logger = logging.getLogger(__name__)

MAX_CHANGE_PAGE = 200


def _serialize_state(state, item):
    """Return the public shape of one canonical state."""
    if state is None:
        return {
            "media_id": item.media_id,
            "source": item.source,
            "media_type": item.media_type,
            "watched": False,
            "play_count": 0,
            "first_watched_at": None,
            "last_watched_at": None,
            "revision": 0,
            "conflicted": False,
            "provenance": None,
        }

    return {
        "media_id": item.media_id,
        "source": item.source,
        "media_type": item.media_type,
        "watched": state.watched,
        "play_count": state.play_count,
        "first_watched_at": state.first_watched_at,
        "last_watched_at": state.last_watched_at,
        "revision": state.revision,
        "conflicted": state.conflicted,
        "provenance": {
            # Explicit and inferred manual changes stay distinguishable: a
            # client showing "you marked this watched" must not say so about a
            # state Floppy inferred from a reconciliation pass.
            "origin_kind": state.origin_kind,
            "origin_key": state.origin_key,
            "updated_at": state.updated_at,
        },
    }


def _resolve_item(request, media_type, source, media_id):
    """Return the addressed item, or an error response."""
    if not check_valid_type(media_type):
        return None, Response(
            {"detail": f"Invalid media type: {media_type}"},
            status=HTTP.BAD_REQUEST,
        )
    if not check_source_type(media_type, source):
        return None, Response(
            {"detail": f"Cannot query `{source}` for `{media_type}` media type"},
            status=HTTP.BAD_REQUEST,
        )

    season_number = request.query_params.get("season_number")
    episode_number = request.query_params.get("episode_number")
    try:
        season_number = int(season_number) if season_number is not None else None
        episode_number = int(episode_number) if episode_number is not None else None
    except (TypeError, ValueError):
        return None, Response(
            {"detail": "season_number and episode_number must be integers."},
            status=HTTP.BAD_REQUEST,
        )

    queryset = resolve_item_queryset(
        media_id,
        source,
        media_type,
        season_number=season_number,
        episode_number=episode_number,
        library_media_type=request.query_params.get("library_media_type"),
    )

    # More than one candidate means the address was ambiguous. Picking one
    # would eventually write to the wrong library bucket.
    matches = list(queryset[:2])
    if not matches:
        return None, Response(
            {"detail": "No matching item."},
            status=HTTP.NOT_FOUND,
        )
    if len(matches) > 1:
        return None, Response(
            {"detail": "Ambiguous item; pass library_media_type."},
            status=HTTP.CONFLICT,
        )
    return matches[0], None


# /api/v1/media/[media_type]/[source]/[media_id]/watched-state/
class WatchedStateView(drf_views.APIView):
    """Read or set the canonical watched state for one item."""

    def get(self, request, media_type, source, media_id):
        """Return effective state and its provenance."""
        item, error = _resolve_item(request, media_type, source, media_id)
        if error is not None:
            return error

        state = effective_state(request.user, item)
        return Response(_serialize_state(state, item), status=HTTP.OK)

    def put(self, request, media_type, source, media_id):
        """Set watched state explicitly.

        This is a state assertion, not a play. It records no playback session
        and removes no history, which is what keeps "mark unwatched" distinct
        from "delete history".
        """
        item, error = _resolve_item(request, media_type, source, media_id)
        if error is not None:
            return error

        watched = request.data.get("watched")
        if not isinstance(watched, bool):
            return Response(
                {"detail": "`watched` must be a boolean."},
                status=HTTP.BAD_REQUEST,
            )

        expected_revision = request.headers.get("If-Match")
        if expected_revision is not None:
            try:
                expected_revision = int(expected_revision)
            except ValueError:
                return Response(
                    {"detail": "If-Match must be an integer revision."},
                    status=HTTP.BAD_REQUEST,
                )

        idempotency_key = request.headers.get("Idempotency-Key") or request.data.get(
            "client_event_id",
        )

        try:
            result = record_state_change(
                request.user,
                item,
                watched=watched,
                play_count=request.data.get("play_count"),
                watched_at=timezone.now() if watched else None,
                origin_kind=WatchStateOrigin.LOCAL_API.value,
                origin_key="api",
                origin_event_id=idempotency_key,
                expected_revision=expected_revision,
            )
        except RevisionConflictError as error:
            return Response(
                {
                    "detail": str(error),
                    "revision": effective_state(request.user, item).revision,
                },
                status=HTTP.CONFLICT,
            )

        payload = _serialize_state(
            result.state or effective_state(request.user, item),
            item,
        )
        payload["replayed"] = result.replayed
        payload["unchanged"] = result.unchanged
        return Response(payload, status=HTTP.OK)


# /api/v1/sync/changes/
class WatchedStateChangeFeedView(drf_views.APIView):
    """Serve the ordered change feed for a synchronizing client."""

    def get(self, request):
        """Return changes after a cursor, in server order.

        The cursor is a server sequence, which is allocated at commit time, so
        paginating by it cannot skip a change that committed late.
        """
        raw_cursor = request.query_params.get("cursor", "0")
        try:
            cursor = int(raw_cursor)
        except ValueError:
            return Response(
                {"detail": "cursor must be an integer sequence."},
                status=HTTP.BAD_REQUEST,
            )

        try:
            limit = min(int(request.query_params.get("limit", 100)), MAX_CHANGE_PAGE)
        except ValueError:
            return Response(
                {"detail": "limit must be an integer."},
                status=HTTP.BAD_REQUEST,
            )

        changes = changes_since(request.user, cursor, limit=limit)
        results = [
            {
                "sequence": change.sequence,
                "revision": change.revision,
                "previous_revision": change.previous_revision,
                "kind": change.kind,
                "watched": change.watched,
                "play_count": change.play_count,
                "watched_at": change.watched_at,
                "media_id": change.item.media_id if change.item else None,
                "source": change.item.source if change.item else None,
                "media_type": change.item.media_type if change.item else None,
                "origin_kind": change.origin_kind,
                "correlation_id": str(change.correlation_id),
            }
            for change in changes
        ]

        return Response(
            {
                "results": results,
                "next_cursor": results[-1]["sequence"] if results else cursor,
                "has_more": len(results) == limit,
            },
            status=HTTP.OK,
        )


# /api/v1/sync/connections/
class SyncConnectionsView(drf_views.APIView):
    """Report what each connection is actually allowed and able to do."""

    def get(self, request):
        """Return connections, their directions, and unavailable capabilities."""
        from integrations.state.outbound import get_adapter

        results = []
        for binding in SyncBinding.objects.filter(user=request.user):
            adapter = get_adapter(binding)
            supported = set(adapter.CAPABILITIES) if adapter is not None else set()
            approved = set(binding.approved_capabilities or [])

            results.append(
                {
                    "id": binding.pk,
                    "client_kind": binding.client_kind,
                    "label": binding.label,
                    "status": binding.status,
                    "directions": binding.approved_directions or [],
                    "capabilities": sorted(approved & supported),
                    # Named explicitly rather than omitted: a direction the
                    # user asked for and cannot have is a capability
                    # limitation, and saying nothing reads as success.
                    "unavailable_capabilities": sorted(approved - supported),
                    "last_reconciled_at": binding.last_reconciled_at,
                    "pending_deliveries": binding.deliveries.filter(
                        status="pending",
                    ).count(),
                    "open_conflicts": binding.conflicts.filter(
                        status=StateConflictStatus.OPEN.value,
                    ).count(),
                },
            )

        return Response({"results": results}, status=HTTP.OK)


# /api/v1/sync/conflicts/
class SyncConflictsView(drf_views.APIView):
    """List disagreements waiting for a person."""

    def get(self, request):
        """Return open conflicts."""
        conflicts = StateConflict.objects.filter(
            user=request.user,
            status=StateConflictStatus.OPEN.value,
        ).select_related("item", "binding")

        return Response(
            {
                "results": [
                    {
                        "id": conflict.pk,
                        "reason": conflict.reason,
                        "media_id": conflict.item.media_id,
                        "source": conflict.item.source,
                        "media_type": conflict.item.media_type,
                        "client_kind": conflict.binding.client_kind,
                        "local": conflict.local_snapshot,
                        "remote": conflict.remote_snapshot,
                        "base": conflict.base_snapshot,
                        "occurrence_count": conflict.occurrence_count,
                        "updated_at": conflict.updated_at,
                    }
                    for conflict in conflicts
                ],
            },
            status=HTTP.OK,
        )


# /api/v1/sync/conflicts/[conflict_id]/resolve/
class SyncConflictResolveView(drf_views.APIView):
    """Settle one disagreement with the state a person chose."""

    def post(self, request, conflict_id):
        """Resolve a conflict, creating a new revision."""
        from integrations.state.apply import resolve_conflict

        conflict = StateConflict.objects.filter(
            pk=conflict_id,
            user=request.user,
            status=StateConflictStatus.OPEN.value,
        ).first()
        if conflict is None:
            return Response(
                {"detail": "No open conflict with that id."},
                status=HTTP.NOT_FOUND,
            )

        watched = request.data.get("watched")
        if not isinstance(watched, bool):
            return Response(
                {"detail": "`watched` must be a boolean."},
                status=HTTP.BAD_REQUEST,
            )

        result = resolve_conflict(
            conflict,
            watched=watched,
            play_count=request.data.get("play_count"),
        )

        return Response(
            _serialize_state(result.state, conflict.item),
            status=HTTP.OK,
        )
