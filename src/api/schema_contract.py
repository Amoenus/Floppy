import ast
import re
from collections.abc import Iterable
from typing import Any, NamedTuple

SCHEMA_REGENERATION_COMMAND = (
    "SECRET=<value> uv run --no-sync python src/manage.py spectacular "
    "--validate --file src/api/contracts/openapi.yaml"
)

type SchemaFinding = tuple[str, str]

_SOURCE_FINDING = re.compile(
    r"(?:^|[/\\])src[/\\](?P<module>.+?)\.py(?::\d+)?: "
    r"(?:Error|Warning) \[(?P<breadcrumbs>[^]]+)\]: (?P<detail>.*)$"
)
_OPERATION_ID_COLLISION = re.compile(
    r'operationId "(?P<operation_id>[^"]+)" has collisions '
    r"(?P<members>\[[^]]*\])"
)
_UNRESOLVED_AUTHENTICATOR = re.compile(
    r"could not resolve authenticator <class '(?P<authenticator>[^']+)'>"
)
_COLLISION_MEMBER_SIZE = 2


EXPECTED_SCHEMA_ERRORS: frozenset[SchemaFinding] = frozenset(
    {
        ("api.fork_views.CollectionEntryView", "serializer-unresolved"),
        ("api.fork_views.CollectionView", "serializer-unresolved"),
        ("api.fork_views.MediaProgressView", "serializer-unresolved"),
        ("api.fork_views.TaskStatusView", "serializer-unresolved"),
        ("api.fork_views_discover.CollectionSeasonView", "serializer-unresolved"),
        ("api.fork_views_discover.CollectionStatusView", "serializer-unresolved"),
        ("api.fork_views_discover.DiscoverHiddenView", "serializer-unresolved"),
        ("api.fork_views_discover.DiscoverRefreshView", "serializer-unresolved"),
        ("api.fork_views_discover.DiscoverRowsView", "serializer-unresolved"),
        ("api.fork_views_discover.HomeView", "serializer-unresolved"),
        ("api.fork_views_integrations.ExportCsvView", "serializer-unresolved"),
        ("api.fork_views_integrations.ExportTemplateView", "serializer-unresolved"),
        ("api.fork_views_integrations.ImportActivityView", "serializer-unresolved"),
        ("api.fork_views_integrations.ImportDispatchView", "serializer-unresolved"),
        ("api.fork_views_lists.ListActivityView", "serializer-unresolved"),
        ("api.fork_views_lists.ListCollaboratorsView", "serializer-unresolved"),
        ("api.fork_views_lists.ListItemsOrderView", "serializer-unresolved"),
        ("api.fork_views_lists.ListItemsReorderView", "serializer-unresolved"),
        (
            "api.fork_views_lists.ListRecommendationDecisionView",
            "serializer-unresolved",
        ),
        ("api.fork_views_lists.ListRecommendationsView", "serializer-unresolved"),
        ("api.fork_views_lists.ListSmartRulesView", "serializer-unresolved"),
        ("api.fork_views_lists.ListSmartSyncView", "serializer-unresolved"),
        ("api.fork_views_metadata.ItemImageView", "serializer-unresolved"),
        ("api.fork_views_metadata.ItemMetadataView", "serializer-unresolved"),
        ("api.fork_views_metadata.MediaEpisodeScoreView", "serializer-unresolved"),
        (
            "api.fork_views_metadata.MediaProviderPreferenceView",
            "serializer-unresolved",
        ),
        ("api.fork_views_music.MusicAlbumDetailView", "serializer-unresolved"),
        ("api.fork_views_music.MusicAlbumPlaysView", "serializer-unresolved"),
        ("api.fork_views_music.MusicAlbumTracksView", "serializer-unresolved"),
        ("api.fork_views_music.MusicAlbumsView", "serializer-unresolved"),
        ("api.fork_views_music.MusicArtistDetailView", "serializer-unresolved"),
        ("api.fork_views_music.MusicArtistPlaysView", "serializer-unresolved"),
        ("api.fork_views_music.MusicArtistSyncView", "serializer-unresolved"),
        ("api.fork_views_music.MusicArtistsView", "serializer-unresolved"),
        ("api.fork_views_music.MusicBulkPlaysView", "serializer-unresolved"),
        ("api.fork_views_music.MusicSongPlayView", "serializer-unresolved"),
        ("api.fork_views_music.MusicTrackScoreView", "serializer-unresolved"),
        ("api.fork_views_podcast.PodcastEpisodePlayView", "serializer-unresolved"),
        (
            "api.fork_views_podcast.PodcastMarkAllPlayedView",
            "serializer-unresolved",
        ),
        ("api.fork_views_podcast.PodcastShowDetailView", "serializer-unresolved"),
        (
            "api.fork_views_podcast.PodcastShowEpisodesView",
            "serializer-unresolved",
        ),
        ("api.fork_views_podcast.PodcastShowsView", "serializer-unresolved"),
        (
            "api.fork_views_statistics.StatisticsOverviewView",
            "serializer-unresolved",
        ),
        (
            "api.fork_views_statistics.StatisticsRefreshView",
            "serializer-unresolved",
        ),
        ("api.fork_views_tracking.HistoryRecordView", "serializer-unresolved"),
        ("api.fork_views_tracking.HistoryView", "serializer-unresolved"),
        ("api.fork_views_tracking.MediaEpisodeBulkView", "serializer-unresolved"),
        ("api.fork_views_tracking.MediaEpisodeDropView", "serializer-unresolved"),
        ("api.fork_views_tracking.MediaEpisodeWatchView", "serializer-unresolved"),
        ("api.fork_views_tracking.MediaMovieWatchView", "serializer-unresolved"),
        ("api.fork_views_tracking.MediaTagsView", "serializer-unresolved"),
        ("api.fork_views_tracking.TagDetailView", "serializer-unresolved"),
        ("api.fork_views_tracking.TagsView", "serializer-unresolved"),
        (
            "api.fork_views_users.UserNotificationExclusionsView",
            "serializer-unresolved",
        ),
        (
            "api.fork_views_users.UserNotificationTestView",
            "serializer-unresolved",
        ),
        ("api.fork_views_users.UserNotificationsView", "serializer-unresolved"),
        ("api.fork_views_users.UserPreferencesView", "serializer-unresolved"),
        ("api.fork_views_users.UserSidebarView", "serializer-unresolved"),
        ("api.fork_views_users.UserTokenRegenerateView", "serializer-unresolved"),
        ("api.views.CalendarUpdateView", "serializer-unresolved"),
        ("api.views.CalendarView", "serializer-unresolved"),
        ("api.views.HealthView", "serializer-unresolved"),
        ("api.views.InfoView", "serializer-unresolved"),
        ("api.views.ListDetailView", "serializer-unresolved"),
        ("api.views.ListItemView", "serializer-unresolved"),
        ("api.views.ListItemsView", "serializer-unresolved"),
        ("api.views.ListsView", "serializer-unresolved"),
        ("api.views.MediaChangesHistoryView", "serializer-unresolved"),
        ("api.views.MediaEpisodeChangesHistoryView", "serializer-unresolved"),
        ("api.views.MediaEpisodeListDetailView", "serializer-unresolved"),
        ("api.views.MediaEpisodeListsView", "serializer-unresolved"),
        ("api.views.MediaEpisodeSyncView", "serializer-unresolved"),
        ("api.views.MediaListDetailView", "serializer-unresolved"),
        ("api.views.MediaListsView", "serializer-unresolved"),
        ("api.views.MediaSeasonChangesHistoryView", "serializer-unresolved"),
        ("api.views.MediaSeasonEpisodesView", "serializer-unresolved"),
        ("api.views.MediaSeasonListDetailView", "serializer-unresolved"),
        ("api.views.MediaSeasonListsView", "serializer-unresolved"),
        ("api.views.MediaSeasonSyncView", "serializer-unresolved"),
        ("api.views.MediaSeasonsView", "serializer-unresolved"),
        ("api.views.MediaSyncView", "serializer-unresolved"),
        (
            "api.views.MediaTypeChangesHistoryDetailView",
            "serializer-unresolved",
        ),
        ("api.views.StatisticsView", "serializer-unresolved"),
    }
)

_EXPECTED_OPERATION_ID_COLLISIONS = (
    (
        "api_v1_collection_retrieve",
        (
            ("/api/v1/collection/", "get"),
            ("/api/v1/collection/{entry_id}/", "get"),
        ),
    ),
    (
        "api_v1_lists_items_retrieve",
        (
            ("/api/v1/lists/{list_id}/items/", "get"),
            ("/api/v1/lists/{list_id}/items/{item_id}/", "get"),
        ),
    ),
    (
        "api_v1_lists_recommendations_create",
        (
            ("/api/v1/lists/{list_id}/recommendations/", "post"),
            (
                "/api/v1/lists/{list_id}/recommendations/"
                "{recommendation_id}/{decision}/",
                "post",
            ),
        ),
    ),
    (
        "api_v1_lists_retrieve",
        (
            ("/api/v1/lists/", "get"),
            ("/api/v1/lists/{list_id}/", "get"),
        ),
    ),
    (
        "api_v1_media_changes_history_retrieve",
        (
            (
                "/api/v1/media/{media_type}/{source}/{media_id}/changes_history/",
                "get",
            ),
            (
                "/api/v1/media/{media_type}/{source}/{media_id}/"
                "{season_number}/changes_history/",
                "get",
            ),
            (
                "/api/v1/media/{media_type}/{source}/{media_id}/"
                "{season_number}/{episode_number}/changes_history/",
                "get",
            ),
        ),
    ),
    (
        "api_v1_media_destroy",
        (
            ("/api/v1/media/{media_type}/{source}/{media_id}/", "delete"),
            (
                "/api/v1/media/{media_type}/{source}/{media_id}/{season_number}/",
                "delete",
            ),
            (
                "/api/v1/media/{media_type}/{source}/{media_id}/"
                "{season_number}/{episode_number}/",
                "delete",
            ),
        ),
    ),
    (
        "api_v1_media_history_destroy",
        (
            (
                "/api/v1/media/{media_type}/{source}/{media_id}/history/"
                "{consumption_id}/",
                "delete",
            ),
            (
                "/api/v1/media/{media_type}/{source}/{media_id}/{season_number}/"
                "history/{consumption_id}/",
                "delete",
            ),
            (
                "/api/v1/media/{media_type}/{source}/{media_id}/{season_number}/"
                "{episode_number}/history/{consumption_id}/",
                "delete",
            ),
        ),
    ),
    (
        "api_v1_media_history_partial_update",
        (
            (
                "/api/v1/media/{media_type}/{source}/{media_id}/history/"
                "{consumption_id}/",
                "patch",
            ),
            (
                "/api/v1/media/{media_type}/{source}/{media_id}/{season_number}/"
                "history/{consumption_id}/",
                "patch",
            ),
            (
                "/api/v1/media/{media_type}/{source}/{media_id}/{season_number}/"
                "{episode_number}/history/{consumption_id}/",
                "patch",
            ),
        ),
    ),
    (
        "api_v1_media_history_retrieve",
        (
            ("/api/v1/media/{media_type}/{source}/{media_id}/history/", "get"),
            (
                "/api/v1/media/{media_type}/{source}/{media_id}/history/"
                "{consumption_id}/",
                "get",
            ),
            (
                "/api/v1/media/{media_type}/{source}/{media_id}/{season_number}/"
                "history/",
                "get",
            ),
            (
                "/api/v1/media/{media_type}/{source}/{media_id}/{season_number}/"
                "history/{consumption_id}/",
                "get",
            ),
            (
                "/api/v1/media/{media_type}/{source}/{media_id}/{season_number}/"
                "{episode_number}/history/",
                "get",
            ),
            (
                "/api/v1/media/{media_type}/{source}/{media_id}/{season_number}/"
                "{episode_number}/history/{consumption_id}/",
                "get",
            ),
        ),
    ),
    (
        "api_v1_media_lists_destroy",
        (
            (
                "/api/v1/media/{media_type}/{source}/{media_id}/lists/{list_id}/",
                "delete",
            ),
            (
                "/api/v1/media/{media_type}/{source}/{media_id}/{season_number}/"
                "lists/{list_id}/",
                "delete",
            ),
            (
                "/api/v1/media/{media_type}/{source}/{media_id}/{season_number}/"
                "{episode_number}/lists/{list_id}/",
                "delete",
            ),
        ),
    ),
    (
        "api_v1_media_lists_retrieve",
        (
            ("/api/v1/media/{media_type}/{source}/{media_id}/lists/", "get"),
            (
                "/api/v1/media/{media_type}/{source}/{media_id}/{season_number}/"
                "lists/",
                "get",
            ),
            (
                "/api/v1/media/{media_type}/{source}/{media_id}/{season_number}/"
                "{episode_number}/lists/",
                "get",
            ),
        ),
    ),
    (
        "api_v1_media_lists_update",
        (
            (
                "/api/v1/media/{media_type}/{source}/{media_id}/lists/{list_id}/",
                "put",
            ),
            (
                "/api/v1/media/{media_type}/{source}/{media_id}/{season_number}/"
                "lists/{list_id}/",
                "put",
            ),
            (
                "/api/v1/media/{media_type}/{source}/{media_id}/{season_number}/"
                "{episode_number}/lists/{list_id}/",
                "put",
            ),
        ),
    ),
    (
        "api_v1_media_partial_update",
        (
            ("/api/v1/media/{media_type}/{source}/{media_id}/", "patch"),
            (
                "/api/v1/media/{media_type}/{source}/{media_id}/{season_number}/",
                "patch",
            ),
            (
                "/api/v1/media/{media_type}/{source}/{media_id}/"
                "{season_number}/{episode_number}/",
                "patch",
            ),
        ),
    ),
    (
        "api_v1_media_progress_create",
        (
            ("/api/v1/media/{media_type}/{source}/{media_id}/progress/", "post"),
            (
                "/api/v1/media/{media_type}/{source}/{media_id}/{season_number}/"
                "progress/",
                "post",
            ),
        ),
    ),
    (
        "api_v1_media_retrieve",
        (
            ("/api/v1/media/", "get"),
            ("/api/v1/media/{media_type}/", "get"),
            ("/api/v1/media/{media_type}/{source}/{media_id}/", "get"),
            (
                "/api/v1/media/{media_type}/{source}/{media_id}/{season_number}/",
                "get",
            ),
            (
                "/api/v1/media/{media_type}/{source}/{media_id}/"
                "{season_number}/{episode_number}/",
                "get",
            ),
        ),
    ),
    (
        "api_v1_media_sync_create",
        (
            ("/api/v1/media/{media_type}/{source}/{media_id}/sync/", "post"),
            (
                "/api/v1/media/{media_type}/{source}/{media_id}/{season_number}/sync/",
                "post",
            ),
            (
                "/api/v1/media/{media_type}/{source}/{media_id}/{season_number}/"
                "{episode_number}/sync/",
                "post",
            ),
        ),
    ),
    (
        "api_v1_music_albums_retrieve",
        (
            ("/api/v1/music/albums/", "get"),
            ("/api/v1/music/albums/{album_id}/", "get"),
        ),
    ),
    (
        "api_v1_music_artists_retrieve",
        (
            ("/api/v1/music/artists/", "get"),
            ("/api/v1/music/artists/{artist_id}/", "get"),
        ),
    ),
    (
        "api_v1_podcasts_shows_retrieve",
        (
            ("/api/v1/podcasts/shows/", "get"),
            ("/api/v1/podcasts/shows/{show_id}/", "get"),
        ),
    ),
)

EXPECTED_SCHEMA_WARNINGS: frozenset[SchemaFinding] = frozenset(
    {
        (
            "api.listenbrainz_views.SubmitListensView"
            "[authenticator=api.authentication.ListenBrainzTokenAuthentication]",
            "authentication-unresolved",
        ),
        (
            "api.listenbrainz_views.ValidateTokenView"
            "[authenticator=api.authentication.ListenBrainzTokenAuthentication]",
            "authentication-unresolved",
        ),
    }
    | {
        (f"operation-id.{operation_id}{members!r}", "operation-id-collision")
        for operation_id, members in _EXPECTED_OPERATION_ID_COLLISIONS
    }
)


class SchemaContract(NamedTuple):
    """Generated OpenAPI schema and its normalized findings."""

    schema: dict[str, Any]
    errors: frozenset[SchemaFinding]
    warnings: frozenset[SchemaFinding]


def normalize_schema_finding(message: str) -> SchemaFinding:
    """Reduce one rendered spectacular finding to a stable owner and category."""
    if match := _SOURCE_FINDING.search(message):
        module = match["module"].replace("/", ".").replace("\\", ".")
        breadcrumbs = match["breadcrumbs"].replace(" > ", ".")
        detail = match["detail"]
        if "unable to guess serializer" in detail:
            return f"{module}.{breadcrumbs}", "serializer-unresolved"
        if match := _UNRESOLVED_AUTHENTICATOR.search(detail):
            owner = f"{module}.{breadcrumbs}[authenticator={match['authenticator']}]"
            return owner, "authentication-unresolved"
        return f"{module}.{breadcrumbs}", "unclassified"

    if match := _OPERATION_ID_COLLISION.search(message):
        try:
            members = ast.literal_eval(match["members"])
        except (SyntaxError, ValueError):
            return f"operation-id.{match['operation_id']}", "unclassified"
        if not isinstance(members, (list, tuple)) or not all(
            isinstance(member, (list, tuple))
            and len(member) == _COLLISION_MEMBER_SIZE
            and all(isinstance(value, str) for value in member)
            for member in members
        ):
            return f"operation-id.{match['operation_id']}", "unclassified"
        canonical_members = tuple(
            sorted({(path, method.lower()) for path, method in members})
        )
        return (
            f"operation-id.{match['operation_id']}{canonical_members!r}",
            "operation-id-collision",
        )

    return "schema", "unclassified"


def normalize_schema_findings(findings: Iterable[str]) -> frozenset[SchemaFinding]:
    """Normalize unique rendered finding keys, ignoring cache repeat counts."""
    return frozenset(normalize_schema_finding(message) for message in findings)


def generate_schema_contract() -> SchemaContract:
    """Generate OpenAPI in memory and return its normalized unique findings."""
    from drf_spectacular.drainage import GENERATOR_STATS, reset_generator_stats
    from drf_spectacular.generators import SchemaGenerator

    reset_generator_stats()
    with GENERATOR_STATS.silence():
        schema = SchemaGenerator().get_schema(public=True)
    return SchemaContract(
        schema=schema,
        errors=normalize_schema_findings(GENERATOR_STATS._error_cache),
        warnings=normalize_schema_findings(GENERATOR_STATS._warn_cache),
    )


def assert_schema_findings(
    errors: Iterable[SchemaFinding], warnings: Iterable[SchemaFinding]
) -> None:
    """Fail with stable additions/removals when schema findings drift."""
    differences = []
    for label, expected, actual in (
        ("errors", EXPECTED_SCHEMA_ERRORS, frozenset(errors)),
        ("warnings", EXPECTED_SCHEMA_WARNINGS, frozenset(warnings)),
    ):
        differences.extend(f"{label} + {finding!r}" for finding in sorted(actual - expected))
        differences.extend(f"{label} - {finding!r}" for finding in sorted(expected - actual))

    if differences:
        details = "\n".join(differences)
        msg = (
            f"OpenAPI schema findings changed:\n{details}\n"
            f"Regenerate with: {SCHEMA_REGENERATION_COMMAND}"
        )
        raise AssertionError(msg)
