import fnmatch
from unittest.mock import patch

from django.conf import settings
from django.test import SimpleTestCase, override_settings

from app import celery_broker


class _FakeRedisPipeline:
    def __init__(self, client):
        self.client = client
        self.operations = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def srem(self, key, *members):
        self.operations.append(("srem", key, members))
        return self

    def sadd(self, key, *members):
        self.operations.append(("sadd", key, members))
        return self

    def execute(self):
        for operation, key, members in self.operations:
            bucket = self.client.data.setdefault(key, set())
            if operation == "srem":
                bucket.difference_update(members)
            elif operation == "sadd":
                bucket.update(members)
        return []


class _FakeRedisClient:
    def __init__(self, data):
        self.data = {key: set(values) for key, values in data.items()}

    def scan_iter(self, match=None):
        for key in self.data:
            if match is None or fnmatch.fnmatch(key, match):
                yield key

    def smembers(self, key):
        return set(self.data.get(key, set()))

    def pipeline(self):
        return _FakeRedisPipeline(self)


class CeleryTaskPriorityTests(SimpleTestCase):
    """Guard the Redis priority direction.

    Kombu's Redis transport publishes priority N to the key "<queue>:N" (0 uses
    the bare "<queue>") and the worker BRPOPs those keys in ascending order, so a
    *lower* number is a *higher* priority -- the opposite of AMQP. Getting this
    backwards silently strands interactive work at the tail of the queue.
    """

    def test_priority_constants_are_ordered_for_redis(self):
        self.assertLess(
            settings.CELERY_TASK_PRIORITY_INTERACTIVE,
            settings.CELERY_TASK_PRIORITY_FOLLOWUP,
        )
        self.assertLess(
            settings.CELERY_TASK_PRIORITY_FOLLOWUP,
            settings.CELERY_TASK_DEFAULT_PRIORITY,
        )
        self.assertLess(
            settings.CELERY_TASK_DEFAULT_PRIORITY,
            settings.CELERY_TASK_PRIORITY_BACKGROUND,
        )

    def test_priority_constants_are_within_configured_steps(self):
        steps = settings.CELERY_BROKER_TRANSPORT_OPTIONS["priority_steps"]
        for name in (
            "CELERY_TASK_PRIORITY_INTERACTIVE",
            "CELERY_TASK_PRIORITY_FOLLOWUP",
            "CELERY_TASK_DEFAULT_PRIORITY",
            "CELERY_TASK_PRIORITY_BACKGROUND",
        ):
            with self.subTest(setting=name):
                self.assertIn(getattr(settings, name), steps)


class CeleryBrokerRepairTests(SimpleTestCase):
    def test_normalize_kombu_binding_member_repairs_default_separator(self):
        legacy_member = celery_broker.KOMBU_REDIS_DEFAULT_SEPARATOR.join(
            [
                "reply.celery.pidbox",
                "",
                "celery@worker.celery.pidbox",
            ],
        )

        normalized = celery_broker.normalize_kombu_binding_member(
            legacy_member,
            desired_separator=":",
        )

        self.assertEqual(
            normalized,
            "reply.celery.pidbox::celery@worker.celery.pidbox",
        )

    @override_settings(
        CELERY_BROKER_URL="redis://example:6379/0",
        CELERY_BROKER_TRANSPORT_OPTIONS={
            "sep": ":",
            "global_keyprefix": "yamtrack_",
        },
    )
    @patch("app.celery_broker.redis.Redis.from_url")
    def test_repair_celery_redis_bindings_rewrites_legacy_members(
        self,
        mock_from_url,
    ):
        legacy_member = celery_broker.KOMBU_REDIS_DEFAULT_SEPARATOR.join(
            [
                "reply.celery.pidbox",
                "",
                "celery@worker.celery.pidbox",
            ],
        )
        key = "yamtrack__kombu.binding.reply.celery.pidbox"
        fake_client = _FakeRedisClient({key: {legacy_member}})
        mock_from_url.return_value = fake_client

        summary = celery_broker.repair_celery_redis_bindings()

        self.assertEqual(
            summary,
            {
                "keys": 1,
                "members": 1,
                "repaired": 1,
                "removed": 0,
            },
        )
        self.assertEqual(
            fake_client.data[key],
            {"reply.celery.pidbox::celery@worker.celery.pidbox"},
        )

    @override_settings(
        CELERY_BROKER_URL="redis://example:6379/0",
        CELERY_BROKER_TRANSPORT_OPTIONS={"sep": ":"},
    )
    @patch("app.celery_broker.redis.Redis.from_url")
    def test_repair_celery_redis_bindings_drops_malformed_members(
        self,
        mock_from_url,
    ):
        fake_client = _FakeRedisClient(
            {
                "_kombu.binding.reply.celery.pidbox": {
                    "invalid-binding-entry",
                },
            },
        )
        mock_from_url.return_value = fake_client

        summary = celery_broker.repair_celery_redis_bindings()

        self.assertEqual(summary["removed"], 1)
        self.assertEqual(
            fake_client.data["_kombu.binding.reply.celery.pidbox"],
            set(),
        )
