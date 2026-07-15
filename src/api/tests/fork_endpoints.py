# FORK: endpoint cases for fork-only routes, appended to endpoints.py's
# get_endpoint_cases() with a single line to keep the upstream file mergeable.
from .endpoints import EndpointCase


def get_fork_endpoint_cases() -> list[EndpointCase]:
    """Return endpoint cases for every fork-only route and method."""
    return [
        EndpointCase(
            "post",
            "api_media_progress",
            args=("movie", "tmdb", 1),
            payload={"operation": "increase"},
        ),
        EndpointCase(
            "post",
            "api_media_season_progress",
            args=("tv", "tmdb", 1, 1),
            payload={"operation": "increase"},
        ),
        EndpointCase("get", "api_collection"),
        EndpointCase("post", "api_collection", payload={}),
        EndpointCase("get", "api_collection_entry", args=(1,)),
        EndpointCase("patch", "api_collection_entry", args=(1,), payload={}),
        EndpointCase("delete", "api_collection_entry", args=(1,)),
        EndpointCase("get", "api_task_status", args=("some-task-id",)),
    ]
