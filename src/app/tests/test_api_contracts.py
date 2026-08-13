import ast
import inspect
from urllib.parse import urljoin

import yaml
from django.conf import settings
from django.test import SimpleTestCase
from django.test.utils import override_settings
from drf_spectacular.renderers import OpenApiYamlRenderer
from floppy_mcp import server as mcp_server
from floppy_mcp.http_manifest import (
    MCP_HTTP_MANIFEST,
    HTTPRoute,
    canonical_openapi_path,
)

from api.helpers import MEDIA_TYPE_VALID_LIST
from api.schema_contract import (
    EXPECTED_SCHEMA_ERRORS,
    EXPECTED_SCHEMA_WARNINGS,
    SCHEMA_REGENERATION_COMMAND,
    VERIFIED_OPERATIONS,
    assert_schema_findings,
    generate_schema_contract,
    generate_static_schema_contract,
    normalize_schema_findings,
)

OPENAPI_CONTRACT_PATH = settings.BASE_DIR / "api" / "contracts" / "openapi.yaml"


class OpenAPIArtifactTests(SimpleTestCase):
    @staticmethod
    def _operations(schema):
        return {
            (path, method.upper())
            for path, path_item in schema["paths"].items()
            for method in path_item
            if method in {"get", "post", "put", "patch", "delete"}
        }

    def test_settings_publish_stable_project_metadata(self):
        self.assertEqual(
            settings.SPECTACULAR_SETTINGS,
            {
                "TITLE": "Floppy",
                "DESCRIPTION": "A self-hosted media tracker.",
                "VERSION": "1.0.0",
                "CONTACT": {
                    "url": "https://github.com/dannyvfilms/Floppy/issues",
                },
                "LICENSE": {
                    "name": "AGPL-3.0",
                    "url": "https://www.gnu.org/licenses/agpl-3.0.html",
                },
                "SERVE_PERMISSIONS": ["rest_framework.permissions.AllowAny"],
            },
        )

    def test_committed_contract_is_exact_verified_generation(self):
        committed = OPENAPI_CONTRACT_PATH.read_bytes()
        parsed = yaml.safe_load(committed)
        generated = generate_static_schema_contract()

        self.assertEqual(parsed["openapi"], "3.0.3")
        self.assertEqual(generated.errors, frozenset())
        self.assertEqual(generated.warnings, frozenset())
        self.assertEqual(self._operations(parsed), VERIFIED_OPERATIONS)
        self.assertEqual(committed, OpenApiYamlRenderer().render(generated.schema))

    @override_settings(VERSION="application-version-must-not-leak")
    def test_contract_is_deterministic_and_independent_of_application_version(self):
        first = OpenApiYamlRenderer().render(generate_static_schema_contract().schema)
        second = OpenApiYamlRenderer().render(generate_static_schema_contract().schema)

        self.assertEqual(first, second)
        self.assertEqual(first, OPENAPI_CONTRACT_PATH.read_bytes())
        self.assertEqual(yaml.safe_load(first)["info"]["version"], "1.0.0")

    def test_contract_is_clearly_scoped_and_subpath_safe(self):
        schema = generate_static_schema_contract().schema

        self.assertIn(
            "verified consumer subset", schema["info"]["description"].lower()
        )
        self.assertEqual(
            schema["x-floppy-scope"], "verified-mcp-and-grounding-subset"
        )
        self.assertEqual(schema["servers"], [{"url": "../"}])

        with override_settings(BASE_URL="/floppy"):
            self.assertEqual(
                urljoin(
                    "https://example.test/floppy/api/openapi.yaml",
                    schema["servers"][0]["url"],
                ),
                "https://example.test/floppy/",
            )

    def test_contract_has_truthful_wire_components_and_auth_schemes(self):
        components = generate_static_schema_contract().schema["components"]
        schemas = components["schemas"]

        self.assertEqual(
            set(schemas["SearchResult"]["required"]),
            {"media_id", "media_type", "title", "image"},
        )
        self.assertEqual(
            schemas["SearchResult"]["properties"]["media_id"]["oneOf"],
            [{"type": "string"}, {"type": "integer"}],
        )
        self.assertEqual(
            set(schemas["SearchEnvelope"]["required"]), {"pagination", "results"}
        )
        self.assertEqual(
            set(schemas["TrackMediaRequest"]["properties"]),
            {
                "source",
                "media_id",
                "title",
                "image",
                "image_url",
                "season_number",
                "episode_number",
                "parent_tv",
                "parent_season",
                "library_media_type",
                "score",
                "status",
                "progress",
                "start_date",
                "end_date",
                "notes",
            },
        )
        self.assertEqual(
            set(schemas["MediaUpdateRequest"]["properties"]),
            {
                "score",
                "status",
                "progress",
                "start_date",
                "end_date",
                "notes",
                "dropped",
            },
        )
        self.assertEqual(
            set(schemas["TrackedMediaResponse"]["properties"]),
            {
                "id",
                "consumption_id",
                "item",
                "item_id",
                "parent_id",
                "tracked",
                "created_at",
                "score",
                "status",
                "progress",
                "progressed_at",
                "start_date",
                "end_date",
                "notes",
                "lists",
            },
        )
        self.assertEqual(
            set(schemas["ConsumptionResponse"]["properties"]),
            {
                "consumption_id",
                "created",
                "score",
                "progress",
                "progressed_at",
                "status",
                "start_date",
                "end_date",
                "notes",
            },
        )
        complete_keys = {
            "id",
            "media_id",
            "source",
            "source_url",
            "media_type",
            "title",
            "max_progress",
            "image",
            "synopsis",
            "genres",
            "score",
            "score_count",
            "details",
            "related",
            "item_id",
            "parent_id",
            "tracked",
            "consumptions_number",
            "consumptions",
            "lists",
        }
        self.assertEqual(
            set(schemas["CompleteMediaResponse"]["properties"]), complete_keys
        )
        self.assertEqual(
            set(schemas["CompleteEpisodeResponse"]["properties"]), complete_keys
        )
        self.assertNotIn(
            "season_number", schemas["CompleteEpisodeResponse"]["properties"]
        )
        self.assertNotIn(
            "episode_number", schemas["CompleteEpisodeResponse"]["properties"]
        )
        self.assertTrue(
            {"season_number", "episode_number"}
            <= set(schemas["EpisodeDetails"]["properties"])
        )
        self.assertEqual(
            set(schemas["InfoResponse"]["properties"]),
            {
                "version",
                "debug",
                "frontend_url",
                "language",
                "timezone",
                "admin_enabled",
                "track_time",
            },
        )
        self.assertEqual(
            components["securitySchemes"],
            {
                "ApiKeyAuth": {
                    "type": "apiKey",
                    "in": "header",
                    "name": "X-API-Key",
                },
                "bearerAuth": {"type": "http", "scheme": "bearer"},
                "listenBrainzToken": {
                    "type": "apiKey",
                    "in": "header",
                    "name": "Authorization",
                    "description": "ListenBrainz token in the form `Token <token>`.",
                },
            },
        )

    def test_critical_operations_use_exact_requests_responses_and_statuses(self):
        paths = generate_static_schema_contract().schema["paths"]
        expected = {
            ("/api/v1/search/{media_type}/", "get"): (
                "searchMedia",
                "SearchEnvelope",
                {"200", "400", "403", "500"},
                None,
            ),
            ("/api/v1/media/{media_type}/", "post"): (
                "trackMedia",
                "TrackedMediaResponse",
                {"201", "400", "403", "404", "409", "500"},
                "TrackMediaRequest",
            ),
            ("/api/v1/media/{media_type}/{source}/{media_id}/", "get"): (
                "retrieveMediaItem",
                "CompleteMediaResponse",
                {"200", "400", "403", "404", "500"},
                None,
            ),
            ("/api/v1/media/{media_type}/{source}/{media_id}/", "patch"): (
                "updateMediaItem",
                "CompleteMediaResponse",
                {"200", "400", "403", "404", "500"},
                "MediaUpdateRequest",
            ),
            (
                "/api/v1/media/{media_type}/{source}/{media_id}/history/"
                "{consumption_id}/",
                "patch",
            ): (
                "updateMediaConsumption",
                "ConsumptionResponse",
                {"200", "400", "403", "404", "500"},
                "MediaUpdateRequest",
            ),
            (
                "/api/v1/media/{media_type}/{source}/{media_id}/{season_number}/",
                "get",
            ): (
                "retrieveMediaSeason",
                "CompleteMediaResponse",
                {"200", "400", "403", "404", "500"},
                None,
            ),
            (
                "/api/v1/media/{media_type}/{source}/{media_id}/{season_number}/"
                "{episode_number}/",
                "get",
            ): (
                "retrieveMediaEpisode",
                "CompleteEpisodeResponse",
                {"200", "400", "403", "404", "500"},
                None,
            ),
        }

        for (path, method), (
            operation_id,
            component,
            statuses,
            request_component,
        ) in expected.items():
            with self.subTest(path=path, method=method):
                operation = paths[path][method]
                self.assertEqual(operation["operationId"], operation_id)
                self.assertEqual(set(operation["responses"]), statuses)
                success = "201" if method == "post" else "200"
                response = operation["responses"][success]
                schema = response["content"]["application/json"]["schema"]
                self.assertEqual(schema["$ref"], f"#/components/schemas/{component}")
                if request_component:
                    request_schema = operation["requestBody"]["content"][
                        "application/json"
                    ]["schema"]
                    self.assertEqual(
                        request_schema["$ref"],
                        f"#/components/schemas/{request_component}",
                    )
                self.assertEqual(
                    operation["security"],
                    [{"bearerAuth": []}, {"ApiKeyAuth": []}],
                )

    def test_search_media_type_enum_matches_supported_provider_types(self):
        operation = generate_static_schema_contract().schema["paths"][
            "/api/v1/search/{media_type}/"
        ]["get"]
        media_type = next(
            parameter
            for parameter in operation["parameters"]
            if parameter["in"] == "path" and parameter["name"] == "media_type"
        )

        self.assertEqual(media_type["schema"]["enum"], sorted(MEDIA_TYPE_VALID_LIST))
        self.assertNotIn("season", media_type["schema"]["enum"])
        self.assertNotIn("episode", media_type["schema"]["enum"])

    def test_list_latest_update_allows_empty_list_null(self):
        paths = generate_static_schema_contract().schema["paths"]
        post_schema = paths["/api/v1/lists/"]["post"]["responses"]["201"][
            "content"
        ]["application/json"]["schema"]
        get_schema = paths["/api/v1/lists/"]["get"]["responses"]["200"][
            "content"
        ]["application/json"]["schema"]["properties"]["results"]["items"]

        self.assertTrue(post_schema["properties"]["latest_update"]["nullable"])
        self.assertTrue(get_schema["properties"]["latest_update"]["nullable"])

    def test_listenbrainz_and_info_operations_are_exact(self):
        paths = generate_static_schema_contract().schema["paths"]
        for path, method, operation_id, statuses in (
            (
                "/apis/listenbrainz/1/submit-listens/",
                "post",
                "submitListenBrainzListens",
                {"200", "400", "401", "403"},
            ),
            (
                "/apis/listenbrainz/1/validate-token/",
                "get",
                "validateListenBrainzToken",
                {"200", "401"},
            ),
        ):
            operation = paths[path][method]
            self.assertEqual(operation["operationId"], operation_id)
            self.assertEqual(operation["security"], [{"listenBrainzToken": []}])
            self.assertEqual(set(operation["responses"]), statuses)

        info = paths["/api/v1/info/"]["get"]
        self.assertEqual(info.get("security"), None)
        self.assertEqual(
            info["responses"]["200"]["content"]["application/json"]["schema"],
            {"$ref": "#/components/schemas/InfoResponse"},
        )

    def test_all_successful_scoped_operations_have_truthful_body_presence(self):
        paths = generate_static_schema_contract().schema["paths"]
        operation_ids = [
            operation["operationId"]
            for path_item in paths.values()
            for method, operation in path_item.items()
            if method in {"get", "post", "put", "patch", "delete"}
        ]
        self.assertEqual(len(operation_ids), len(set(operation_ids)))

        for path, path_item in paths.items():
            for method, operation in path_item.items():
                if method not in {"get", "post", "put", "patch", "delete"}:
                    continue
                for status, response in operation["responses"].items():
                    if method != "delete" and status.startswith("2"):
                        with self.subTest(path=path, method=method, status=status):
                            self.assertIn("schema", response["content"]["application/json"])


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
        self.assertEqual(len(EXPECTED_SCHEMA_WARNINGS), 18)

    def test_generated_schema_findings_match_reviewed_baseline(self):
        contract = generate_schema_contract()

        assert_schema_findings(contract.errors, contract.warnings)

    def test_static_schema_has_no_findings_and_full_schema_is_a_superset(self):
        static = generate_static_schema_contract()
        dynamic = generate_schema_contract()

        self.assertEqual(static.errors, frozenset())
        self.assertEqual(static.warnings, frozenset())
        assert_schema_findings(dynamic.errors, dynamic.warnings)
        self.assertTrue(
            OpenAPIArtifactTests._operations(static.schema)
            <= OpenAPIArtifactTests._operations(dynamic.schema)
        )


class MCPHTTPManifestTests(SimpleTestCase):
    def test_relative_paths_have_one_canonical_openapi_form(self):
        self.assertEqual(canonical_openapi_path("media/{media_type}"), "/api/v1/media/{media_type}/")
        self.assertEqual(canonical_openapi_path("/media/"), "/api/v1/media/")

    @staticmethod
    def _routes_from_source(source):
        routes = []

        def is_mcp_tool(node):
            return any(
                isinstance(decorator, ast.Call)
                and isinstance(decorator.func, ast.Attribute)
                and isinstance(decorator.func.value, ast.Name)
                and decorator.func.value.id == "mcp"
                and decorator.func.attr == "tool"
                for decorator in node.decorator_list
            )

        def path_template(node, line):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                return node.value
            if isinstance(node, ast.JoinedStr):
                parts = []
                for value in node.values:
                    if isinstance(value, ast.Constant) and isinstance(value.value, str):
                        parts.append(value.value)
                    elif (
                        isinstance(value, ast.FormattedValue)
                        and isinstance(value.value, ast.Name)
                        and value.conversion == -1
                        and value.format_spec is None
                    ):
                        parts.append(f"{{{value.value.id}}}")
                    else:
                        raise AssertionError(
                            f"Unsupported MCP path expression at line {line}"
                        )
                return "".join(parts)
            raise AssertionError(f"Unsupported MCP path expression at line {line}")

        for node in ast.parse(source).body:
            if not isinstance(node, ast.AsyncFunctionDef) or not is_mcp_tool(node):
                continue
            for call in ast.walk(node):
                if not (
                    isinstance(call, ast.Call)
                    and isinstance(call.func, ast.Name)
                    and call.func.id == "_call"
                ):
                    continue
                if len(call.args) < 2:
                    raise AssertionError(f"Invalid _call at line {call.lineno}")
                method = call.args[0]
                if not (
                    isinstance(method, ast.Constant)
                    and isinstance(method.value, str)
                    and method.value == method.value.lower()
                ):
                    raise AssertionError(
                        f"MCP method must be a lowercase string literal at line {call.lineno}"
                    )
                routes.append(
                    HTTPRoute(
                        node.name,
                        method.value,
                        canonical_openapi_path(
                            path_template(call.args[1], call.lineno)
                        ),
                    )
                )
        return routes

    def test_source_extractor_rejects_computed_paths(self):
        source = """
@mcp.tool()
async def computed_path():
    path = "home"
    return await _call("get", path)
"""
        with self.assertRaisesRegex(
            AssertionError, "Unsupported MCP path expression at line 5"
        ):
            self._routes_from_source(source)

    def test_source_extractor_requires_literal_lowercase_methods(self):
        for method in ("method", '"GET"'):
            with self.subTest(method=method), self.assertRaisesRegex(
                AssertionError,
                "MCP method must be a lowercase string literal at line 4",
            ):
                self._routes_from_source(
                    f"""
@mcp.tool()
async def invalid_method():
    return await _call({method}, "home")
"""
                )

    def test_source_extractor_preserves_exact_templates(self):
        source = """\
@mcp.tool()
async def exact_template():
    await _call("get", f"media/{media_type}/{source}/{media_id}")
    await _call("post", "unexercised")
"""
        expected = {
            HTTPRoute(
                "exact_template",
                "get",
                "/api/v1/media/{media_type}/{source}/{media_id}/",
            ),
            HTTPRoute("exact_template", "post", "/api/v1/unexercised/"),
        }

        self.assertEqual(set(self._routes_from_source(source)), expected)
        self.assertNotEqual(
            set(
                self._routes_from_source(
                    source.replace("{media_type}/{source}", "{source}/{media_type}")
                )
            ),
            expected,
        )
        self.assertIn(
            HTTPRoute("exact_template", "post", "/api/v1/unexercised/"),
            self._routes_from_source(source),
        )

    def test_manifest_covers_all_current_http_branches(self):
        routes = self._routes_from_source(inspect.getsource(mcp_server))

        self.assertEqual(len(MCP_HTTP_MANIFEST), 40)
        self.assertEqual(len(MCP_HTTP_MANIFEST), len(set(MCP_HTTP_MANIFEST)))
        self.assertEqual(set(routes), set(MCP_HTTP_MANIFEST))
        self.assertTrue(
            {"search_media", "get_media", "track_media"}
            <= {route.tool for route in routes}
        )

    def test_every_manifest_route_exists_in_committed_openapi(self):
        paths = yaml.safe_load(OPENAPI_CONTRACT_PATH.read_bytes())["paths"]

        missing = [
            entry
            for entry in MCP_HTTP_MANIFEST
            if entry.path not in paths or entry.method not in paths[entry.path]
        ]
        self.assertEqual(missing, [])
