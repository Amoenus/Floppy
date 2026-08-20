from unittest.mock import patch

from django.test import TestCase

from integrations import plex


class ListSectionsTimeBudgetTests(TestCase):
    """list_sections() must bound total time spent probing connections."""

    def _server(self, name, connection_uris):
        return {
            "name": name,
            "machine_identifier": name,
            "access_token": "token",
            "connections": [{"uri": uri} for uri in connection_uris],
        }

    @patch("integrations.plex._fetch_sections_from_connection")
    @patch("integrations.plex.list_resources")
    def test_all_connections_tried_within_budget(
        self,
        mock_list_resources,
        mock_fetch,
    ):
        mock_list_resources.return_value = [
            self._server("server-1", ["https://a.example"]),
        ]
        mock_fetch.return_value = [{"id": "1", "title": "Movies"}]

        sections = plex.list_sections("token")

        self.assertEqual(sections, [{"id": "1", "title": "Movies"}])
        mock_fetch.assert_called_once()

    @patch("integrations.plex.time.monotonic")
    @patch("integrations.plex._fetch_sections_from_connection")
    @patch("integrations.plex.list_resources")
    def test_stops_early_once_time_budget_is_exceeded(
        self,
        mock_list_resources,
        mock_fetch,
        mock_monotonic,
    ):
        mock_list_resources.return_value = [
            self._server("server-1", ["https://a.example"]),
            self._server("server-2", ["https://b.example"]),
        ]
        mock_fetch.side_effect = plex.PlexClientError("unreachable")
        # deadline computed once, then one in-budget check before the
        # second server's connection attempt reports the budget is spent.
        mock_monotonic.side_effect = [0, 0, 999]

        sections = plex.list_sections("token")

        self.assertEqual(sections, [])
        mock_fetch.assert_called_once()
