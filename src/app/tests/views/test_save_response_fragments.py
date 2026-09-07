"""A failing OOB fragment must not take the rest of the save response with it."""

from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from app.models import Item, MediaTypes, Movie, Sources, Status

# Marker present in each fragment of a successful htmx save response.
FRAGMENT_MARKERS = {
    "status pill": "data-track-action-root",
    "activity subtitle": "activity-subtitle",
    "score chip": "score-chip",
    "card rating": "media-card-rating",
    "status chip": "status-chip",
    "notes section": "detail-notes-section",
}

METADATA = {
    "media_id": "238",
    "title": "Test Movie",
    "media_type": MediaTypes.MOVIE.value,
    "source": Sources.TMDB.value,
    "image": "http://example.com/image.jpg",
    "synopsis": "Test overview",
    "max_progress": 1,
    "details": {},
    "related": {},
    "cast": [],
    "crew": [],
    "studios_full": [],
}


class SaveResponseFragmentIsolationTests(TestCase):
    """media_save composes one required pill plus independent OOB fragments."""

    def setUp(self):
        self.credentials = {"username": "test", "password": "12345"}
        self.user = get_user_model().objects.create_user(**self.credentials)
        self.client.login(**self.credentials)
        self.item = Item.objects.create(
            media_id="238",
            source=Sources.TMDB.value,
            media_type=MediaTypes.MOVIE.value,
            title="Test Movie",
        )
        Movie.objects.create(
            item=self.item,
            user=self.user,
            status=Status.COMPLETED.value,
            progress=1,
            notes="a note",
        )

    def _save(self):
        return self.client.post(
            reverse("media_save"),
            {
                "media_id": "238",
                "source": Sources.TMDB.value,
                "media_type": MediaTypes.MOVIE.value,
                "status": Status.COMPLETED.value,
                "progress": 1,
                "repeats": 0,
                "notes": "a note",
            },
            headers={"hx-request": "true"},
        )

    @patch("app.views.services.get_media_metadata", return_value=METADATA)
    @patch("app.providers.services.get_media_metadata", return_value=METADATA)
    def test_healthy_save_carries_every_fragment(self, *_mocks):
        body = self._save().content.decode()
        for label, marker in FRAGMENT_MARKERS.items():
            self.assertIn(marker, body, f"{label} missing from a healthy save")

    @patch("app.views.services.get_media_metadata", return_value=METADATA)
    @patch("app.providers.services.get_media_metadata", return_value=METADATA)
    def test_one_failing_fragment_costs_only_itself(self, *_mocks):
        """The notes section is the last fragment appended.

        Before fragments were isolated, a failure here rebound the whole
        response to a bare confirmation, discarding the five fragments that had
        already rendered - and still returned 200, so the client saw most of
        the page silently not update.
        """
        with patch(
            "app.save_views._render_notes_section_oob",
            side_effect=RuntimeError("boom"),
        ):
            response = self._save()

        self.assertEqual(response.status_code, 200)
        body = response.content.decode()

        for label, marker in FRAGMENT_MARKERS.items():
            if label == "notes section":
                self.assertNotIn(marker, body, "the failing fragment should be absent")
            else:
                self.assertIn(marker, body, f"{label} was lost to an unrelated failure")

    @patch("app.views.services.get_media_metadata", return_value=METADATA)
    @patch("app.providers.services.get_media_metadata", return_value=METADATA)
    def test_an_early_failing_fragment_does_not_stop_later_ones(self, *_mocks):
        """Isolation runs both ways: a failure first must not skip the rest."""
        with patch(
            "app.save_views._build_detail_activity_state",
            side_effect=RuntimeError("boom"),
        ):
            response = self._save()

        self.assertEqual(response.status_code, 200)
        body = response.content.decode()

        self.assertNotIn(FRAGMENT_MARKERS["activity subtitle"], body)
        for label in ("status pill", "score chip", "card rating", "notes section"):
            self.assertIn(
                FRAGMENT_MARKERS[label],
                body,
                f"{label} was skipped after an earlier fragment failed",
            )
