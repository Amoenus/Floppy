from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from app.models import PodcastEpisode, PodcastShow


class PodcastShowDetailWebsiteLinkTests(TestCase):
    """website_url renders as a link on the podcast show detail page."""

    def setUp(self):
        self.credentials = {"username": "test", "password": "12345"}
        self.user = get_user_model().objects.create_user(**self.credentials)
        self.client.login(**self.credentials)

    def test_renders_show_and_episode_website_links(self):
        show = PodcastShow.objects.create(
            podcast_uuid="show-website-link",
            title="Website Link Podcast",
            website_url="https://example.com/show",
        )
        PodcastEpisode.objects.create(
            show=show,
            episode_uuid="episode-website-link",
            title="Episode With A Link",
            website_url="https://example.com/show/episode-one",
        )

        response = self.client.get(reverse("podcast_show_detail", args=[show.id]))

        self.assertContains(response, "https://example.com/show")
        self.assertContains(response, "https://example.com/show/episode-one")

    def test_omits_links_when_website_url_is_blank(self):
        show = PodcastShow.objects.create(
            podcast_uuid="show-no-website-link",
            title="No Link Podcast",
        )
        PodcastEpisode.objects.create(
            show=show,
            episode_uuid="episode-no-website-link",
            title="Episode Without A Link",
        )

        response = self.client.get(reverse("podcast_show_detail", args=[show.id]))

        self.assertNotContains(response, "Visit show website")
        self.assertNotContains(response, "Episode website")
