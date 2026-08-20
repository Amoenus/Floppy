from unittest.mock import Mock, patch

from django.test import SimpleTestCase

from integrations import podcast_rss

ITUNES_IMAGE_FEED = b"""<?xml version="1.0" encoding="UTF-8"?>
<rss xmlns:itunes="http://www.itunes.com/dtds/podcast-1.0.dtd" version="2.0">
  <channel>
    <title>Example Show</title>
    <itunes:image href="https://example.com/itunes-art.jpg"/>
  </channel>
</rss>
"""

CHANNEL_IMAGE_FEED = b"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>Example Show</title>
    <image>
      <url>https://example.com/rss-art.jpg</url>
    </image>
  </channel>
</rss>
"""

NO_IMAGE_FEED = b"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>Example Show</title>
  </channel>
</rss>
"""


class FetchShowMetadataArtworkTests(SimpleTestCase):
    """Tests for artwork extraction in fetch_show_metadata_from_rss."""

    @patch("integrations.podcast_rss.requests.get")
    def test_prefers_itunes_image(self, mock_get):
        mock_get.return_value = Mock(content=ITUNES_IMAGE_FEED)
        mock_get.return_value.raise_for_status = Mock()

        metadata = podcast_rss.fetch_show_metadata_from_rss("https://example.com/feed.xml")

        self.assertEqual(metadata["image"], "https://example.com/itunes-art.jpg")

    @patch("integrations.podcast_rss.requests.get")
    def test_falls_back_to_channel_image_url(self, mock_get):
        mock_get.return_value = Mock(content=CHANNEL_IMAGE_FEED)
        mock_get.return_value.raise_for_status = Mock()

        metadata = podcast_rss.fetch_show_metadata_from_rss("https://example.com/feed.xml")

        self.assertEqual(metadata["image"], "https://example.com/rss-art.jpg")

    @patch("integrations.podcast_rss.requests.get")
    def test_no_image_omits_key(self, mock_get):
        mock_get.return_value = Mock(content=NO_IMAGE_FEED)
        mock_get.return_value.raise_for_status = Mock()

        metadata = podcast_rss.fetch_show_metadata_from_rss("https://example.com/feed.xml")

        self.assertNotIn("image", metadata)
