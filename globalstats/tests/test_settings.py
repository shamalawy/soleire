"""Configuration behaviour that must fail loudly rather than silently."""

import os
from unittest import mock

from django.core.exceptions import ImproperlyConfigured
from django.test import SimpleTestCase

from soleir import env


class EnvReaderTests(SimpleTestCase):
    def test_blank_values_count_as_unset(self):
        with mock.patch.dict(os.environ, {"X": "   "}):
            self.assertEqual(env.get("X", "fallback"), "fallback")

    def test_booleans(self):
        for raw, expected in [
            ("true", True),
            ("1", True),
            ("On", True),
            ("false", False),
            ("0", False),
            ("no", False),
        ]:
            with mock.patch.dict(os.environ, {"FLAG": raw}):
                self.assertIs(env.get_bool("FLAG"), expected)

    def test_a_nonsense_boolean_raises_instead_of_defaulting(self):
        """Silently reading DJANGO_DEBUG=maybe as False would be worse."""
        with mock.patch.dict(os.environ, {"FLAG": "maybe"}):
            with self.assertRaises(ImproperlyConfigured):
                env.get_bool("FLAG")

    def test_integers_and_lists(self):
        with mock.patch.dict(os.environ, {"N": "42", "L": "a, b ,,c"}):
            self.assertEqual(env.get_int("N", 0), 42)
            self.assertEqual(env.get_list("L"), ["a", "b", "c"])

    def test_a_nonsense_integer_raises(self):
        with mock.patch.dict(os.environ, {"N": "lots"}):
            with self.assertRaises(ImproperlyConfigured):
                env.get_int("N", 0)


class DatabaseUrlTests(SimpleTestCase):
    def test_parses_a_full_url(self):
        parsed = env.parse_database_url("postgres://bob:s3cr%40t@db.example:6543/soleire")
        self.assertEqual(parsed["NAME"], "soleire")
        self.assertEqual(parsed["USER"], "bob")
        self.assertEqual(parsed["PASSWORD"], "s3cr@t")  # percent-decoded
        self.assertEqual(parsed["HOST"], "db.example")
        self.assertEqual(parsed["PORT"], "6543")

    def test_rejects_a_non_postgres_scheme(self):
        """Quietly falling back to SQLite would hide the misconfiguration until
        the first Postgres-specific query failed."""
        with self.assertRaises(ImproperlyConfigured):
            env.parse_database_url("sqlite:///db.sqlite3")

    def test_rejects_a_url_without_a_database_name(self):
        with self.assertRaises(ImproperlyConfigured):
            env.parse_database_url("postgres://bob@db.example:5432/")


class DeployedSettingsTests(SimpleTestCase):
    def test_project_settings_are_postgres(self):
        from django.conf import settings

        self.assertEqual(settings.DATABASES["default"]["ENGINE"], "django.db.backends.postgresql")

    def test_no_secret_key_is_committed(self):
        """The original settings carried a literal SECRET_KEY in version control."""
        from pathlib import Path

        source = (Path(__file__).resolve().parents[2] / "soleir" / "settings.py").read_text()
        self.assertNotIn("django-insecure-=uj6", source)
        self.assertIn("DJANGO_SECRET_KEY", source)

    def test_security_headers_are_configured(self):
        from django.conf import settings

        self.assertEqual(settings.X_FRAME_OPTIONS, "DENY")
        self.assertTrue(settings.SECURE_CONTENT_TYPE_NOSNIFF)
        self.assertTrue(settings.SESSION_COOKIE_HTTPONLY)

    def test_static_root_is_set_so_collectstatic_works(self):
        from django.conf import settings

        self.assertTrue(settings.STATIC_ROOT)

    def test_timezone_is_irish(self):
        from django.conf import settings

        self.assertEqual(settings.TIME_ZONE, "Europe/Dublin")
