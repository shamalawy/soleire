"""Regressions: each test here pins a defect that was found and fixed.

Kept together so the reason each behaviour exists stays attached to it.
"""

from decimal import Decimal

from django.contrib.auth.models import User
from django.db import IntegrityError, transaction
from django.test import TestCase, override_settings
from django.urls import reverse

from globalstats import stats
from globalstats.constants import Orientation
from globalstats.forms import PVSystemForm
from globalstats.models import MIN_SYSTEM_SIZE, PVSystem
from globalstats.tests.factories import (
    make_cohort,
    make_full_year,
    make_reading,
    make_system,
    make_user,
)

PASSWORD = "correct-horse-battery"


class ValidatorConstraintAgreementTests(TestCase):
    """Field validators and check constraints must draw the same line.

    They did not: the constraint allowed anything above zero while the
    validator demanded 0.10, so a 0.05 kWp row could sit in the database and
    then refuse to save when its owner opened the edit form.
    """

    def test_the_database_refuses_what_the_form_refuses(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            PVSystem.objects.create(
                owner=make_user(),
                county="Cork",
                orientation=Orientation.SOUTH,
                array_size_kwp=Decimal("0.05"),
                inverter_size_kw=Decimal("3.00"),
            )

    def test_the_same_holds_for_the_inverter(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            PVSystem.objects.create(
                owner=make_user(),
                county="Cork",
                orientation=Orientation.SOUTH,
                array_size_kwp=Decimal("4.00"),
                inverter_size_kw=Decimal("0.05"),
            )

    def test_a_stored_system_is_always_editable_by_its_owner(self):
        """The point of the agreement: nothing in the table is un-editable."""
        system = make_system(array=str(MIN_SYSTEM_SIZE), inverter=str(MIN_SYSTEM_SIZE))
        form = PVSystemForm(
            {
                "label": "",
                "county": system.county,
                "orientation": system.orientation,
                "array_size_kwp": system.array_size_kwp,
                "inverter_size_kw": system.inverter_size_kw,
                "battery_capacity_kwh": "",
                "commissioned_year": "",
            },
            instance=system,
        )
        self.assertTrue(form.is_valid(), form.errors)

    def test_a_negative_battery_is_a_field_error_not_a_500(self):
        """battery_capacity_kwh had a maximum but no minimum, so a negative
        value cleared the form and only blew up at the check constraint."""
        user = make_user(username="battery-owner", password=PASSWORD)
        self.client.login(username="battery-owner", password=PASSWORD)
        response = self.client.post(
            reverse("system_create"),
            {
                "label": "",
                "county": "Cork",
                "orientation": "S",
                "array_size_kwp": "4.00",
                "inverter_size_kw": "3.50",
                "battery_capacity_kwh": "-5.00",
                "commissioned_year": "",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("battery_capacity_kwh", response.context["form"].errors)
        self.assertFalse(PVSystem.objects.filter(owner=user).exists())


@override_settings(SOLEIRE_MIN_GROUP_SIZE=3, STATS_CACHE_SECONDS=0)
class NationalSuppressionTests(TestCase):
    """The national headline needs the same floor as every other bucket.

    With two contributors and no threshold, the national energy total handed
    each of them the other's output by subtraction, while every county row sat
    dutifully suppressed.
    """

    def test_totals_are_withheld_below_the_threshold(self):
        make_cohort(2, county="Cork")
        summary = stats.national_summary()
        self.assertTrue(summary["suppressed"])
        self.assertIsNone(summary["total_energy_kwh"])
        self.assertIsNone(summary["monthly_yield"])
        self.assertIsNone(summary["installed_capacity_kwp"])
        self.assertIsNone(summary["median_monthly_yield"])

    def test_participation_counts_are_still_shown(self):
        """Knowing four people have signed up identifies nobody, and hiding it
        would make a young site look broken rather than new."""
        make_cohort(2, county="Cork")
        summary = stats.national_summary()
        self.assertEqual(summary["contributors"], 2)
        self.assertEqual(summary["systems"], 2)
        self.assertGreater(summary["readings"], 0)

    def test_totals_appear_once_the_threshold_is_met(self):
        make_cohort(3, county="Cork")
        summary = stats.national_summary()
        self.assertFalse(summary["suppressed"])
        self.assertIsNotNone(summary["total_energy_kwh"])

    def test_the_home_page_survives_a_suppressed_headline(self):
        make_cohort(2, county="Cork")
        self.assertEqual(self.client.get(reverse("home")).status_code, 200)

    def test_the_api_reflects_the_same_suppression(self):
        import json

        make_cohort(2, county="Cork")
        payload = json.loads(self.client.get(reverse("stats_api", args=["summary"])).content)
        self.assertIsNone(payload["data"]["total_energy_kwh"])


@override_settings(SOLEIRE_MIN_GROUP_SIZE=1, STATS_CACHE_SECONDS=0)
class BenchmarkComparabilityTests(TestCase):
    """Both sides of the benchmark must be summed the same way.

    A contributor's own annual figure is the sum of their monthly kWh/kWp. The
    peer figure has to be the sum of the peers' monthly kWh/kWp over the *same*
    months. Replacing it with total-energy-over-total-capacity would produce a
    per-month average and compare it against a multi-month sum, inflating the
    difference by roughly the number of months reported.
    """

    def test_peer_annual_is_the_sum_of_monthly_yields(self):
        peer = make_system(owner=make_user(), county="Clare", array="4.00")
        make_reading(peer, year=2025, month=6, kwh="400.00")  # 100 kWh/kWp
        make_reading(peer, year=2025, month=12, kwh="40.00")  #  10 kWh/kWp

        mine = make_system(owner=make_user(), county="Clare", array="4.00")
        make_reading(mine, year=2025, month=6, kwh="400.00")
        make_reading(mine, year=2025, month=12, kwh="40.00")

        report = stats.benchmark_system(mine, 2025)
        # Own: (400 + 40) / 4 = 110. County: 100 + 10 across the two months,
        # once my own readings join the pool — identical, so the delta is zero.
        self.assertEqual(report["own_annual_yield"], 110.0)
        self.assertEqual(report["county_annual_yield"], 110.0)
        self.assertEqual(report["vs_county_pct"], 0.0)

    def test_an_average_system_reads_as_average_even_when_capacity_varies(self):
        """The peers' total capacity changes month to month here. A system
        performing exactly at the peer average must still come out at 0%."""
        big = make_system(owner=make_user(), county="Clare", array="10.00")
        small = make_system(owner=make_user(), county="Clare", array="2.00")
        # June: both report. December: only the big one does.
        make_reading(big, year=2025, month=6, kwh="1000.00")  # 100 kWh/kWp
        make_reading(small, year=2025, month=6, kwh="200.00")  # 100 kWh/kWp
        make_reading(big, year=2025, month=12, kwh="100.00")  #  10 kWh/kWp

        mine = make_system(owner=make_user(), county="Clare", array="4.00")
        make_reading(mine, year=2025, month=6, kwh="400.00")  # 100 kWh/kWp
        make_reading(mine, year=2025, month=12, kwh="40.00")  #  10 kWh/kWp

        report = stats.benchmark_system(mine, 2025)
        self.assertEqual(report["own_annual_yield"], 110.0)
        self.assertEqual(report["vs_county_pct"], 0.0)

    def test_a_partial_year_is_not_compared_against_a_full_one(self):
        for _ in range(3):
            make_full_year(make_system(owner=make_user(), county="Cork"), kwh_per_month="100.00")
        mine = make_system(owner=make_user(), county="Cork", array="4.00")
        make_reading(mine, year=2025, month=6, kwh="100.00")

        report = stats.benchmark_system(mine, 2025)
        # One month each side, not one month against twelve.
        self.assertEqual(report["months_reported"], 1)
        self.assertEqual(report["own_annual_yield"], report["county_annual_yield"])


@override_settings(SOLEIRE_MIN_GROUP_SIZE=1, STATS_CACHE_SECONDS=0)
class SeasonalWindowTests(TestCase):
    """Seasonal shares must come from exactly one complete calendar year.

    Across "all years" the window used to cover nine springs and six autumns
    and present the ratio as seasonality.
    """

    def test_a_partial_year_publishes_nothing(self):
        system = make_system(owner=make_user(), county="Cork")
        for month in (6, 7, 8):
            make_reading(system, year=2025, month=month)
        self.assertEqual(stats.seasonal_breakdown(year=2025), [])

    def test_a_complete_year_covers_twelve_months(self):
        make_full_year(make_system(owner=make_user(), county="Cork"), year=2025)
        seasons = stats.seasonal_breakdown(year=2025)
        self.assertEqual(len(seasons), 4)
        self.assertEqual(sum(s["months"] for s in seasons), 12)
        self.assertAlmostEqual(sum(s["share_pct"] for s in seasons), 100.0, places=0)

    def test_seasons_are_in_meteorological_order(self):
        make_full_year(make_system(owner=make_user(), county="Cork"), year=2025)
        labels = [s["label"] for s in stats.seasonal_breakdown(year=2025)]
        self.assertEqual(
            [label.split()[0] for label in labels], ["Winter", "Spring", "Summer", "Autumn"]
        )

    def test_more_than_one_year_of_data_still_reports_a_single_year(self):
        system = make_system(owner=make_user(), county="Cork")
        make_full_year(system, year=2024)
        for month in (1, 2, 3):
            make_reading(system, year=2025, month=month)
        seasons = stats.seasonal_breakdown()
        self.assertTrue(all(s["year"] == 2024 for s in seasons))
        self.assertEqual(sum(s["months"] for s in seasons), 12)


class SeedGuardRegressionTests(TestCase):
    def test_clear_only_removes_seeded_accounts(self):
        """--clear matches on the demo prefix; a real contributor must survive."""
        from io import StringIO

        from django.core.management import call_command

        keeper = make_user(username="bright-heron-4712")
        with override_settings(DEBUG=True):
            call_command("seed_demo_data", "--systems", "3", "--years", "1", stdout=StringIO())
            call_command(
                "seed_demo_data", "--clear", "--systems", "2", "--years", "1", stdout=StringIO()
            )
        self.assertTrue(User.objects.filter(pk=keeper.pk).exists())


@override_settings(SOLEIRE_STATS_CACHE_SECONDS=300, SOLEIRE_MIN_GROUP_SIZE=1)
class CacheInvalidationTests(TestCase):
    """A contributor must never see figures that predate their own submission.

    The cache used to be per-process local memory with only a TTL. Under
    gunicorn each worker held a private copy, so two visitors could see
    different numbers, a fresh submission appeared to vanish for five minutes,
    and no process could invalidate another's entries.
    """

    def setUp(self):
        from django.core.cache import cache

        cache.clear()

    def test_a_new_reading_retires_the_cached_totals(self):
        cohort = make_cohort(2, county="Cork", year=2025, kwh_per_month="100.00")
        before = stats.national_summary()["total_energy_kwh"]

        make_reading(cohort[0], year=2024, month=6, kwh="500.00")

        after = stats.national_summary()["total_energy_kwh"]
        self.assertNotEqual(before, after)
        self.assertAlmostEqual(after, before + 500.0, places=2)

    def test_a_deleted_reading_retires_them_too(self):
        cohort = make_cohort(2, county="Cork", year=2025, kwh_per_month="100.00")
        extra = make_reading(cohort[0], year=2024, month=6, kwh="500.00")
        before = stats.national_summary()["total_energy_kwh"]

        extra.delete()

        self.assertAlmostEqual(
            stats.national_summary()["total_energy_kwh"], before - 500.0, places=2
        )

    def test_a_new_system_retires_them(self):
        make_cohort(2, county="Cork", year=2025)
        before = stats.national_summary()["systems"]
        make_system(owner=make_user(), county="Mayo")
        self.assertEqual(stats.national_summary()["systems"], before)  # no readings yet
        make_reading(PVSystem.objects.latest("id"), year=2025, month=1)
        self.assertEqual(stats.national_summary()["systems"], before + 1)

    def test_the_version_namespace_changes_on_a_write(self):
        first = stats.stats_version()
        make_system(owner=make_user(), county="Cork")
        self.assertNotEqual(stats.stats_version(), first)

    def test_repeated_reads_without_a_write_do_hit_the_cache(self):
        """The invalidation must not defeat the caching it protects.

        The database cache backend issues its own key lookups, so the check is
        that the readings table is not touched a second time — not that the
        query count drops to zero.
        """
        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        make_cohort(3, county="Cork", year=2025)

        with CaptureQueriesContext(connection) as cold:
            stats.national_summary()
        with CaptureQueriesContext(connection) as warm:
            stats.national_summary()

        def touches_readings(ctx):
            return sum(
                1 for q in ctx.captured_queries if "globalstats_monthlygeneration" in q["sql"]
            )

        self.assertGreater(touches_readings(cold), 0)
        self.assertEqual(touches_readings(warm), 0)
        self.assertLess(len(warm.captured_queries), len(cold.captured_queries))
