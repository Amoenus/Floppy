"""Checks for the guided installer's shell helpers and generated files.

The installer cannot be exercised end to end from the test suite - it installs
packages and registers system services - but the parts that silently produce a
broken installation can be: the substitution that writes every generated file,
the state file that resumption reads back, and the shape of the configuration
handed to Compose, Supervisor, and Nginx.
"""

import configparser
import subprocess
import tempfile
from pathlib import Path

import yaml
from django.test import SimpleTestCase

ROOT = Path(__file__).resolve().parents[3]
INSTALL_DIR = ROOT / "scripts" / "install"
TEMPLATE_DIR = INSTALL_DIR / "templates"

SHELL_FILES = [
    ROOT / "scripts" / "install.sh",
    INSTALL_DIR / "common.sh",
    INSTALL_DIR / "main.sh",
    INSTALL_DIR / "docker.sh",
    INSTALL_DIR / "source_common.sh",
    INSTALL_DIR / "linux_source.sh",
    INSTALL_DIR / "macos_source.sh",
    INSTALL_DIR / "finish.sh",
]


def run_helper(body, root):
    """Run a snippet with the installer helpers loaded against a temp root."""
    script = (
        "set -euo pipefail\n"
        f'FLOPPY_ROOT="{root}"\n'
        f'. "{INSTALL_DIR / "common.sh"}"\n'
        f"{body}\n"
    )
    result = subprocess.run(  # noqa: S603 - test-controlled script
        ["bash", "-c", script],  # noqa: S607
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        msg = f"helper failed: {result.stderr}"
        raise AssertionError(msg)
    return result.stdout


class InstallerShellSyntaxTests(SimpleTestCase):
    def test_every_installer_file_parses(self):
        for path in SHELL_FILES:
            with self.subTest(script=path.name):
                self.assertTrue(path.exists(), f"{path} is missing")
                result = subprocess.run(  # noqa: S603 - test-controlled script
                    ["bash", "-n", str(path)],  # noqa: S607
                    capture_output=True,
                    text=True,
                    check=False,
                )
                self.assertEqual(result.returncode, 0, result.stderr)

    def test_bootstrap_is_executable(self):
        self.assertTrue(ROOT.joinpath("scripts", "install.sh").stat().st_mode & 0o111)


class RenderTemplateTests(SimpleTestCase):
    def test_placeholders_are_replaced_including_paths_with_spaces(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "My Floppy"
            root.mkdir()
            template = root / "t.tmpl"
            template.write_text("dir=@@DIR@@\nport=@@PORT@@\n", encoding="utf-8")
            output = root / "out"
            run_helper(
                f'render_template "{template}" "{output}" "DIR={root}" "PORT=8123"',
                root,
            )
            self.assertEqual(
                output.read_text(encoding="utf-8"),
                f"dir={root}\nport=8123\n",
            )

    def test_unused_placeholder_is_left_alone_rather_than_emptied(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            template = root / "t.tmpl"
            template.write_text("a=@@A@@ b=@@B@@\n", encoding="utf-8")
            output = root / "out"
            run_helper(f'render_template "{template}" "{output}" "A=1"', root)
            self.assertEqual(output.read_text(encoding="utf-8"), "a=1 b=@@B@@\n")


class InstallStateTests(SimpleTestCase):
    def test_values_survive_a_round_trip(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "My Floppy"
            root.mkdir()
            output = run_helper(
                "state_set METHOD docker\n"
                f'state_set ROOT "{root}"\n'
                "state_set PORT 8123\n"
                "state_get METHOD\n"
                "state_get ROOT\n"
                "state_get PORT\n",
                root,
            )
            self.assertEqual(output.splitlines(), ["docker", str(root), "8123"])

    def test_rewriting_a_key_keeps_only_the_new_value(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            output = run_helper(
                "state_set PORT 8000\nstate_set PORT 9000\nstate_get PORT\n",
                root,
            )
            self.assertEqual(output.strip(), "9000")
            self.assertEqual(
                (root / "install.conf").read_text(encoding="utf-8").count("PORT="),
                1,
            )

    def test_state_file_is_not_world_readable(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            run_helper("state_set METHOD docker", root)
            mode = (root / "install.conf").stat().st_mode & 0o777
            self.assertEqual(mode, 0o600)


class PortHelperTests(SimpleTestCase):
    def test_a_listening_port_is_skipped(self):
        import socket

        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            sock.listen(1)
            busy = sock.getsockname()[1]
            with tempfile.TemporaryDirectory() as temp_dir:
                chosen = run_helper(f"first_free_port {busy}", Path(temp_dir)).strip()
            self.assertNotEqual(chosen, str(busy))
            self.assertGreater(int(chosen), busy)


class GeneratedComposeTests(SimpleTestCase):
    def render(self, root):
        output = root / "docker-compose.yml"
        run_helper(
            "render_template "
            f'"{TEMPLATE_DIR / "docker-compose.install.yml.tmpl"}" "{output}" '
            f'"ROOT={root}" "IMAGE=ghcr.io/dannyvfilms/floppy:release" '
            f'"ENV_FILE={root}/floppy.env" "DATA_DIR={root}/db" '
            f'"BACKUP_DIR={root}/backups" "REDIS_DIR={root}/redis" '
            '"BIND=127.0.0.1" "PORT=8123" "PROJECT=floppy-my-floppy"',
            root,
        )
        return yaml.safe_load(output.read_text(encoding="utf-8"))

    def test_generated_stack_is_valid_yaml_with_the_expected_wiring(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "My Floppy"
            root.mkdir()
            compose = self.render(root)

        floppy = compose["services"]["floppy"]
        self.assertEqual(floppy["image"], "ghcr.io/dannyvfilms/floppy:release")
        self.assertEqual(floppy["ports"], ["127.0.0.1:8123:8000"])
        self.assertIn(f"{root}/db:/floppy/db", floppy["volumes"])
        self.assertIn(f"{root}/backups:/floppy/backups", floppy["volumes"])
        self.assertEqual(floppy["env_file"], [f"{root}/floppy.env"])

        redis = compose["services"]["redis"]
        self.assertIn(f"{root}/redis:/data", redis["volumes"])
        self.assertIn("--appendonly yes", redis["command"])
        self.assertIn("--maxmemory-policy volatile-lru", redis["command"])

    def test_floppy_waits_for_a_healthy_redis(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            compose = self.render(root)
        self.assertEqual(
            compose["services"]["floppy"]["depends_on"]["redis"]["condition"],
            "service_healthy",
        )
        self.assertIn("healthcheck", compose["services"]["redis"])

    def test_installation_owns_its_own_project_and_no_fixed_container_names(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "My Floppy"
            root.mkdir()
            compose = self.render(root)
        # A fixed container_name would collide with, or take over, an existing
        # Floppy stack on the same host.
        self.assertEqual(compose["name"], "floppy-my-floppy")
        for name, service in compose["services"].items():
            with self.subTest(service=name):
                self.assertNotIn("container_name", service)

    def test_no_build_section_so_cloning_never_builds_an_image(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            compose = self.render(Path(temp_dir))
        for name, service in compose["services"].items():
            with self.subTest(service=name):
                self.assertNotIn("build", service)


class GeneratedSupervisorTests(SimpleTestCase):
    def render(self, root):
        output = root / "supervisord.conf"
        run_helper(
            "render_template "
            f'"{TEMPLATE_DIR / "supervisord.install.conf.tmpl"}" "{output}" '
            f'"RUN_DIR={root}/run" "LOG_DIR={root}/logs" "REDIS_DIR={root}/redis" '
            '"REDIS_SERVER=/usr/bin/redis-server" "NGINX=/usr/sbin/nginx" '
            f'"SRC_DIR={root}/repo/src" "VENV_DIR={root}/repo/.venv"',
            root,
        )
        parser = configparser.ConfigParser(interpolation=None)
        parser.read_string(output.read_text(encoding="utf-8"))
        return parser

    def test_every_process_is_defined_and_runs_from_the_installation(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "My Floppy"
            root.mkdir()
            parser = self.render(root)

        expected = {
            "program:redis",
            "program:nginx",
            "program:gunicorn",
            "program:celery",
            "program:celery-interactive",
            "program:celery-discover",
        }
        self.assertTrue(expected.issubset(set(parser.sections())))

        self.assertEqual(
            parser["program:gunicorn"]["directory"],
            f"{root}/repo/src",
        )
        self.assertIn(
            f"{root}/repo/.venv/bin",
            parser["supervisord"]["environment"],
        )
        # Unquoted, because Supervisor takes these options literally: quoting
        # them would make the quotes part of the path.
        self.assertEqual(parser["supervisord"]["logfile"], f"{root}/logs/supervisord.log")

    def test_optional_workers_follow_the_resource_profile(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            parser = self.render(Path(temp_dir))
        self.assertEqual(
            parser["program:celery-interactive"]["autostart"],
            "%(ENV_FLOPPY_START_INTERACTIVE_WORKER)s",
        )
        self.assertEqual(
            parser["program:celery-discover"]["autostart"],
            "%(ENV_FLOPPY_START_DISCOVER_WORKER)s",
        )

    def test_the_interactive_worker_never_takes_background_queues(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            parser = self.render(Path(temp_dir))
        command = parser["program:celery-interactive"]["command"]
        self.assertIn("--queues interactive", command)
        self.assertNotIn("celery,", command)


class GeneratedNginxTests(SimpleTestCase):
    def render(self, root, *, bind="0.0.0.0", port="8123"):  # noqa: S104
        output = root / "nginx.conf"
        run_helper(
            "render_template "
            f'"{TEMPLATE_DIR / "nginx.install.conf.tmpl"}" "{output}" '
            f'"RUN_DIR={root}/run" "LOG_DIR={root}/logs" '
            '"MIME_TYPES=/etc/nginx/mime.types" '
            f'"STATIC_ROOT={root}/repo/src/staticfiles" '
            f'"BIND={bind}" "PORT={port}"',
            root,
        )
        return output.read_text(encoding="utf-8")

    def test_listener_and_static_root_follow_the_answers(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "My Floppy"
            root.mkdir()
            conf = self.render(root, bind="127.0.0.1", port="9001")
        self.assertIn("listen 127.0.0.1:9001;", conf)
        self.assertIn(f'alias "{root}/repo/src/staticfiles/";', conf)
        self.assertIn("server 127.0.0.1:8001;", conf)

    def test_access_log_keeps_query_strings_out(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            conf = self.render(Path(temp_dir))
        self.assertIn("$request_method $uri $server_protocol", conf)
        self.assertNotIn("$request ", conf)
        self.assertNotIn("$query_string", conf)
        self.assertNotIn("$http_referer", conf)


class GeneratedServiceUnitTests(SimpleTestCase):
    def test_systemd_unit_runs_the_wrapper_as_the_installing_user(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "My Floppy"
            root.mkdir()
            output = root / "floppy.service"
            run_helper(
                "render_template "
                f'"{TEMPLATE_DIR / "floppy.service.tmpl"}" "{output}" '
                '"RUN_USER=media" "RUN_GROUP=media" '
                f'"SRC_DIR={root}/repo/src" "RUN_DIR={root}/run"',
                root,
            )
            unit = output.read_text(encoding="utf-8")
        self.assertIn("User=media", unit)
        self.assertIn(f"ExecStart={root}/run/floppy-supervisord", unit)
        self.assertIn("WantedBy=multi-user.target", unit)

    def test_launch_daemon_runs_the_wrapper_as_the_installing_user(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "My Floppy"
            root.mkdir()
            output = root / "com.floppy.app.plist"
            run_helper(
                "render_template "
                f'"{TEMPLATE_DIR / "com.floppy.app.plist.tmpl"}" "{output}" '
                '"RUN_USER=media" "RUN_GROUP=staff" '
                f'"SRC_DIR={root}/repo/src" "RUN_DIR={root}/run" '
                f'"LOG_DIR={root}/logs" "VENV_DIR={root}/repo/.venv" '
                '"EXTRA_PATH=/opt/homebrew/bin"',
                root,
            )
            plist = output.read_text(encoding="utf-8")
        import plistlib

        parsed = plistlib.loads(plist.encode("utf-8"))
        self.assertEqual(parsed["Label"], "com.floppy.app")
        self.assertEqual(parsed["UserName"], "media")
        self.assertEqual(
            parsed["ProgramArguments"],
            [f"{root}/run/floppy-supervisord"],
        )
        self.assertTrue(parsed["RunAtLoad"])
        self.assertTrue(parsed["KeepAlive"])


class GeneratedWrapperTests(SimpleTestCase):
    def test_wrapper_loads_configuration_and_probes_the_resource_profile(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "My Floppy"
            root.mkdir()
            output = root / "floppy-supervisord"
            run_helper(
                "render_template "
                f'"{TEMPLATE_DIR / "floppy-supervisord.tmpl"}" "{output}" '
                f'"ENV_FILE={root}/floppy.env" "VENV_DIR={root}/repo/.venv" '
                f'"SRC_DIR={root}/repo/src" "RUN_DIR={root}/run" '
                f'"LOG_DIR={root}/logs"',
                root,
            )
            wrapper = output.read_text(encoding="utf-8")
            syntax = subprocess.run(  # noqa: S603 - test-controlled script
                ["bash", "-n", str(output)],  # noqa: S607
                capture_output=True,
                text=True,
                check=False,
            )

        self.assertEqual(syntax.returncode, 0, syntax.stderr)
        self.assertIn(f'. "{root}/floppy.env"', wrapper)
        self.assertIn("from config.runtime_profile import emit_env", wrapper)
        self.assertIn("FLOPPY_START_INTERACTIVE_WORKER", wrapper)
        self.assertIn(f'exec supervisord -c "{root}/run/supervisord.conf"', wrapper)
