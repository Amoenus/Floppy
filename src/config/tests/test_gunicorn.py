import sys
from unittest import mock, skipIf

from django.test import SimpleTestCase

from config import gunicorn as gunicorn_config

# gunicorn is not available on Windows
if sys.platform != "win32":
    from gunicorn.app.wsgiapp import run


@skipIf(sys.platform == "win32", "gunicorn is not fully supported on Windows")
class GunicornConfigTests(SimpleTestCase):
    """Test Gunicorn configuration."""

    @mock.patch("django.db.connections")
    def test_pre_fork_closes_database_connections_and_pools(self, connections):
        """Workers must not inherit the master's process-local database pool."""
        pooled_connection = mock.Mock()
        unpooled_connection = mock.Mock(spec=[])
        connections.all.return_value = [pooled_connection, unpooled_connection]

        gunicorn_config.pre_fork(None, None)

        connections.close_all.assert_called_once_with()
        pooled_connection.close_pool.assert_called_once_with()

    def test_config(self):
        """Test that the Gunicorn configuration file is valid."""
        argv = [
            "gunicorn",
            "--check-config",
            "--config",
            "python:config.gunicorn",
            "config.wsgi",
        ]
        mock_argv = mock.patch.object(sys, "argv", argv)

        with self.assertRaises(SystemExit) as cm, mock_argv:
            run()

        exit_code = cm.exception.args[0]
        self.assertEqual(exit_code, 0)
