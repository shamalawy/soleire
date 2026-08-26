"""The aggregation layer: anonymity thresholds first, then the arithmetic."""

from django.test import TestCase, override_settings

from globalstats import stats
from globalstats.constants import Orientation
from globalstats.models import MonthlyGeneration
from globalstats.tests.factories import (
    make_cohort,
    make_full_year,
    make_reading,
    make_system,
    make_user,
)


@override_settings(SOLEIRE_MIN_GROUP_SIZE=3, STATS_CACHE_SECONDS=0)
class SuppressionTests(TestCase):
    """The rule the whole privacy claim rests on."""

    def test_county_below_the_threshold_is_withheld(self):
        make_cohort(2, county="Leitrim")
        row = self._county("Leitrim")
        self.assertTrue(row["suppressed"])
        self.assertIsNone(row["specific_yield"])
        self.assertIsNone(row["total_energy_kwh"])
        self.assertIsNone(row["systems"])

    def test_county_at_the_threshold_is_published(self):
        make_cohort(3, county="Leitrim")
        row = self._county("Leitrim")
        self.assertFalse(row["suppressed"])
        self.assertIsNotNone(row["specific_yield"])
        self.assertEqual(row["systems"], 3)

    def test_one_person_with_many_systems_does_not_unlock_a_county(self):
        """Systems and contributors are counted separately on purpose — three
        arrays on one roof are still one household."""
        owner = make_user()
        for orientation in (Orientation.SOUTH, Orientation.EAST, Orientation.WEST):
            system = make_system(owner=owner, county="Leitrim", orientation=orientation)
            make_full_year(system)
        row = self._county("Leitrim")
        self.assertTrue(row["suppressed"])

    def test_counties_with_no_data_are_listed_but_carry_no_figures(self):
        make_cohort(3, county="Cork")
        rows = {r["key"]: r for r in stats.county_breakdown()}
        self.assertIn("Leitrim", rows)
        self.assertTrue(rows["Leitrim"]["no_data"])
        self.assertIsNone(rows["Leitrim"]["specific_yield"])

    def test_threshold_is_configurable(self):
        make_cohort(3, county="Sligo")
        with override_settings(SOLEIRE_MIN_GROUP_SIZE=5):
            self.assertTrue(self._county("Sligo")["suppressed"])
        self.assertFalse(self._county("Sligo")["suppressed"])

    def test_monthly_series_keeps_the_x_axis_but_drops_the_value(self):
        make_cohort(2, county="Mayo", year=2025)
        rows = stats.monthly_series(year=2025)
        self.assertEqual(len(rows), 12)
        self.assertTrue(all(r["suppressed"] for r in rows))
        self.assertTrue(all(r["specific_yield"] is None for r in rows))
        self.assertTrue(all(r["month"] is not None for r in rows))

    def test_orientation_and_size_bands_are_suppressed_too(self):
        make_cohort(2, county="Cork")
        self.assertTrue(all(r["suppressed"] for r in stats.orientation_breakdown()))
        self.assertTrue(all(r["suppressed"] for r in stats.size_band_breakdown()))

    def _county(self, name):
        return next(r for r in stats.county_breakdown() if r["key"] == name)


@override_settings(SOLEIRE_MIN_GROUP_SIZE=1, STATS_CACHE_SECONDS=0)
class ArithmeticTests(TestCase):
    def test_specific_yield_is_energy_over_capacity(self):
        make_cohort(3, county="Cork", array="4.00", kwh_per_month="400.00")
        row = next(r for r in stats.county_breakdown() if r["key"] == "Cork")
        self.assertEqual(row["specific_yield"], 100.0)  # 400 kWh / 4 kWp

    def test_bigger_systems_carry_more_weight_in_the_average(self):
        """Energy-weighted, not a plain mean of per-system yields: a 10 kWp array
        should move a county figure more than a 1 kWp one."""
        make_system(owner=make_user(), county="Clare", array="10.00")
        big = make_system(owner=make_user(), county="Clare", array="10.00")
        small = make_system(owner=make_user(), county="Clare", array="1.00")
        make_reading(big, year=2025, month=6, kwh="1000.00")  # 100 kWh/kWp
        make_reading(small, year=2025, month=6, kwh="20.00")  # 20 kWh/kWp
        row = next(r for r in stats.county_breakdown(year=2025, month=6) if r["key"] == "Clare")
        # (1000 + 20) / (10 + 1) = 92.7, not the unweighted mean of 60.
        self.assertAlmostEqual(row["specific_yield"], 92.7, places=1)

    def test_annual_yield_uses_complete_years_only(self):
        """A system with only sunny months must not inflate the annual figure."""
        for _ in range(3):
            make_full_year(make_system(owner=make_user(), county="Cork"), kwh_per_month="100.00")
        partial = make_system(owner=make_user(), county="Cork", array="4.00")
        for month in (6, 7):
            make_reading(partial, year=2025, month=month, kwh="800.00")  # 200 kWh/kWp

        summary = stats.annual_summary(year=2025)
        self.assertEqual(summary["systems"], 3)
        # 100 kWh/month over a 4 kWp array = 25 kWh/kWp/month = 300 a year.
        self.assertEqual(summary["annual_yield"], 300.0)

    def test_annual_spread_comes_from_per_system_totals(self):
        """Multiplying the monthly quartiles by twelve would compare a December
        against a June and report a nonsense range."""
        for kwh in ("80.00", "100.00", "120.00"):
            make_full_year(make_system(owner=make_user(), county="Cork"), kwh_per_month=kwh)
        summary = stats.annual_summary(year=2025)
        self.assertEqual(summary["median_annual_yield"], 300.0)  # 100*12/4
        self.assertEqual(summary["p25"], 270.0)  # midpoint 80..100
        self.assertEqual(summary["p75"], 330.0)

    def test_annual_summary_is_none_when_no_year_is_complete(self):
        system = make_system(owner=make_user(), county="Cork")
        make_reading(system, year=2025, month=4)
        self.assertIsNone(stats.annual_summary()["annual_yield"])

    def test_quantile_interpolates_like_postgres(self):
        self.assertEqual(stats._quantile([10, 20, 30, 40], 0.5), 25)
        self.assertEqual(stats._quantile([10], 0.5), 10)
        self.assertIsNone(stats._quantile([], 0.5))

    def test_median_differs_from_the_mean_when_one_system_is_odd(self):
        for _ in range(4):
            make_full_year(make_system(owner=make_user(), county="Kerry"), kwh_per_month="100.00")
        outlier = make_system(owner=make_user(), county="Kerry", array="4.00")
        make_full_year(outlier, kwh_per_month="700.00")  # 175 kWh/kWp/month, still plausible
        row = next(r for r in stats.county_breakdown() if r["key"] == "Kerry")
        self.assertGreater(row["specific_yield"], row["median_yield"])


@override_settings(SOLEIRE_MIN_GROUP_SIZE=1, STATS_CACHE_SECONDS=0)
class PlausibilityTests(TestCase):
    def test_impossible_readings_are_excluded_from_aggregates(self):
        """A watt-hour figure entered as kilowatt-hours would otherwise dominate
        its county's average."""
        good = make_cohort(3, county="Cork", kwh_per_month="100.00")
        rogue = make_system(owner=make_user(), county="Cork", array="4.00")
        make_reading(rogue, year=2025, month=6, kwh="400000.00")

        row = next(r for r in stats.county_breakdown(year=2025, month=6) if r["key"] == "Cork")
        self.assertEqual(row["systems"], len(good))
        self.assertEqual(row["specific_yield"], 25.0)

    def test_excluded_readings_are_reported_openly(self):
        make_cohort(1, county="Cork")
        rogue = make_system(owner=make_user(), county="Cork", array="4.00")
        make_reading(rogue, year=2025, month=6, kwh="400000.00")
        report = stats.data_quality_report()
        self.assertEqual(report["excluded_readings"], 1)
        self.assertEqual(report["total_readings"], MonthlyGeneration.objects.count())

    def test_a_reading_at_the_plausibility_limit_is_kept(self):
        system = make_system(owner=make_user(), county="Cork", array="4.00")
        make_reading(system, year=2025, month=6, kwh="1000.00")  # exactly 250 kWh/kWp
        self.assertEqual(stats.data_quality_report()["excluded_readings"], 0)


@override_settings(SOLEIRE_MIN_GROUP_SIZE=3, STATS_CACHE_SECONDS=0)
class BenchmarkTests(TestCase):
    def test_compares_against_peers(self):
        make_cohort(3, county="Cork", kwh_per_month="100.00", array="4.00")
        mine = make_system(owner=make_user(), county="Cork", array="4.00")
        make_full_year(mine, kwh_per_month="120.00")

        report = stats.benchmark_system(mine, 2025)
        self.assertEqual(report["months_reported"], 12)
        self.assertEqual(report["own_annual_yield"], 360.0)
        # 30 vs a county of ~26.2 once my own rows are included in the peer set.
        self.assertGreater(report["vs_county_pct"], 0)

    def test_peer_figures_are_withheld_when_the_county_is_sparse(self):
        mine = make_system(owner=make_user(), county="Leitrim", array="4.00")
        make_full_year(mine)
        report = stats.benchmark_system(mine, 2025)
        self.assertIsNotNone(report["own_annual_yield"])
        self.assertIsNone(report["county_annual_yield"])
        self.assertIsNone(report["vs_county_pct"])

    def test_returns_none_without_readings(self):
        self.assertIsNone(stats.benchmark_system(make_system(), 2025))

    def test_annual_comparison_only_spans_reported_months(self):
        make_cohort(3, county="Cork", kwh_per_month="100.00", array="4.00")
        mine = make_system(owner=make_user(), county="Cork", array="4.00")
        make_reading(mine, year=2025, month=6, kwh="100.00")
        report = stats.benchmark_system(mine, 2025)
        self.assertEqual(report["months_reported"], 1)
        self.assertEqual(report["own_annual_yield"], 25.0)
        self.assertEqual(report["county_annual_yield"], 25.0)


@override_settings(SOLEIRE_MIN_GROUP_SIZE=1, STATS_CACHE_SECONDS=0)
class SeriesTests(TestCase):
    def test_monthly_series_is_in_calendar_order(self):
        make_cohort(2, county="Cork", year=2025)
        months = [r["month"] for r in stats.monthly_series(year=2025)]
        self.assertEqual(months, list(range(1, 13)))

    def test_year_on_year_returns_one_row_per_year_newest_first(self):
        system = make_system(owner=make_user(), county="Cork")
        make_full_year(system, year=2024)
        make_full_year(system, year=2025)
        rows = stats.year_on_year()
        self.assertEqual([r["year"] for r in rows], [2025, 2024])
        self.assertEqual(len(rows[0]["values"]), 12)

    def test_seasonal_shares_sum_to_one_hundred(self):
        make_cohort(2, county="Cork", year=2025)
        total = sum(s["share_pct"] for s in stats.seasonal_breakdown(year=2025))
        self.assertAlmostEqual(total, 100.0, places=0)

    def test_available_years_is_newest_first(self):
        system = make_system(owner=make_user())
        make_reading(system, year=2023, month=1)
        make_reading(system, year=2025, month=1)
        self.assertEqual(stats.available_years(), [2025, 2023])
