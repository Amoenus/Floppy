"""The request-scoped user is what makes personal keys reach every provider."""

from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import RequestFactory, TestCase, override_settings

from app.middleware import ProviderCredentialUserMiddleware
from app.providers import credentials, tmdb


class ProviderCredentialUserScopeTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = get_user_model().objects.create_user(
            username="scoped",
            password="12345",
        )
        credentials.set_user("tmdb", self.user, {"api_key": "personal-tmdb"})

    def tearDown(self):
        cache.clear()

    def test_outside_a_request_the_instance_key_is_used(self):
        """Celery runs no middleware, so background work must not spend a member's key."""
        self.assertNotEqual(tmdb.base_params()["api_key"], "personal-tmdb")

    def test_inside_a_request_the_personal_key_reaches_a_deep_provider_call(self):
        """tmdb.base_params takes no user argument; the contextvar is how it learns."""
        seen = {}

        def view(request):
            seen["api_key"] = tmdb.base_params()["api_key"]
            return "response"

        middleware = ProviderCredentialUserMiddleware(view)
        request = RequestFactory().get("/")
        request.user = self.user

        middleware(request)

        self.assertEqual(seen["api_key"], "personal-tmdb")

    def test_the_scope_is_reset_after_the_response(self):
        """A leaked contextvar would hand the next request this member's key."""
        middleware = ProviderCredentialUserMiddleware(lambda request: "response")
        request = RequestFactory().get("/")
        request.user = self.user

        middleware(request)

        self.assertNotEqual(tmdb.base_params()["api_key"], "personal-tmdb")

    def test_an_anonymous_request_uses_the_instance_key(self):
        from django.contrib.auth.models import AnonymousUser

        seen = {}

        def view(request):
            seen["api_key"] = tmdb.base_params()["api_key"]
            return "response"

        request = RequestFactory().get("/")
        request.user = AnonymousUser()
        ProviderCredentialUserMiddleware(view)(request)

        self.assertNotEqual(seen["api_key"], "personal-tmdb")

    @override_settings(TVDB_API_KEY="instance-tvdb", TVDB_PIN="")
    def test_a_personal_key_gets_its_own_token_cache_slot(self):
        """A shared token cache key would hand one member's bearer token to everyone."""
        from app.providers import tvdb

        credentials.set_user("tvdb", self.user, {"api_key": "personal-tvdb"})

        instance_key = tvdb._token_cache_key()
        personal_key = tvdb._token_cache_key(self.user)

        self.assertNotEqual(instance_key, personal_key)

    @override_settings(TVDB_API_KEY="instance-tvdb", TVDB_PIN="")
    @patch("app.providers.tvdb.services.api_request")
    def test_a_members_tvdb_token_is_not_served_to_others(self, mock_request):
        from app.providers import tvdb

        credentials.set_user("tvdb", self.user, {"api_key": "personal-tvdb"})
        mock_request.return_value = {"data": {"token": "personal-bearer"}}

        self.assertEqual(tvdb._get_token(self.user), "personal-bearer")

        mock_request.return_value = {"data": {"token": "instance-bearer"}}
        self.assertEqual(tvdb._get_token(), "instance-bearer")
