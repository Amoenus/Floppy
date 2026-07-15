# FORK: URL routes for fork-only endpoints, appended to urls.py's
# urlpatterns with a single line to keep the upstream file mergeable.
from django.urls import re_path

from . import fork_views

urlpatterns = [
    re_path(
        r"^media/(?P<media_type>[^/]+)/(?P<source>[^/]+)/(?P<media_id>[^/]+)/progress/?$",
        fork_views.MediaProgressView.as_view(),
        name="api_media_progress",
    ),
    re_path(
        r"^media/(?P<media_type>[^/]+)/(?P<source>[^/]+)/(?P<media_id>[^/]+)/(?P<season_number>\d+)/progress/?$",
        fork_views.MediaProgressView.as_view(),
        name="api_media_season_progress",
    ),
    re_path(
        r"^collection/?$",
        fork_views.CollectionView.as_view(),
        name="api_collection",
    ),
    re_path(
        r"^collection/(?P<entry_id>\d+)/?$",
        fork_views.CollectionEntryView.as_view(),
        name="api_collection_entry",
    ),
    re_path(
        r"^tasks/(?P<task_id>[\w-]+)/?$",
        fork_views.TaskStatusView.as_view(),
        name="api_task_status",
    ),
]
