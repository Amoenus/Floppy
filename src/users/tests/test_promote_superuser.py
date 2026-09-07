"""Coverage for the promote_superuser management command."""

from io import StringIO

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase


class PromoteSuperuserTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="owner",
            password="12345",
        )

    def _run(self, *args):
        out = StringIO()
        call_command("promote_superuser", *args, stdout=out, stderr=out)
        return out.getvalue()

    def test_promotes_an_existing_account(self):
        self._run("owner")
        self.user.refresh_from_db()

        self.assertTrue(self.user.is_superuser)
        self.assertTrue(self.user.is_staff)

    def test_promoting_twice_is_harmless(self):
        self._run("owner")
        output = self._run("owner")

        self.assertIn("already a superuser", output)

    def test_unknown_account_is_an_error(self):
        with self.assertRaises(CommandError) as caught:
            self._run("nobody")

        self.assertIn("No account named", str(caught.exception))

    def test_a_username_is_required(self):
        with self.assertRaises(CommandError) as caught:
            self._run()

        self.assertIn("--list", str(caught.exception))

    def test_list_warns_when_no_superuser_exists(self):
        output = self._run("--list")

        self.assertIn("owner", output)
        self.assertIn("No superusers", output)

    def test_list_names_the_superusers(self):
        self._run("owner")
        output = self._run("--list")

        self.assertIn("1 superuser(s): owner", output)

    def test_revoke_drops_the_rights(self):
        other = get_user_model().objects.create_user(username="two", password="1")
        self._run("owner")
        self._run("two")

        self._run("--revoke", "two")
        other.refresh_from_db()

        self.assertFalse(other.is_superuser)

    def test_revoking_the_last_superuser_is_refused(self):
        """An instance with no superuser can never change instance settings."""
        self._run("owner")

        with self.assertRaises(CommandError) as caught:
            self._run("--revoke", "owner")

        self.user.refresh_from_db()
        self.assertTrue(self.user.is_superuser)
        self.assertIn("only superuser", str(caught.exception))
