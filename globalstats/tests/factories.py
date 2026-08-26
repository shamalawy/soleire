"""Small helpers for building test data without a factory library."""

from decimal import Decimal

from django.contrib.auth.models import User

from globalstats.constants import Orientation
from globalstats.models import MonthlyGeneration, PVSystem

_counter = {"n": 0}


def make_user(username=None, **kwargs):
    _counter["n"] += 1
    return User.objects.create_user(
        username=username or f"tester{_counter['n']}",
        password=kwargs.pop("password", "correct-horse-battery"),
        **kwargs,
    )


def make_system(
    owner=None,
    county="Cork",
    orientation=Orientation.SOUTH,
    array="4.00",
    inverter="3.60",
    battery=None,
    **kwargs,
):
    return PVSystem.objects.create(
        owner=owner or make_user(),
        county=county,
        orientation=orientation,
        array_size_kwp=Decimal(array),
        inverter_size_kw=Decimal(inverter),
        battery_capacity_kwh=Decimal(battery) if battery is not None else None,
        **kwargs,
    )


def make_reading(system, year=2025, month=6, kwh="400.00"):
    return MonthlyGeneration.objects.create(
        system=system, year=year, month=month, energy_generated_kwh=Decimal(kwh)
    )


def make_full_year(system, year=2025, kwh_per_month="100.00"):
    """Twelve readings, which is what the annual statistics require."""
    return [make_reading(system, year=year, month=m, kwh=kwh_per_month) for m in range(1, 13)]


def make_cohort(count, county="Cork", year=2025, kwh_per_month="100.00", array="4.00"):
    """``count`` distinct contributors, each with one system and a full year.

    Distinct owners matter: the suppression rule counts contributors as well as
    systems, so a cohort built from one user would never publish.
    """
    systems = []
    for _ in range(count):
        system = make_system(owner=make_user(), county=county, array=array)
        make_full_year(system, year=year, kwh_per_month=kwh_per_month)
        systems.append(system)
    return systems
