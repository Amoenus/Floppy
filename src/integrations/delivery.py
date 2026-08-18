"""Deduplication and delivery receipt gateway for integration events."""

import hashlib
import json
import logging
from collections.abc import Callable
from http import HTTPStatus as HTTP  # noqa: N814
from typing import Any

from django.core.serializers.json import DjangoJSONEncoder
from django.db import IntegrityError, transaction
from rest_framework.response import Response

from .models import IntegrationEventReceipt, IntegrationToken

logger = logging.getLogger(__name__)



def calculate_payload_digest(payload: Any) -> str:
    """Calculate deterministic SHA-256 hex digest of sorted canonical JSON."""
    if isinstance(payload, (dict, list)):
        json_str = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    elif isinstance(payload, str):
        try:
            parsed = json.loads(payload)
            if isinstance(parsed, (dict, list)):
                json_str = json.dumps(parsed, sort_keys=True, separators=(",", ":"), default=str)
            else:
                json_str = payload
        except (ValueError, TypeError):
            json_str = payload
    elif isinstance(payload, bytes):
        try:
            parsed = json.loads(payload.decode("utf-8"))
            if isinstance(parsed, (dict, list)):
                json_str = json.dumps(parsed, sort_keys=True, separators=(",", ":"), default=str)
            else:
                json_str = payload.decode("utf-8", errors="replace")
        except Exception:
            json_str = payload.decode("utf-8", errors="replace")
    else:
        try:
            json_str = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
        except Exception:
            json_str = str(payload)

    return hashlib.sha256(json_str.encode("utf-8")).hexdigest()


def get_or_record_receipt(
    user: Any,
    client_event_id: str,
    payload: Any,
    execute_fn: Callable[[], Response],
    token: IntegrationToken | None = None,
) -> tuple[Response, bool]:
    """Retrieve existing cached response or execute operation and persist receipt.

    Returns a tuple of (Response, is_replay).
    """
    digest = calculate_payload_digest(payload)

    try:
        receipt = IntegrationEventReceipt.objects.get(
            user=user,
            client_event_id=client_event_id,
        )
    except IntegrationEventReceipt.DoesNotExist:
        receipt = None

    if receipt is not None:
        if receipt.payload_digest == digest:
            replay_body = None if receipt.response_status_code == HTTP.NO_CONTENT else receipt.response_body
            return (Response(replay_body, status=receipt.response_status_code), True)
        return (
            Response(
                {
                    "error": {
                        "type": "conflict_error",
                        "code": "idempotency_conflict",
                        "message": (
                            "The provided Idempotency-Key has already been used "
                            "with a different request payload."
                        ),
                        "param": "Idempotency-Key",
                        "correlation_id": f"rec_{client_event_id}",
                    },
                },
                status=HTTP.CONFLICT,
            ),
            False,
        )

    response = execute_fn()

    if response.status_code < HTTP.INTERNAL_SERVER_ERROR:
        if response.data is not None:
            try:
                response_data = json.loads(json.dumps(response.data, cls=DjangoJSONEncoder))
            except Exception:
                response_data = response.data
        else:
            response_data = {}

        try:
            with transaction.atomic():
                IntegrationEventReceipt.objects.create(
                    user=user,
                    token=token,
                    client_event_id=client_event_id,
                    payload_digest=digest,
                    response_status_code=response.status_code,
                    response_body=response_data,
                )

        except IntegrityError:
            receipt = IntegrationEventReceipt.objects.filter(
                user=user,
                client_event_id=client_event_id,
            ).first()
            if receipt is not None:
                if receipt.payload_digest == digest:
                    replay_body = None if receipt.response_status_code == HTTP.NO_CONTENT else receipt.response_body
                    return (Response(replay_body, status=receipt.response_status_code), True)
                return (
                    Response(
                        {
                            "error": {
                                "type": "conflict_error",
                                "code": "idempotency_conflict",
                                "message": (
                                    "The provided Idempotency-Key has already been used "
                                    "with a different request payload."
                                ),
                                "param": "Idempotency-Key",
                                "correlation_id": f"rec_{client_event_id}",
                            },
                        },
                        status=HTTP.CONFLICT,
                    ),
                    False,
                )

    return (response, False)
