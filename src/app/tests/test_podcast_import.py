from unittest.mock import patch

from django.test import SimpleTestCase

from app.services import podcast_import


class ResolveShowMetadataTests(SimpleTestCase):
    """Tests for resolve_show_metadata's RSS-fallback guard."""

    @patch("integrations.podcast_rss.fetch_show_metadata_from_rss")
    def test_fetches_rss_for_website_url_even_with_a_description(self, mock_rss):
        """A description from iTunes alone must not skip the RSS fetch.

        website_url never comes from iTunes, so the RSS feed still needs to
        be read even when iTunes already supplied a description.
        """
        mock_rss.return_value = {"website_url": "https://example.com/show"}

        resolved = podcast_import.resolve_show_metadata(
            {"description": "From iTunes."},
            "https://example.com/feed.xml",
        )

        mock_rss.assert_called_once_with("https://example.com/feed.xml")
        self.assertEqual(resolved["description"], "From iTunes.")
        self.assertEqual(resolved["website_url"], "https://example.com/show")

    @patch("integrations.podcast_rss.fetch_show_metadata_from_rss")
    def test_skips_rss_fetch_once_description_and_website_url_are_present(
        self, mock_rss
    ):
        resolved = podcast_import.resolve_show_metadata(
            {
                "description": "From iTunes.",
                "website_url": "https://example.com/show",
            },
            "https://example.com/feed.xml",
        )

        mock_rss.assert_not_called()
        self.assertEqual(resolved["website_url"], "https://example.com/show")
