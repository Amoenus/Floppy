import hashlib

from django.conf import settings
from django.urls import reverse

from .base import FloppyApiTestCase
from .helpers import check_health_structure, check_info_structure


class PublicEndpointsTests(FloppyApiTestCase):
    """Verify public endpoints stay accessible without auth."""

    def test_health_endpoint(self):
        """Health endpoint test."""
        response = self.call_api("get", "api_health")

        self.assertIn(response.status_code, [200, 500])
        payload = response.json()
        check_health_structure(self, payload)

    def test_info_endpoint(self):
        """Info endpoint test."""
        response = self.call_api("get", "api_info")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        check_info_structure(self, payload)

    def test_openapi_endpoints_are_public(self):
        for route_name in ("schema", "swagger-ui", "openapi-contract"):
            with self.subTest(route_name=route_name):
                response = self.client.get(reverse(route_name))
                self.assertEqual(response.status_code, 200)

    def test_openapi_contract_supports_public_cache_validation(self):
        artifact = (
            settings.BASE_DIR / "api" / "contracts" / "openapi.yaml"
        ).read_bytes()
        expected_etag = f'"{hashlib.sha256(artifact).hexdigest()}"'
        url = reverse("openapi-contract")

        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/yaml")
        self.assertEqual(response["Cache-Control"], "public, max-age=3600")
        self.assertEqual(response["ETag"], expected_etag)
        self.assertEqual(b"".join(response.streaming_content), artifact)

        not_modified = self.client.get(url, HTTP_IF_NONE_MATCH=expected_etag)
        self.assertEqual(not_modified.status_code, 304)
        self.assertEqual(not_modified.content, b"")
        self.assertEqual(not_modified["ETag"], expected_etag)

        changed = self.client.get(url, HTTP_IF_NONE_MATCH='"different"')
        self.assertEqual(changed.status_code, 200)
        self.assertEqual(b"".join(changed.streaming_content), artifact)

    def test_protected_data_endpoint_remains_private(self):
        response = self.client.get(reverse("api_media_list"))

        self.assertIn(response.status_code, (401, 403))
