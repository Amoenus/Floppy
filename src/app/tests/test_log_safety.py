import logging

from django.test import SimpleTestCase

from app.log_safety import (
    exception_summary,
    install_redacting_log_record_factory,
    presence_map,
    redact_secrets,
    safe_url,
    stable_hmac,
)


def _raise_secret_error():
    raise RuntimeError("provider failed: api_key=plain-secret")


class _UnrenderableLogValue:
    def __str__(self):
        raise RuntimeError("access_token=plain-secret")


class LogSafetyTests(SimpleTestCase):
    def test_exception_summary_includes_status_without_message(self):
        response = type("Response", (), {"status_code": 404})()
        exc = Exception("contains secrets")
        exc.response = response

        self.assertEqual(exception_summary(exc), "Exception(status=404)")

    def test_presence_map_redacts_values(self):
        values = {"tmdb_id": "123", "imdb_id": "", "tvdb_id": None}

        self.assertEqual(
            presence_map(values, ("tmdb_id", "imdb_id", "tvdb_id")),
            {"tmdb_id": True, "imdb_id": False, "tvdb_id": False},
        )

    def test_safe_url_drops_query_and_fragment(self):
        self.assertEqual(
            safe_url("https://example.com/library?token=secret#frag"),
            "https://example.com/library",
        )

    def test_stable_hmac_is_namespaced_and_deterministic(self):
        digest = stable_hmac("value", namespace="discover")

        self.assertEqual(digest, stable_hmac("value", namespace="discover"))
        self.assertNotEqual(digest, stable_hmac("value", namespace="history"))

    def test_redact_secrets_strips_bearer_tokens(self):
        line = "[INFO] Authorization: Bearer abc123.def-456_ghi== sent to trakt"

        self.assertEqual(
            redact_secrets(line),
            "[INFO] Authorization: [REDACTED]",
        )

    def test_redact_secrets_strips_basic_authorization(self):
        self.assertEqual(
            redact_secrets("Authorization: Basic dXNlcjpwYXNz"),
            "Authorization: [REDACTED]",
        )

    def test_redact_secrets_strips_cookie_header(self):
        result = redact_secrets("Cookie: sessionid=session-secret; csrftoken=csrf-secret")

        self.assertEqual(result, "Cookie: [REDACTED]")

    def test_redact_secrets_strips_url_credentials(self):
        result = redact_secrets("proxy=socks5://user:password@proxy.example:1080")

        self.assertNotIn("user:password", result)
        self.assertIn("socks5://[REDACTED]:[REDACTED]@proxy.example:1080", result)

    def test_redact_secrets_strips_named_params(self):
        line = (
            "GET https://plex.example/library?X-Plex-Token=abcDEF123&size=10 "
            "api_key=deadbeef password: hunter2"
        )

        result = redact_secrets(line)

        self.assertNotIn("abcDEF123", result)
        self.assertNotIn("deadbeef", result)
        self.assertNotIn("hunter2", result)
        self.assertIn("size=10", result)

    def test_redact_secrets_strips_quoted_json_values_with_spaces(self):
        result = redact_secrets('{"password": "two words", "size": 10}')

        self.assertEqual(result, '{"password": "[REDACTED]", "size": 10}')

    def test_redact_secrets_strips_quoted_repr_values_with_spaces(self):
        result = redact_secrets("{'api_key': 'two words', 'size': 10}")

        self.assertEqual(result, "{'api_key': '[REDACTED]', 'size': 10}")

    def test_redact_secrets_strips_every_credential_name_spelling(self):
        """Integrations spell the same credential in four different styles."""
        for line in (
            "authToken=plain-secret",
            "accessToken=plain-secret",
            "auth_token=plain-secret",
            "X-Api-Key: plain-secret",
            "TMDB_API_KEY=plain-secret",
            "webhook_secret=plain-secret",
            'headers={"authToken": "plain-secret"}',
        ):
            with self.subTest(line=line):
                self.assertNotIn("plain-secret", redact_secrets(line))

    def test_redact_secrets_keeps_names_that_only_end_in_a_keyword_word(self):
        """Diagnostic fields must stay readable, so match whole name parts."""
        for line in (
            "request finished status_code=200 in 0.04s",
            "error_code=RATE_LIMIT retry_after=30",
            "token_count=512 model=default",
            "tokenizer_config=default",
        ):
            with self.subTest(line=line):
                self.assertEqual(redact_secrets(line), line)

    def test_redact_secrets_strips_list_values(self):
        """Django writes form data as a QueryDict repr with list values."""
        result = redact_secrets("<QueryDict: {'password': ['plain-secret']}>")

        self.assertEqual(result, "<QueryDict: {'password': [REDACTED]}>")

    def test_redact_secrets_handles_empty_input(self):
        self.assertEqual(redact_secrets(""), "")
        self.assertEqual(redact_secrets(None), "")

    def test_record_factory_scrubs_rendered_arguments(self):
        install_redacting_log_record_factory()
        logger = logging.getLogger("app.tests.log_safety.arguments")

        with self.assertLogs(logger, level="INFO") as captured:
            logger.info(
                "GET %s",
                "https://example.test/library?access_token=plain-secret",
            )

        output = "\n".join(captured.output)
        self.assertNotIn("plain-secret", output)
        self.assertIn("access_token=[REDACTED]", output)

    def test_record_factory_scrubs_exception_text_and_tuple(self):
        install_redacting_log_record_factory()
        logger = logging.getLogger("app.tests.log_safety.exception")

        with self.assertLogs(logger, level="ERROR") as captured:
            try:
                _raise_secret_error()
            except RuntimeError:
                logger.exception("Provider request failed")

        output = "\n".join(captured.output)
        record = captured.records[0]
        self.assertNotIn("plain-secret", output)
        self.assertIn("api_key=[REDACTED]", output)
        self.assertIsNone(record.exc_info)
        self.assertNotIn("plain-secret", record.exc_text)

    def test_record_factory_fails_closed_when_message_cannot_render(self):
        install_redacting_log_record_factory()
        logger = logging.getLogger("app.tests.log_safety.failure")

        with self.assertLogs(logger, level="ERROR") as captured:
            logger.error("Provider value: %s", _UnrenderableLogValue())

        output = "\n".join(captured.output)
        self.assertNotIn("plain-secret", output)
        self.assertIn("Log message redaction failed", output)

    def test_record_factory_is_installed_once(self):
        install_redacting_log_record_factory()
        first_factory = logging.getLogRecordFactory()
        install_redacting_log_record_factory()

        self.assertIs(logging.getLogRecordFactory(), first_factory)
        self.assertTrue(getattr(first_factory, "_floppy_redacts_secrets", False))

    def test_record_factory_leaves_ordinary_text_unchanged(self):
        install_redacting_log_record_factory()
        record = logging.getLogger("app.tests.log_safety.ordinary").makeRecord(
            name="app.tests.log_safety.ordinary",
            level=logging.INFO,
            fn=__file__,
            lno=1,
            msg="Media item %s updated",
            args=(123,),
            exc_info=None,
        )

        self.assertEqual(record.getMessage(), "Media item 123 updated")
