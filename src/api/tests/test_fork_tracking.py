# FORK: tests for the tracking parity endpoints — episode watch/drop,
# tag management, and the history timeline.
import datetime
from http import HTTPStatus as HTTP  # noqa: N814
from unittest.mock import patch

from app.models import Episode, ItemTag, MediaTypes, Movie, Sources, Tag

from .base import YamtrackApiTestCase

SEASON_METADATA = {
    "media_id": "1001",
    "source": Sources.TMDB.value,
    "media_type": MediaTypes.SEASON.value,
    "title": "TV Show 1",
    "original_title": "TV Show 1",
    "localized_title": "TV Show 1",
    "image": "http://example.com/tv-1-s1.jpg",
    "season_number": 1,
    "season_title": "Season 1",
    "details": {"episodes": 3},
    "episodes": [
        {
            "episode_number": number,
            "air_date": f"2023-06-0{number}",
            "image": f"http://example.com/tv-1-s1e{number}.jpg",
            "name": f"Episode {number}",
        }
        for number in (1, 2, 3)
    ],
}


def _season_metadata_side_effect(
    media_type,
    _media_id,
    _source,
    _season_numbers=None,
    *_args,
    **_kwargs,
):
    if media_type == "tv_with_seasons":
        return {**SEASON_METADATA, "season/1": SEASON_METADATA}
    return SEASON_METADATA


class EpisodeWatchTests(YamtrackApiTestCase):
    """POST/DELETE episode watch and POST episode drop."""

    def _watch(self, episode_number, payload=None, headers=None):
        return self.call_api(
            "post",
            "api_media_episode_watch",
            args=("tv", "tmdb", "1001", 1, episode_number),
            payload=payload or {},
            headers=headers or self.auth_headers,
        )

    @patch(
        "app.models.providers.services.get_media_metadata",
        side_effect=_season_metadata_side_effect,
    )
    def test_watch_creates_play(self, _mock):
        """POST watch adds an Episode play with the given end_date."""
        response = self._watch(2, payload={"end_date": "2024-03-05"})
        self.assertEqual(response.status_code, HTTP.CREATED)
        payload = response.json()
        self.assertTrue(payload["end_date"].startswith("2024-03-05"))
        self.assertTrue(
            Episode.objects.filter(
                related_season=self.season_medias[0],
                item__episode_number=2,
                end_date__date="2024-03-05",
            ).exists(),
        )

    @patch(
        "app.models.providers.services.get_media_metadata",
        side_effect=_season_metadata_side_effect,
    )
    def test_watch_defaults_end_date_to_today(self, _mock):
        """POST watch without end_date uses today."""
        response = self._watch(3)
        self.assertEqual(response.status_code, HTTP.CREATED)
        self.assertIsNotNone(response.json()["end_date"])

    def test_watch_invalid_date_rejected(self):
        """POST watch with a bad end_date returns 400."""
        response = self._watch(1, payload={"end_date": "not-a-date"})
        self.assertEqual(response.status_code, HTTP.BAD_REQUEST)

    def test_watch_non_tv_rejected(self):
        """POST watch on a non-tv media type returns 400."""
        response = self.call_api(
            "post",
            "api_media_episode_watch",
            args=("movie", "tmdb", "701", 1, 1),
            payload={},
            headers=self.auth_headers,
        )
        self.assertEqual(response.status_code, HTTP.BAD_REQUEST)

    @patch(
        "app.models.providers.services.get_media_metadata",
        side_effect=_season_metadata_side_effect,
    )
    def test_unwatch_removes_latest_play(self, _mock):
        """DELETE watch removes the most recent play only."""
        self._watch(1, payload={"end_date": "2024-01-01"})
        self._watch(1, payload={"end_date": "2024-02-01"})

        response = self.call_api(
            "delete",
            "api_media_episode_watch",
            args=("tv", "tmdb", "1001", 1, 1),
            headers=self.auth_headers,
        )
        self.assertEqual(response.status_code, HTTP.NO_CONTENT)
        remaining = Episode.objects.filter(
            related_season=self.season_medias[0],
            item__episode_number=1,
            end_date__isnull=False,
        )
        self.assertEqual(remaining.count(), 1)
        self.assertEqual(str(remaining.first().end_date.date()), "2024-01-01")

    def test_unwatch_untracked_season_not_found(self):
        """DELETE watch on an untracked season returns 404."""
        response = self.call_api(
            "delete",
            "api_media_episode_watch",
            args=("tv", "tmdb", "999999", 9, 1),
            headers=self.auth_headers,
        )
        self.assertEqual(response.status_code, HTTP.NOT_FOUND)

    @patch(
        "app.models.providers.services.get_media_metadata",
        side_effect=_season_metadata_side_effect,
    )
    def test_drop_creates_dropped_record(self, _mock):
        """POST drop records a dropped episode without watch history."""
        response = self.call_api(
            "post",
            "api_media_episode_drop",
            args=("tv", "tmdb", "1001", 1, 2),
            payload={},
            headers=self.auth_headers,
        )
        self.assertEqual(response.status_code, HTTP.CREATED)
        self.assertTrue(
            Episode.objects.filter(
                related_season=self.season_medias[0],
                item__episode_number=2,
                dropped=True,
                end_date=None,
            ).exists(),
        )


class TagTests(YamtrackApiTestCase):
    """Tag CRUD and per-item tag assignment."""

    def test_create_list_and_delete_tag(self):
        """Tags can be created, listed with counts, renamed, and deleted."""
        created = self.call_api(
            "post",
            "api_tags",
            payload={"name": "  cozy   vibes "},
            headers=self.auth_headers,
        )
        self.assertEqual(created.status_code, HTTP.CREATED)
        tag_id = created.json()["id"]
        self.assertEqual(created.json()["name"], "cozy vibes")

        duplicate = self.call_api(
            "post",
            "api_tags",
            payload={"name": "COZY VIBES"},
            headers=self.auth_headers,
        )
        self.assertEqual(duplicate.status_code, HTTP.CONFLICT)

        listed = self.call_api("get", "api_tags", headers=self.auth_headers)
        self.assertEqual(listed.status_code, HTTP.OK)
        self.assertEqual(listed.json()["results"][0]["item_count"], 0)

        renamed = self.call_api(
            "patch",
            "api_tag_detail",
            args=(tag_id,),
            payload={"name": "renamed"},
            headers=self.auth_headers,
        )
        self.assertEqual(renamed.status_code, HTTP.OK)
        self.assertEqual(renamed.json()["name"], "renamed")

        deleted = self.call_api(
            "delete",
            "api_tag_detail",
            args=(tag_id,),
            headers=self.auth_headers,
        )
        self.assertEqual(deleted.status_code, HTTP.NO_CONTENT)
        self.assertFalse(Tag.objects.filter(id=tag_id).exists())

    def test_other_users_tag_not_found(self):
        """Another user's tag cannot be renamed or deleted."""
        tag = Tag.objects.create(user=self.user2, name="theirs")
        response = self.call_api(
            "delete",
            "api_tag_detail",
            args=(tag.id,),
            headers=self.auth_headers,
        )
        self.assertEqual(response.status_code, HTTP.NOT_FOUND)

    def test_media_tags_put_replaces_assignments(self):
        """PUT media tags replaces the caller's assignments on the item."""
        movie_item = self.items_by_type[MediaTypes.MOVIE.value][0]
        keep = Tag.objects.create(user=self.user1, name="keep")
        drop = Tag.objects.create(user=self.user1, name="drop")
        ItemTag.objects.create(tag=drop, item=movie_item)

        response = self.call_api(
            "put",
            "api_media_tags",
            args=(MediaTypes.MOVIE.value, movie_item.source, movie_item.media_id),
            payload={"tag_ids": [keep.id]},
            headers=self.auth_headers,
        )
        self.assertEqual(response.status_code, HTTP.OK)
        names = [tag["name"] for tag in response.json()["results"]]
        self.assertEqual(names, ["keep"])
        self.assertFalse(ItemTag.objects.filter(tag=drop, item=movie_item).exists())

        listed = self.call_api(
            "get",
            "api_media_tags",
            args=(MediaTypes.MOVIE.value, movie_item.source, movie_item.media_id),
            headers=self.auth_headers,
        )
        self.assertEqual(listed.status_code, HTTP.OK)
        self.assertEqual(len(listed.json()["results"]), 1)

    def test_media_tags_unknown_tag_rejected(self):
        """PUT media tags with a foreign or unknown tag id returns 404."""
        movie_item = self.items_by_type[MediaTypes.MOVIE.value][0]
        foreign = Tag.objects.create(user=self.user2, name="foreign")
        response = self.call_api(
            "put",
            "api_media_tags",
            args=(MediaTypes.MOVIE.value, movie_item.source, movie_item.media_id),
            payload={"tag_ids": [foreign.id]},
            headers=self.auth_headers,
        )
        self.assertEqual(response.status_code, HTTP.NOT_FOUND)

    def test_media_tags_unknown_item_not_found(self):
        """Tag routes 404 for unknown items."""
        response = self.call_api(
            "get",
            "api_media_tags",
            args=(MediaTypes.MOVIE.value, "tmdb", "999999"),
            headers=self.auth_headers,
        )
        self.assertEqual(response.status_code, HTTP.NOT_FOUND)


class HistoryTimelineTests(YamtrackApiTestCase):
    """GET /history returns the day-grouped consumption timeline."""

    def setUp(self):
        """Give a movie play a concrete end date so it appears in history."""
        super().setUp()
        movie = self.movie_medias[0]
        movie.end_date = datetime.date(2024, 5, 10)
        movie.save(update_fields=["end_date"])

    def test_history_returns_days(self):
        """The timeline contains the movie play grouped under its day."""
        response = self.call_api("get", "api_history", headers=self.auth_headers)
        self.assertEqual(response.status_code, HTTP.OK)
        days = response.json()["results"]
        self.assertTrue(days)
        all_entries = [entry for day in days for entry in day["entries"]]
        self.assertTrue(
            any(entry["media_type"] == "movie" for entry in all_entries),
        )

    def test_history_media_type_filter(self):
        """media_type filters the timeline."""
        response = self.call_api(
            "get",
            "api_history",
            params={"media_type": "game"},
            headers=self.auth_headers,
        )
        self.assertEqual(response.status_code, HTTP.OK)
        days = response.json()["results"]
        for day in days:
            for entry in day["entries"]:
                self.assertEqual(entry["media_type"], "game")

    def test_history_invalid_int_filter_rejected(self):
        """Non-integer values for integer filters return 400."""
        response = self.call_api(
            "get",
            "api_history",
            params={"tv": "abc"},
            headers=self.auth_headers,
        )
        self.assertEqual(response.status_code, HTTP.BAD_REQUEST)


class HistoryRecordDeleteTests(YamtrackApiTestCase):
    """DELETE /history/{media_type}/{history_id} removes plays."""

    def test_delete_movie_play_removes_instance(self):
        """Deleting a movie history record removes the Movie play itself."""
        movie = self.movie_medias[0]
        movie.end_date = datetime.date(2024, 5, 10)
        movie.save(update_fields=["end_date"])
        record = movie.history.filter(history_user=self.user1).first()
        self.assertIsNotNone(record)

        response = self.call_api(
            "delete",
            "api_history_record",
            args=("movie", record.history_id),
            headers=self.auth_headers,
        )
        self.assertEqual(response.status_code, HTTP.NO_CONTENT)
        self.assertFalse(Movie.objects.filter(id=movie.id).exists())

    def test_delete_unknown_record_not_found(self):
        """Unknown history ids return 404."""
        response = self.call_api(
            "delete",
            "api_history_record",
            args=("movie", "999999"),
            headers=self.auth_headers,
        )
        self.assertEqual(response.status_code, HTTP.NOT_FOUND)

    def test_delete_other_users_record_not_found(self):
        """Another user's record cannot be deleted."""
        movie = self.movie_medias[0]
        record = movie.history.filter(history_user=self.user1).first()
        response = self.call_api(
            "delete",
            "api_history_record",
            args=("movie", record.history_id),
            headers=self.auth_headers2,
        )
        self.assertEqual(response.status_code, HTTP.NOT_FOUND)

    def test_delete_invalid_media_type_rejected(self):
        """Unsupported media types return 400."""
        response = self.call_api(
            "delete",
            "api_history_record",
            args=("invalid", "1"),
            headers=self.auth_headers,
        )
        self.assertEqual(response.status_code, HTTP.BAD_REQUEST)
