"""View behaviour: access control, ownership isolation, and HTTP method safety."""

import json
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from django.urls import reverse

from globalstats.models import MonthlyGeneration, PVSystem
from globalstats.tests.factories import (
    make_cohort,
    make_full_year,
    make_reading,
    make_system,
    make_user,
)

PASSWORD = "correct-horse-battery"

# Registration collects nothing but a password and an acknowledgement — the
# handle is issued by the server and is never posted.
REGISTRATION_POST = {
    "password1": PASSWORD,
    "password2": PASSWORD,
    "saved_credentials": "on",
}


@override_settings(SOLEIRE_MIN_GROUP_SIZE=1, STATS_CACHE_SECONDS=0)
class PublicPageTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        make_cohort(3, county="Cork", year=2025)

    def test_every_public_page_renders(self):
        for name in ("home", "county_stats", "trends", "system_comparison", "about"):
            with self.subTest(page=name):
                self.assertEqual(self.client.get(reverse(name)).status_code, 200)

    def test_public_pages_need_no_login(self):
        response = self.client.get(reverse("county_stats"))
        self.assertNotIn("/accounts/login/", response.get("Location", ""))

    def test_hostile_query_string_does_not_break_the_page(self):
        response = self.client.get(
            reverse("county_stats"),
            {"year": "banana", "month": "<script>alert(1)</script>", "county": "'; DROP TABLE"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertNotIn(b"<script>alert(1)</script>", response.content)

    def test_healthz_reports_the_database(self):
        response = self.client.get(reverse("healthz"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(json.loads(response.content)["database"], "ok")

    def test_legacy_urls_still_resolve(self):
        for old, new in (
            ("/statistics/", reverse("my_records")),
            ("/county_totals/", reverse("county_stats")),
            ("/login/", reverse("login")),
        ):
            with self.subTest(url=old):
                response = self.client.get(old)
                self.assertEqual(response.status_code, 301)
                self.assertEqual(response["Location"], new)

    def test_empty_database_still_renders(self):
        MonthlyGeneration.objects.all().delete()
        PVSystem.objects.all().delete()
        for name in ("home", "county_stats", "trends", "system_comparison", "about"):
            with self.subTest(page=name):
                self.assertEqual(self.client.get(reverse(name)).status_code, 200)


@override_settings(SOLEIRE_MIN_GROUP_SIZE=1, STATS_CACHE_SECONDS=0)
class AnonymityTests(TestCase):
    """No public response may carry a contributor's identity."""

    @classmethod
    def setUpTestData(cls):
        cls.user = make_user(username="identifiable-person", email="me@example.com")
        system = make_system(owner=cls.user, county="Cork")
        make_full_year(system)
        make_cohort(2, county="Cork")

    def test_no_public_page_leaks_a_username_or_email(self):
        pages = [
            reverse("home"),
            reverse("county_stats"),
            reverse("trends"),
            reverse("system_comparison"),
            reverse("about"),
            reverse("export_counties_csv"),
            reverse("export_monthly_csv"),
            reverse("stats_api", args=["counties"]),
            reverse("stats_api", args=["monthly"]),
            reverse("stats_api", args=["summary"]),
            reverse("stats_api", args=["orientation"]),
        ]
        for url in pages:
            with self.subTest(url=url):
                body = self.client.get(url).content
                self.assertNotIn(b"identifiable-person", body)
                self.assertNotIn(b"me@example.com", body)

    def test_api_carries_no_owner_or_system_identifiers(self):
        payload = json.loads(self.client.get(reverse("stats_api", args=["counties"])).content)
        serialised = json.dumps(payload)
        self.assertNotIn("owner", serialised)
        self.assertNotIn("system_id", serialised)
        self.assertNotIn("username", serialised)

    def test_unknown_api_dataset_is_a_404(self):
        self.assertEqual(
            self.client.get(reverse("stats_api", args=["everything"])).status_code, 404
        )


class AuthBoundaryTests(TestCase):
    """Every contributor page must refuse an anonymous visitor."""

    @classmethod
    def setUpTestData(cls):
        cls.owner = make_user(username="owner")
        cls.system = make_system(owner=cls.owner)
        cls.reading = make_reading(cls.system, year=2024, month=5)

    def test_private_pages_redirect_to_login(self):
        urls = [
            reverse("my_records"),
            reverse("export_my_data"),
            reverse("system_create"),
            reverse("system_detail", args=[self.system.pk]),
            reverse("system_edit", args=[self.system.pk]),
            reverse("system_delete", args=[self.system.pk]),
            reverse("reading_bulk", args=[self.system.pk]),
            reverse("reading_create", args=[self.system.pk]),
            reverse("benchmark", args=[self.system.pk]),
            reverse("reading_edit", args=[self.reading.pk]),
            reverse("reading_delete", args=[self.reading.pk]),
            reverse("delete_account"),
        ]
        for url in urls:
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 302)
                self.assertIn(reverse("login"), response["Location"])


class OwnershipIsolationTests(TestCase):
    """One contributor must never reach another's rows, even by guessing an id."""

    @classmethod
    def setUpTestData(cls):
        cls.owner = make_user(username="owner", password=PASSWORD)
        cls.intruder = make_user(username="intruder", password=PASSWORD)
        cls.system = make_system(owner=cls.owner)
        cls.reading = make_reading(cls.system, year=2024, month=5)

    def setUp(self):
        self.client.login(username="intruder", password=PASSWORD)

    def test_another_users_pages_are_404_not_403(self):
        """404 rather than 403: a 403 would confirm the record exists."""
        urls = [
            reverse("system_detail", args=[self.system.pk]),
            reverse("system_edit", args=[self.system.pk]),
            reverse("system_delete", args=[self.system.pk]),
            reverse("reading_bulk", args=[self.system.pk]),
            reverse("benchmark", args=[self.system.pk]),
            reverse("reading_edit", args=[self.reading.pk]),
            reverse("reading_delete", args=[self.reading.pk]),
        ]
        for url in urls:
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 404)

    def test_posting_to_another_users_record_changes_nothing(self):
        response = self.client.post(
            reverse("reading_edit", args=[self.reading.pk]),
            {"year": 2024, "month": 5, "energy_generated_kwh": "99999"},
        )
        self.assertEqual(response.status_code, 404)
        self.reading.refresh_from_db()
        self.assertEqual(self.reading.energy_generated_kwh, Decimal("400.00"))

    def test_deleting_another_users_record_changes_nothing(self):
        self.client.post(reverse("reading_delete", args=[self.reading.pk]))
        self.assertTrue(MonthlyGeneration.objects.filter(pk=self.reading.pk).exists())

    def test_my_records_lists_only_my_own(self):
        response = self.client.get(reverse("my_records"))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, str(self.system))

    def test_export_contains_only_my_own(self):
        body = self.client.get(reverse("export_my_data")).content
        self.assertNotIn(b"400.00", body)


class DestructiveMethodTests(TestCase):
    """Deletion used to happen on a GET link, which a prefetcher could fire."""

    def setUp(self):
        self.owner = make_user(username="owner", password=PASSWORD)
        self.system = make_system(owner=self.owner)
        self.reading = make_reading(self.system, year=2024, month=5)
        self.client.login(username="owner", password=PASSWORD)

    def test_get_on_delete_only_shows_a_confirmation(self):
        response = self.client.get(reverse("reading_delete", args=[self.reading.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertTrue(MonthlyGeneration.objects.filter(pk=self.reading.pk).exists())

    def test_post_actually_deletes(self):
        response = self.client.post(reverse("reading_delete", args=[self.reading.pk]))
        self.assertEqual(response.status_code, 302)
        self.assertFalse(MonthlyGeneration.objects.filter(pk=self.reading.pk).exists())

    def test_deleting_a_system_takes_its_readings(self):
        self.client.post(reverse("system_delete", args=[self.system.pk]))
        self.assertFalse(PVSystem.objects.filter(pk=self.system.pk).exists())
        self.assertFalse(MonthlyGeneration.objects.filter(pk=self.reading.pk).exists())

    def test_logout_rejects_get(self):
        """Django 5 requires POST; a GET logout link is CSRF-able."""
        self.assertEqual(self.client.get(reverse("logout")).status_code, 405)
        self.assertEqual(self.client.post(reverse("logout")).status_code, 302)


class ContributionFlowTests(TestCase):
    def setUp(self):
        self.user = make_user(username="owner", password=PASSWORD)
        self.client.login(username="owner", password=PASSWORD)

    def test_register_issues_a_handle_and_logs_the_user_in(self):
        """The old view passed authenticate()'s result to login() unchecked,
        which crashed with TypeError whenever it returned None."""
        self.client.logout()
        page = self.client.get(reverse("register"))
        handle = page.context["handle"]
        self.assertRegex(handle, r"^[a-z]+-[a-z]+-\d{4}$")

        response = self.client.post(reverse("register"), REGISTRATION_POST)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], reverse("welcome"))
        user = User.objects.get(username=handle)
        self.assertEqual(int(self.client.session["_auth_user_id"]), user.pk)

    def test_creating_a_system_assigns_the_logged_in_owner(self):
        response = self.client.post(
            reverse("system_create"),
            {
                "label": "Roof",
                "county": "Cork",
                "orientation": "S",
                "array_size_kwp": "4.50",
                "inverter_size_kw": "4.00",
                "battery_capacity_kwh": "",
                "commissioned_year": "",
            },
        )
        self.assertEqual(response.status_code, 302)
        system = PVSystem.objects.get()
        self.assertEqual(system.owner, self.user)

    def test_bulk_entry_creates_then_updates(self):
        system = make_system(owner=self.user, array="4.00")
        url = reverse("reading_bulk", args=[system.pk])

        self.client.post(url, {"year": 2024, "month_1": "50", "month_2": "80"})
        self.assertEqual(MonthlyGeneration.objects.filter(system=system).count(), 2)

        self.client.post(url, {"year": 2024, "month_1": "60", "month_3": "120"})
        readings = {
            r.month: r.energy_generated_kwh for r in MonthlyGeneration.objects.filter(system=system)
        }
        self.assertEqual(readings[1], Decimal("60.00"))  # updated
        self.assertEqual(readings[2], Decimal("80.00"))  # untouched
        self.assertEqual(readings[3], Decimal("120.00"))  # created

    def test_bulk_entry_is_all_or_nothing(self):
        system = make_system(owner=self.user, array="4.00")
        self.client.post(
            reverse("reading_bulk", args=[system.pk]),
            {"year": 2024, "month_1": "50", "month_6": "40000"},  # month 6 implausible
        )
        self.assertEqual(MonthlyGeneration.objects.filter(system=system).count(), 0)

    def test_export_round_trips_my_readings(self):
        system = make_system(owner=self.user, county="Cork", array="4.00")
        make_reading(system, year=2024, month=5, kwh="321.00")
        body = self.client.get(reverse("export_my_data")).content.decode()
        self.assertIn("321.00", body)
        self.assertIn("Cork", body)
        self.assertIn("kwh_per_kwp", body)


class AccountDeletionTests(TestCase):
    def setUp(self):
        self.user = make_user(username="leaver", password=PASSWORD)
        system = make_system(owner=self.user)
        make_reading(system, year=2024, month=5)
        self.client.login(username="leaver", password=PASSWORD)

    def test_wrong_confirmation_keeps_the_account(self):
        self.client.post(reverse("delete_account"), {"confirm": "not-my-name"})
        self.assertTrue(User.objects.filter(username="leaver").exists())

    def test_correct_confirmation_erases_everything(self):
        response = self.client.post(reverse("delete_account"), {"confirm": "leaver"})
        self.assertEqual(response.status_code, 302)
        self.assertFalse(User.objects.filter(username="leaver").exists())
        self.assertEqual(PVSystem.objects.count(), 0)
        self.assertEqual(MonthlyGeneration.objects.count(), 0)


@override_settings(SOLEIRE_MIN_GROUP_SIZE=1, STATS_CACHE_SECONDS=0)
class ExportTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        make_cohort(3, county="Cork", year=2025, kwh_per_month="100.00")

    def test_county_csv_has_a_header_and_rows(self):
        response = self.client.get(reverse("export_counties_csv"))
        self.assertEqual(response.status_code, 200)
        self.assertIn("text/csv", response["Content-Type"])
        self.assertIn("attachment", response["Content-Disposition"])
        lines = response.content.decode().splitlines()
        self.assertTrue(lines[0].startswith("county,province"))
        self.assertTrue(any(line.startswith("Cork") for line in lines))

    @override_settings(SOLEIRE_MIN_GROUP_SIZE=5)
    def test_csv_respects_the_suppression_threshold(self):
        body = self.client.get(reverse("export_counties_csv")).content.decode()
        cork = next(line for line in body.splitlines() if line.startswith("Cork"))
        self.assertEqual(cork, "Cork,Munster,,,,,")


class AnonymousRegistrationTests(TestCase):
    """Registration must not be able to collect personal information at all."""

    def test_the_form_offers_no_username_or_email_input(self):
        html = self.client.get(reverse("register")).content.decode()
        self.assertNotIn('type="email"', html)
        self.assertNotIn('name="email"', html)
        # The handle input exists so password managers store it, but it is
        # read-only and the server ignores whatever comes back.
        self.assertIn('name="username"', html)
        self.assertIn("readonly", html)
        self.assertIn('autocomplete="username"', html)

    def test_a_posted_username_cannot_override_the_issued_handle(self):
        handle = self.client.get(reverse("register")).context["handle"]
        self.client.post(
            reverse("register"),
            {**REGISTRATION_POST, "username": "sean.murphy@example.com"},
        )
        self.assertTrue(User.objects.filter(username=handle).exists())
        self.assertFalse(User.objects.filter(username="sean.murphy@example.com").exists())

    def test_a_posted_email_is_discarded(self):
        handle = self.client.get(reverse("register")).context["handle"]
        self.client.post(reverse("register"), {**REGISTRATION_POST, "email": "me@example.com"})
        self.assertEqual(User.objects.get(username=handle).email, "")

    def test_the_handle_survives_a_reload(self):
        """Someone who has already copied it must not have it swapped out."""
        first = self.client.get(reverse("register")).context["handle"]
        second = self.client.get(reverse("register")).context["handle"]
        self.assertEqual(first, second)

    def test_the_handle_survives_a_failed_submission(self):
        handle = self.client.get(reverse("register")).context["handle"]
        response = self.client.post(reverse("register"), {"password1": "x", "password2": "y"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["handle"], handle)

    def test_the_acknowledgement_is_required(self):
        data = {k: v for k, v in REGISTRATION_POST.items() if k != "saved_credentials"}
        response = self.client.post(reverse("register"), data)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(User.objects.count(), 0)

    def test_password_is_stored_as_an_argon2id_hash(self):
        handle = self.client.get(reverse("register")).context["handle"]
        self.client.post(reverse("register"), REGISTRATION_POST)
        stored = User.objects.get(username=handle).password
        self.assertTrue(stored.startswith("argon2$argon2id$"))
        self.assertNotIn(PASSWORD, stored)

    def test_the_new_account_can_sign_in_with_its_handle(self):
        handle = self.client.get(reverse("register")).context["handle"]
        self.client.post(reverse("register"), REGISTRATION_POST)
        self.client.logout()
        self.assertTrue(self.client.login(username=handle, password=PASSWORD))

    def test_welcome_page_shows_the_handle_and_the_warning(self):
        handle = self.client.get(reverse("register")).context["handle"]
        self.client.post(reverse("register"), REGISTRATION_POST)
        response = self.client.get(reverse("welcome"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, handle)
        self.assertContains(response, "permanently")
        self.assertContains(response, "data-copy-target")

    def test_welcome_page_requires_a_login(self):
        response = self.client.get(reverse("welcome"))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("login"), response["Location"])

    def test_two_visitors_get_different_handles(self):
        from django.test import Client

        first = Client().get(reverse("register")).context["handle"]
        second = Client().get(reverse("register")).context["handle"]
        self.assertNotEqual(first, second)

    def test_a_signed_in_user_is_sent_away(self):
        make_user(username="already-here-1234", password=PASSWORD)
        self.client.login(username="already-here-1234", password=PASSWORD)
        response = self.client.get(reverse("register"))
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], reverse("my_records"))
