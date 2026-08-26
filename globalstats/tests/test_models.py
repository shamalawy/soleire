"""Model-level guarantees: constraints the database enforces, and derived values."""

from decimal import Decimal

from django.db import IntegrityError, transaction
from django.test import TestCase

from globalstats.constants import (
    ALL_COUNTIES,
    COUNTY_TO_PROVINCE,
    MONTH_TO_SEASON,
    Orientation,
    Province,
    Season,
)
from globalstats.models import MonthlyGeneration, PVSystem
from globalstats.tests.factories import make_reading, make_system, make_user


class ConstraintTests(TestCase):
    def test_one_reading_per_system_per_month(self):
        """The old constraint was (user, month, input_date), so the same January
        could be filed twice on two different days and the year was ignored."""
        system = make_system()
        make_reading(system, year=2025, month=1)
        with self.assertRaises(IntegrityError), transaction.atomic():
            make_reading(system, year=2025, month=1, kwh="999.00")

    def test_same_month_in_different_years_is_allowed(self):
        system = make_system()
        make_reading(system, year=2024, month=1)
        make_reading(system, year=2025, month=1)
        self.assertEqual(MonthlyGeneration.objects.count(), 2)

    def test_two_systems_may_both_report_the_same_month(self):
        owner = make_user()
        first = make_system(owner=owner, county="Cork")
        second = make_system(owner=owner, county="Cork", orientation=Orientation.EAST)
        make_reading(first, year=2025, month=3)
        make_reading(second, year=2025, month=3)
        self.assertEqual(MonthlyGeneration.objects.count(), 2)

    def test_month_outside_1_to_12_is_rejected(self):
        system = make_system()
        with self.assertRaises(IntegrityError), transaction.atomic():
            MonthlyGeneration.objects.create(
                system=system, year=2025, month=13, energy_generated_kwh=Decimal("10")
            )

    def test_negative_energy_is_rejected(self):
        system = make_system()
        with self.assertRaises(IntegrityError), transaction.atomic():
            MonthlyGeneration.objects.create(
                system=system, year=2025, month=5, energy_generated_kwh=Decimal("-1")
            )

    def test_zero_array_size_is_rejected(self):
        """Guards the division in every specific-yield calculation."""
        with self.assertRaises(IntegrityError), transaction.atomic():
            PVSystem.objects.create(
                owner=make_user(),
                county="Cork",
                orientation=Orientation.SOUTH,
                array_size_kwp=Decimal("0.00"),
                inverter_size_kw=Decimal("3.00"),
            )

    def test_year_before_the_first_data_year_is_rejected(self):
        system = make_system()
        with self.assertRaises(IntegrityError), transaction.atomic():
            MonthlyGeneration.objects.create(
                system=system, year=1999, month=5, energy_generated_kwh=Decimal("10")
            )


class FieldRangeTests(TestCase):
    def test_array_size_holds_a_realistic_domestic_system(self):
        """The old DecimalField(max_digits=3, decimal_places=2) capped at 9.99 kWp,
        which excludes a large share of real Irish installs."""
        system = make_system(array="24.75", inverter="20.00")
        system.refresh_from_db()
        self.assertEqual(system.array_size_kwp, Decimal("24.75"))

    def test_monthly_energy_holds_a_large_array(self):
        system = make_system(array="100.00", inverter="80.00")
        reading = make_reading(system, kwh="18500.00")
        reading.refresh_from_db()
        self.assertEqual(reading.energy_generated_kwh, Decimal("18500.00"))


class DerivedValueTests(TestCase):
    def test_specific_yield(self):
        system = make_system(array="5.00")
        reading = make_reading(system, kwh="600.00")
        self.assertEqual(reading.specific_yield, Decimal("120"))

    def test_dc_ac_ratio(self):
        system = make_system(array="6.00", inverter="5.00")
        self.assertAlmostEqual(float(system.dc_ac_ratio), 1.2)

    def test_has_battery(self):
        self.assertFalse(make_system().has_battery)
        self.assertTrue(make_system(battery="5.20").has_battery)

    def test_province_lookup(self):
        self.assertEqual(make_system(county="Cork").province, Province.MUNSTER)
        self.assertEqual(make_system(county="Donegal").province, Province.ULSTER)

    def test_season(self):
        system = make_system()
        self.assertEqual(make_reading(system, month=1).season, Season.WINTER)
        self.assertEqual(make_reading(system, month=7).season, Season.SUMMER)

    def test_readings_order_chronologically(self):
        """Month is an integer now. Ordering the old CharField gave
        April, August, December, February..."""
        system = make_system()
        for month in (3, 11, 1, 7):
            make_reading(system, year=2025, month=month)
        months = list(
            MonthlyGeneration.objects.filter(system=system)
            .order_by("year", "month")
            .values_list("month", flat=True)
        )
        self.assertEqual(months, [1, 3, 7, 11])


class ConstantsTests(TestCase):
    def test_every_county_has_a_province(self):
        missing = [c for c in ALL_COUNTIES if c not in COUNTY_TO_PROVINCE]
        self.assertEqual(missing, [])

    def test_no_stray_provinces(self):
        stray = [c for c in COUNTY_TO_PROVINCE if c not in ALL_COUNTIES]
        self.assertEqual(stray, [])

    def test_waterford_is_spelled_correctly(self):
        """The original COUNTY_CHOICES had 'Waterfor', which silently split the
        county in two and rejected the correct spelling."""
        self.assertIn("Waterford", ALL_COUNTIES)
        self.assertNotIn("Waterfor", ALL_COUNTIES)

    def test_thirty_two_counties(self):
        self.assertEqual(len(ALL_COUNTIES), 32)
        self.assertEqual(len(set(ALL_COUNTIES)), 32)

    def test_every_month_maps_to_a_season(self):
        self.assertEqual(sorted(MONTH_TO_SEASON), list(range(1, 13)))
