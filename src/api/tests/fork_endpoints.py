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
        EndpointCase(
            "post",
            "api_media_episode_watch",
            args=("tv", "tmdb", 1, 1, 1),
            payload={},
        ),
        EndpointCase(
            "delete",
            "api_media_episode_watch",
            args=("tv", "tmdb", 1, 1, 1),
        ),
        EndpointCase(
            "post",
            "api_media_episode_drop",
            args=("tv", "tmdb", 1, 1, 1),
            payload={},
        ),
        EndpointCase("get", "api_media_tags", args=("movie", "tmdb", 1)),
        EndpointCase(
            "put",
            "api_media_tags",
            args=("movie", "tmdb", 1),
            payload={"tag_ids": []},
        ),
        EndpointCase(
            "patch",
            "api_media_episode_score",
            args=("tv", "tmdb", 1, 1, 1),
            payload={"score": 8},
        ),
        EndpointCase(
            "get",
            "api_media_provider_preference",
            args=("movie", "tmdb", 1),
        ),
        EndpointCase(
            "put",
            "api_media_provider_preference",
            args=("movie", "tmdb", 1),
            payload={"provider": "tmdb"},
        ),
        EndpointCase(
            "patch",
            "api_item_image",
            args=(1,),
            payload={"image_url": "https://example.com/x.jpg"},
        ),
        EndpointCase("patch", "api_item_metadata", args=(1,), payload={}),
        EndpointCase("get", "api_history"),
        EndpointCase("delete", "api_history_record", args=("movie", "1")),
        EndpointCase("get", "api_tags"),
        EndpointCase("post", "api_tags", payload={"name": "tag"}),
        EndpointCase("patch", "api_tag_detail", args=(1,), payload={"name": "t"}),
        EndpointCase("delete", "api_tag_detail", args=(1,)),
    ]
