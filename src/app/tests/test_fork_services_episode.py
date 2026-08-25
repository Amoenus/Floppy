from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase

from app import fork_services_episode
from app.models import MediaTypes, Sources


class ResolveOrCreateSeasonMalformedMetadataTests(TestCase):
    """Regression test for #957: malformed provider metadata must not leak
    a raw AttributeError ("'list' object has no attribute 'get'").
    """

    def setUp(self):
        self.user = get_user_model().objects.create_user(username="owner")

    def test_list_season_payload_does_not_raise(self):
        with patch(
            "app.fork_services_episode.services.get_media_metadata",
            return_value={
                "season/1": ["not", "a", "dict"],
                "title": "Show",
                "image": "/show.jpg",
            },
        ):
            season = fork_services_episode.resolve_or_create_season(
                self.user,
                media_id="show",
                source=Sources.TMDB.value,
                season_number=1,
            )

        self.assertIsNotNone(season)
        self.assertEqual(season.item.media_type, MediaTypes.SEASON.value)
        self.assertEqual(season.item.title, "Show")
        self.assertEqual(season.item.image, "/show.jpg")

    def test_missing_season_key_does_not_raise(self):
        with patch(
            "app.fork_services_episode.services.get_media_metadata",
            return_value={"title": "Show", "image": "/show.jpg"},
        ):
            season = fork_services_episode.resolve_or_create_season(
                self.user,
                media_id="show",
                source=Sources.TMDB.value,
                season_number=1,
            )

        self.assertIsNotNone(season)
        self.assertEqual(season.item.title, "Show")
        self.assertEqual(season.item.image, "/show.jpg")
