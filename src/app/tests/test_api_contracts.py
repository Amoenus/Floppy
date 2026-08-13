import asyncio
from unittest.mock import AsyncMock, patch

from django.test import SimpleTestCase
from floppy_mcp import server as mcp_server
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
            "[('/api/v1/media/', 'get')]. volatile prose": 3,
        }

        self.assertEqual(
            normalize_schema_findings(findings),
            frozenset(
                {
                    ("api.views.CalendarView", "serializer-unresolved"),
                    (
                        "api.listenbrainz_views.SubmitListensView"
                        "[authenticator=Changed]",
                        "authentication-unresolved",
                    ),
                    ("api.future.FutureView", "unclassified"),
                    (
                        "operation-id.api_v1_media_retrieve"
                        "(('/api/v1/media/', 'get'),)",
                        "operation-id-collision",
                    ),
                }
            ),
        )

    def test_unresolved_authenticator_class_is_part_of_finding_identity(self):
        prefix = (
            "/checkout/src/api/views.py: Warning [AuthView]: "
            "could not resolve authenticator <class '"
        )

        listenbrainz = normalize_schema_findings(
            [f"{prefix}api.authentication.ListenBrainzTokenAuthentication'>."]
        )
        api_key = normalize_schema_findings(
            [f"{prefix}api.authentication.APIKeyAuthentication'>."]
        )

        self.assertNotEqual(listenbrainz, api_key)
        self.assertIn(
            (
                "api.views.AuthView"
                "[authenticator=api.authentication.ListenBrainzTokenAuthentication]",
                "authentication-unresolved",
            ),
            listenbrainz,
        )

    def test_operation_id_collision_members_are_part_of_finding_identity(self):
        prefix = 'Warning: operationId "api_v1_media_retrieve" has collisions '

        two_routes = normalize_schema_findings(
            [f"{prefix}[('/api/v1/media/', 'get'), ('/api/v1/media/{{id}}/', 'get')]."]
        )
        same_routes_reordered = normalize_schema_findings(
            [f"{prefix}[('/api/v1/media/{{id}}/', 'GET'), ('/api/v1/media/', 'get')]."]
        )
        three_routes = normalize_schema_findings(
            [
                f"{prefix}[('/api/v1/media/{{id}}/', 'get'), "
                "('/api/v1/media/{id}/{part}/', 'get'), "
                "('/api/v1/media/', 'get')]."
            ]
        )

        self.assertEqual(two_routes, same_routes_reordered)
        self.assertNotEqual(two_routes, three_routes)

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
        observed = set()

        async def exercise_all_branches(mock_call):
            async def capture(tool, coroutine, results=None):
                mock_call.reset_mock()
                mock_call.return_value = {}
                mock_call.side_effect = results
                await coroutine
                observed.update(
                    (
                        tool,
                        call.args[0],
                        canonical_openapi_path(call.args[1]),
                    )
                    for call in mock_call.await_args_list
                )
                mock_call.side_effect = None

            await capture("search_media", mcp_server.search_media("movie", "query"))
            await capture(
                "search_tracked_media", mcp_server.search_tracked_media("query")
            )
            await capture("get_discover", mcp_server.get_discover("movie"))
            await capture("get_home", mcp_server.get_home())
            await capture("get_media", mcp_server.get_media("tv", "tmdb", "1"))
            await capture(
                "get_media", mcp_server.get_media("tv", "tmdb", "1", 2)
            )
            await capture(
                "get_media", mcp_server.get_media("tv", "tmdb", "1", 2, 3)
            )
            await capture("list_tracked_media", mcp_server.list_tracked_media())
            await capture(
                "list_tracked_media", mcp_server.list_tracked_media("movie")
            )
            await capture(
                "track_media",
                mcp_server.track_media("movie", "tmdb", "1"),
                [{"tracked": False}, {}],
            )
            await capture(
                "track_media",
                mcp_server.track_media("movie", "tmdb", "1"),
                [{"tracked": True, "consumptions": []}, {}],
            )
            await capture(
                "track_media",
                mcp_server.track_media("movie", "tmdb", "1", status="Completed"),
                [
                    {
                        "tracked": True,
                        "consumptions": [
                            {"consumption_id": 42, "status": "Planning"}
                        ],
                    },
                    {},
                ],
            )
            await capture(
                "untrack_media", mcp_server.untrack_media("movie", "tmdb", "1")
            )
            await capture(
                "untrack_media", mcp_server.untrack_media("tv", "tmdb", "1", 2)
            )
            await capture(
                "untrack_media", mcp_server.untrack_media("tv", "tmdb", "1", 2, 3)
            )
            await capture(
                "update_progress",
                mcp_server.update_progress("movie", "tmdb", "1", "increase"),
            )
            await capture(
                "update_progress",
                mcp_server.update_progress("tv", "tmdb", "1", "increase", 2),
            )
            await capture(
                "log_episode_play", mcp_server.log_episode_play("tmdb", "1", 2, 3)
            )
            await capture("log_song_play", mcp_server.log_song_play(1))
            await capture("log_podcast_play", mcp_server.log_podcast_play(1))
            await capture("list_custom_lists", mcp_server.list_custom_lists())
            await capture("manage_list", mcp_server.manage_list("create", name="x"))
            await capture("manage_list", mcp_server.manage_list("rename", 1, "x"))
            await capture("manage_list", mcp_server.manage_list("delete", 1))
            await capture("manage_list", mcp_server.manage_list("list_items", 1))
            await capture(
                "manage_list",
                mcp_server.manage_list("add_item", 1, media_type="movie", source="tmdb", media_id="1"),
            )
            await capture(
                "manage_list",
                mcp_server.manage_list("remove_item", 1, media_type="movie", source="tmdb", media_id="1"),
            )
            await capture("manage_tags", mcp_server.manage_tags("list"))
            await capture("manage_tags", mcp_server.manage_tags("create", name="x"))
            await capture("manage_tags", mcp_server.manage_tags("rename", 1, "x"))
            await capture("manage_tags", mcp_server.manage_tags("delete", 1))
            await capture(
                "manage_tags",
                mcp_server.manage_tags(
                    "get_for_item", media_type="movie", source="tmdb", media_id="1"
                ),
            )
            await capture(
                "manage_tags",
                mcp_server.manage_tags(
                    "set_for_item", media_type="movie", source="tmdb", media_id="1"
                ),
            )
            await capture("get_history", mcp_server.get_history())
            await capture("get_statistics", mcp_server.get_statistics())
            await capture("run_import", mcp_server.run_import("mal"))
            await capture("get_task_status", mcp_server.get_task_status("task-1"))
            await capture("manage_settings", mcp_server.manage_settings("get"))
            await capture("manage_settings", mcp_server.manage_settings("update"))

        with patch("floppy_mcp.server._call", new_callable=AsyncMock) as mock_call:
            asyncio.run(exercise_all_branches(mock_call))

        def matches(entry, observed_route):
            tool, method, path = observed_route
            template_parts = entry.path.strip("/").split("/")
            path_parts = path.strip("/").split("/")
            return (
                entry.tool == tool
                and entry.method == method
                and len(template_parts) == len(path_parts)
                and all(
                    template == actual
                    or (template.startswith("{") and template.endswith("}"))
                    for template, actual in zip(template_parts, path_parts, strict=True)
                )
            )

        unmatched = {
            route
            for route in observed
            if not any(matches(entry, route) for entry in MCP_HTTP_MANIFEST)
        }
        unobserved = {
            entry
            for entry in MCP_HTTP_MANIFEST
            if not any(matches(entry, route) for route in observed)
        }

        self.assertEqual(unmatched, set())
        self.assertEqual(unobserved, set())

    def test_every_manifest_route_exists_in_generated_openapi(self):
        paths = generate_schema_contract().schema["paths"]

        missing = [
            entry
            for entry in MCP_HTTP_MANIFEST
            if entry.path not in paths or entry.method not in paths[entry.path]
        ]
        self.assertEqual(missing, [])
