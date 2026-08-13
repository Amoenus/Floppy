from django.test import SimpleTestCase
from floppy_mcp.http_manifest import (
    MCP_HTTP_MANIFEST,
    HTTPRoute,
    canonical_openapi_path,
)

from api.schema_contract import (
    EXPECTED_SCHEMA_ERRORS,
    EXPECTED_SCHEMA_WARNINGS,
    SCHEMA_REGENERATION_COMMAND,
    assert_schema_findings,
    generate_schema_contract,
    normalize_schema_findings,
)


class SchemaFindingContractTests(SimpleTestCase):
    def test_normalizes_unique_findings_without_volatile_rendering(self):
        findings = {
            "/home/example/checkout/src/api/views.py:123: Error [CalendarView]: "
            "unable to guess serializer. Volatile advice.": 7,
            "/another/checkout/src/api/listenbrainz_views.py: Warning "
            "[SubmitListensView]: could not resolve authenticator <class 'Changed'>.": 2,
            "/checkout/src/api/future.py: Error [FutureView]: new volatile prose": 1,
            'Warning: operationId "api_v1_media_retrieve" has collisions '
            "[volatile route details].": 3,
        }

        self.assertEqual(
            normalize_schema_findings(findings),
            frozenset(
                {
                    ("api.views.CalendarView", "serializer-unresolved"),
                    (
                        "api.listenbrainz_views.SubmitListensView",
                        "authentication-unresolved",
                    ),
                    ("api.future.FutureView", "unclassified"),
                    ("operation-id.api_v1_media_retrieve", "operation-id-collision"),
                }
            ),
        )

    def test_baseline_failure_names_changed_pair_and_regeneration_command(self):
        removed = min(EXPECTED_SCHEMA_ERRORS)
        added = (f"{removed[0]}Changed", removed[1])
        mutated = (EXPECTED_SCHEMA_ERRORS - {removed}) | {added}

        with self.assertRaises(AssertionError) as caught:
            assert_schema_findings(mutated, EXPECTED_SCHEMA_WARNINGS)

        message = str(caught.exception)
        self.assertIn(f"+ {added!r}", message)
        self.assertIn(f"- {removed!r}", message)
        self.assertIn(SCHEMA_REGENERATION_COMMAND, message)

    def test_reviewed_baseline_has_expected_unique_counts(self):
        self.assertEqual(len(EXPECTED_SCHEMA_ERRORS), 83)
        self.assertEqual(len(EXPECTED_SCHEMA_WARNINGS), 21)

    def test_generated_schema_findings_match_reviewed_baseline(self):
        contract = generate_schema_contract()

        assert_schema_findings(contract.errors, contract.warnings)


class MCPHTTPManifestTests(SimpleTestCase):
    def test_relative_paths_have_one_canonical_openapi_form(self):
        self.assertEqual(canonical_openapi_path("media/{media_type}"), "/api/v1/media/{media_type}/")
        self.assertEqual(canonical_openapi_path("/media/"), "/api/v1/media/")

    def test_grounding_critical_tools_are_explicit(self):
        critical = {
            entry for entry in MCP_HTTP_MANIFEST if entry.tool in {"search_media", "get_media", "track_media"}
        }

        self.assertEqual(
            critical,
            {
                HTTPRoute("search_media", "get", "/api/v1/search/{media_type}/"),
                HTTPRoute(
                    "get_media",
                    "get",
                    "/api/v1/media/{media_type}/{source}/{media_id}/",
                ),
                HTTPRoute(
                    "get_media",
                    "get",
                    "/api/v1/media/{media_type}/{source}/{media_id}/{season_number}/",
                ),
                HTTPRoute(
                    "get_media",
                    "get",
                    "/api/v1/media/{media_type}/{source}/{media_id}/{season_number}/{episode_number}/",
                ),
                HTTPRoute(
                    "track_media",
                    "get",
                    "/api/v1/media/{media_type}/{source}/{media_id}/",
                ),
                HTTPRoute(
                    "track_media",
                    "patch",
                    "/api/v1/media/{media_type}/{source}/{media_id}/history/{consumption_id}/",
                ),
                HTTPRoute(
                    "track_media",
                    "patch",
                    "/api/v1/media/{media_type}/{source}/{media_id}/",
                ),
                HTTPRoute(
                    "track_media",
                    "post",
                    "/api/v1/media/{media_type}/",
                ),
            },
        )

    def test_manifest_covers_all_current_http_branches(self):
        expected_by_tool = {
            "search_media": {("get", "search/{media_type}")},
            "search_tracked_media": {("get", "media")},
            "get_discover": {("get", "discover")},
            "get_home": {("get", "home")},
            "get_media": {
                ("get", "media/{media_type}/{source}/{media_id}"),
                (
                    "get",
                    "media/{media_type}/{source}/{media_id}/{season_number}",
                ),
                (
                    "get",
                    "media/{media_type}/{source}/{media_id}/{season_number}/"
                    "{episode_number}",
                ),
            },
            "list_tracked_media": {
                ("get", "media"),
                ("get", "media/{media_type}"),
            },
            "track_media": {
                ("get", "media/{media_type}/{source}/{media_id}"),
                (
                    "patch",
                    "media/{media_type}/{source}/{media_id}/history/"
                    "{consumption_id}",
                ),
                ("patch", "media/{media_type}/{source}/{media_id}"),
                ("post", "media/{media_type}"),
            },
            "untrack_media": {
                ("delete", "media/{media_type}/{source}/{media_id}"),
                (
                    "delete",
                    "media/{media_type}/{source}/{media_id}/{season_number}",
                ),
                (
                    "delete",
                    "media/{media_type}/{source}/{media_id}/{season_number}/"
                    "{episode_number}",
                ),
            },
            "update_progress": {
                ("post", "media/{media_type}/{source}/{media_id}/progress"),
                (
                    "post",
                    "media/{media_type}/{source}/{media_id}/{season_number}/progress",
                ),
            },
            "log_episode_play": {
                (
                    "post",
                    "media/{media_type}/{source}/{media_id}/{season_number}/episodes/"
                    "{episode_number}/watch",
                )
            },
            "log_song_play": {("post", "music/songs/plays")},
            "log_podcast_play": {("post", "podcasts/episodes/plays")},
            "list_custom_lists": {("get", "lists")},
            "manage_list": {
                ("post", "lists"),
                ("patch", "lists/{list_id}"),
                ("delete", "lists/{list_id}"),
                ("get", "lists/{list_id}/items"),
                (
                    "put",
                    "media/{media_type}/{source}/{media_id}/lists/{list_id}",
                ),
                (
                    "delete",
                    "media/{media_type}/{source}/{media_id}/lists/{list_id}",
                ),
            },
            "manage_tags": {
                ("get", "tags"),
                ("post", "tags"),
                ("patch", "tags/{tag_id}"),
                ("delete", "tags/{tag_id}"),
                ("get", "media/{media_type}/{source}/{media_id}/tags"),
                ("put", "media/{media_type}/{source}/{media_id}/tags"),
            },
            "get_history": {("get", "history")},
            "get_statistics": {("get", "statistics/overview")},
            "run_import": {("post", "imports/{service}")},
            "get_task_status": {("get", "tasks/{task_id}")},
            "manage_settings": {
                ("get", "user/preferences"),
                ("patch", "user/preferences"),
            },
        }
        expected = {
            HTTPRoute(tool, method, canonical_openapi_path(path))
            for tool, routes in expected_by_tool.items()
            for method, path in routes
        }

        self.assertEqual(set(MCP_HTTP_MANIFEST), expected)
        self.assertEqual(len(MCP_HTTP_MANIFEST), len(expected))
        self.assertTrue(all(entry.method == entry.method.lower() for entry in MCP_HTTP_MANIFEST))

    def test_every_manifest_route_exists_in_generated_openapi(self):
        paths = generate_schema_contract().schema["paths"]

        missing = [
            entry
            for entry in MCP_HTTP_MANIFEST
            if entry.path not in paths or entry.method not in paths[entry.path]
        ]
        self.assertEqual(missing, [])
