from unittest.mock import patch

import requests
from django.conf import settings
from django.core.cache import cache
from django.test import SimpleTestCase

from app.models import Sources
from app.providers import mal
from app.providers.services import ProviderAPIError


class MalRatingProviderTests(SimpleTestCase):
    # Provider credentials resolve through the database (Settings > Metadata).
    databases = {"default"}

    def setUp(self):
        cache.clear()

    def tearDown(self):
        cache.clear()

    @patch("app.providers.mal.services.api_request")
    def test_rating_requests_aggregate_fields_and_caches_success(self, mock_request):
        mock_request.return_value = {"mean": 8.76, "num_scoring_users": 1234}

        self.assertEqual(mal.rating("52991"), (8.76, 1234))
        self.assertEqual(mal.rating("52991"), (8.76, 1234))

        mock_request.assert_called_once_with(
            Sources.MAL.value,
            "GET",
            "https://api.myanimelist.net/v2/anime/52991",
            params={"fields": "mean,num_scoring_users"},
            headers={"X-MAL-CLIENT-ID": settings.MAL_API},
        )

    @patch("app.providers.mal.services.api_request")
    def test_rating_returns_none_for_missing_or_invalid_scores(self, mock_request):
        for media_id, response in (
            ("missing", {"mean": None, "num_scoring_users": 100}),
            ("unrated", {"mean": 8.0, "num_scoring_users": 0}),
            ("out-of-range", {"mean": 11.0, "num_scoring_users": 100}),
        ):
            mock_request.return_value = response
            self.assertIsNone(mal.rating(media_id))

        self.assertEqual(mock_request.call_count, 3)

    @patch("app.providers.mal.services.api_request")
    def test_rating_raises_provider_error_for_api_failure(self, mock_request):
        response = requests.Response()
        response.status_code = 503
        response._content = b"{}"
        response.url = "https://api.myanimelist.net/v2/anime/52991"
        mock_request.side_effect = requests.exceptions.HTTPError(response=response)

        with self.assertRaises(ProviderAPIError):
            mal.rating("52991")
