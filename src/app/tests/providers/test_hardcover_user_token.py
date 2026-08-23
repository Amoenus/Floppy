from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings

from app.providers import hardcover
from integrations.imports.helpers import encrypt


class HardcoverUserTokenTests(TestCase):
    """Coverage for per-user Hardcover API token resolution (#937)."""

    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="hardcover-user",
            password="12345",
        )

    @override_settings(HARDCOVER_API="instance-default-token")
    def test_falls_back_to_instance_default_when_no_user(self):
        self.assertEqual(
            hardcover._authorization_header(),
            "Bearer instance-default-token",
        )

    @override_settings(HARDCOVER_API="instance-default-token")
    def test_falls_back_to_instance_default_when_user_has_no_key(self):
        self.assertEqual(
            hardcover._authorization_header(self.user),
            "Bearer instance-default-token",
        )

    @override_settings(HARDCOVER_API="instance-default-token")
    def test_uses_users_own_key_when_set(self):
        self.user.hardcover_api_key = encrypt("personal-token")
        self.user.save(update_fields=["hardcover_api_key"])

        self.assertEqual(
            hardcover._authorization_header(self.user),
            "Bearer personal-token",
        )

    @override_settings(HARDCOVER_API="instance-default-token")
    def test_different_users_get_different_tokens(self):
        other_user = get_user_model().objects.create_user(
            username="other-hardcover-user",
            password="12345",
        )
        self.user.hardcover_api_key = encrypt("token-a")
        self.user.save(update_fields=["hardcover_api_key"])
        other_user.hardcover_api_key = encrypt("token-b")
        other_user.save(update_fields=["hardcover_api_key"])

        self.assertEqual(
            hardcover._authorization_header(self.user),
            "Bearer token-a",
        )
        self.assertEqual(
            hardcover._authorization_header(other_user),
            "Bearer token-b",
        )

    @patch("app.providers.hardcover.services.api_request")
    def test_search_forwards_user_token_to_request_headers(self, mock_api_request):
        self.user.hardcover_api_key = encrypt("personal-token")
        self.user.save(update_fields=["hardcover_api_key"])
        mock_api_request.return_value = {"data": {"search": {"results": None}}}

        hardcover.cache.delete("search_hardcover_book_user-token-query_1")
        hardcover.search("user-token-query", 1, user=self.user)

        headers = mock_api_request.call_args.kwargs["headers"]
        self.assertEqual(headers["Authorization"], "Bearer personal-token")
