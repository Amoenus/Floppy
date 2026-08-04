from bs4 import BeautifulSoup
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse


class PreferencesViewTests(TestCase):
    """Tests for the preferences view."""

    def setUp(self):
        """Create user for the tests."""
        self.credentials = {"username": "testuser", "password": "testpass123"}
        self.user = get_user_model().objects.create_user(**self.credentials)
        self.client.login(**self.credentials)

    def test_preferences_post_persists_date_format(self):
        """POSTing a new date_format should persist to the DB, not just render."""
        response = self.client.post(
            reverse("preferences"),
            {"date_format": "m_d_yyyy", "time_format": "hh_mm"},
        )
        self.assertRedirects(response, reverse("preferences"))
        self.user.refresh_from_db()
        self.assertEqual(self.user.date_format, "m_d_yyyy")
        self.assertEqual(self.user.time_format, "hh_mm")

    def test_preferences_post_persists_theme(self):
        """POSTing a new theme should persist to the DB."""
        response = self.client.post(reverse("preferences"), {"theme": "light"})
        self.assertRedirects(response, reverse("preferences"))
        self.user.refresh_from_db()
        self.assertEqual(self.user.theme, "light")

    def test_preferences_post_rejects_invalid_theme(self):
        """POSTing an invalid theme value should be ignored, not persisted."""
        response = self.client.post(reverse("preferences"), {"theme": "solarized"})
        self.assertRedirects(response, reverse("preferences"))
        self.user.refresh_from_db()
        self.assertEqual(self.user.theme, "system")

    def test_preferences_save_button_is_inside_form(self):
        """Regression test for #345.

        A stray closing </div> in the template caused browsers to implicitly
        close the <form> before the submit button, making Save a silent
        no-op. Django's test client posts form data directly and never
        catches this, so assert on parsed HTML structure instead.
        """
        response = self.client.get(reverse("preferences"))
        soup = BeautifulSoup(response.content, "html.parser")

        forms = soup.find_all("form")
        preferences_form = next(
            (f for f in forms if f.find("input", {"name": "date_format"})),
            None,
        )
        self.assertIsNotNone(preferences_form, "preferences form not found")

        save_button = preferences_form.find("button", {"type": "submit"})
        self.assertIsNotNone(
            save_button,
            "Save button must be inside the preferences <form> or clicking "
            "it silently does nothing",
        )
