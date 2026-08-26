"""Populate the database with plausible demo data.

Replaces the old `generate_data` command, which created 1,000 accounts all
sharing the password ``password123``, swallowed every exception with a bare
``except: pass`` (so it reported success while silently writing nothing), did an
O(n²) membership check against a list, and inserted a row at a time.

What this one does differently:

* refuses to run unless explicitly unlocked, so it cannot be fired at a live
  database by accident;
* creates accounts with **unusable** passwords by default — nobody can log in
  as a demo contributor;
* models Irish irradiance properly, so the resulting statistics are worth
  looking at rather than uniform noise;
* is deterministic for a given ``--seed``, and idempotent.
"""

import os
import random
from decimal import Decimal

from django.contrib.auth.models import User
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from globalstats.constants import (
    NORTHERN_COUNTIES,
    REPUBLIC_COUNTIES,
    Orientation,
)
from globalstats.models import MonthlyGeneration, PVSystem

# Typical monthly specific yield for Ireland, kWh per kWp, indexed 1–12.
# Sums to roughly 870 kWh/kWp/year, which is where a well-sited Irish domestic
# array actually lands.
BASELINE_MONTHLY_YIELD = {
    1: 19,
    2: 34,
    3: 68,
    4: 104,
    5: 128,
    6: 127,
    7: 118,
    8: 99,
    9: 74,
    10: 44,
    11: 22,
    12: 14,
}

# How much each orientation gives up against due south.
ORIENTATION_FACTOR = {
    Orientation.SOUTH: 1.00,
    Orientation.SOUTH_EAST: 0.96,
    Orientation.SOUTH_WEST: 0.96,
    Orientation.SOUTH_EAST_WEST: 0.91,
    Orientation.EAST_WEST: 0.86,
    Orientation.FLAT: 0.87,
    Orientation.EAST: 0.79,
    Orientation.WEST: 0.80,
    Orientation.NORTH_SOUTH: 0.76,
    Orientation.NORTH_EAST: 0.63,
    Orientation.NORTH_WEST: 0.64,
    Orientation.NORTH: 0.52,
    Orientation.OTHER: 0.82,
}

# Rough south-east to north-west gradient in annual irradiance.
SUNNIER_COUNTIES = {"Wexford", "Waterford", "Cork", "Carlow", "Kilkenny", "Wicklow"}
DULLER_COUNTIES = {"Donegal", "Leitrim", "Sligo", "Mayo", "Fermanagh", "Londonderry", "Tyrone"}

# Where domestic PV is actually concentrated, so the demo dataset exercises the
# suppression rules: Dublin and Cork publish, Leitrim does not.
POPULOUS_COUNTIES = {"Dublin": 9, "Cork": 6, "Galway": 4, "Kildare": 4, "Meath": 3, "Limerick": 3}


class Command(BaseCommand):
    help = "Create demo contributors, systems and readings. Development use only."

    def add_arguments(self, parser):
        parser.add_argument(
            "--systems", type=int, default=250, help="Number of PV systems (default 250)."
        )
        parser.add_argument(
            "--years",
            type=int,
            default=3,
            help="How many years of readings, ending with the current one (default 3).",
        )
        parser.add_argument(
            "--seed",
            type=int,
            default=1234,
            help="RNG seed, so runs are reproducible (default 1234).",
        )
        parser.add_argument("--prefix", default="demo", help="Username prefix (default 'demo').")
        parser.add_argument(
            "--clear", action="store_true", help="Delete previously seeded demo accounts first."
        )
        parser.add_argument(
            "--password",
            default=None,
            help="Give every demo account this password. Omit and they get an unusable one, which is the safe default.",
        )
        parser.add_argument(
            "--include-northern-ireland",
            action="store_true",
            help="Also place systems in the six northern counties.",
        )

    def handle(self, *args, **options):
        self._guard()

        rng = random.Random(options["seed"])
        prefix = options["prefix"]
        count = options["systems"]
        years_back = options["years"]

        if count < 1:
            raise CommandError("--systems must be at least 1.")
        if years_back < 1:
            raise CommandError("--years must be at least 1.")

        if options["clear"]:
            deleted, _ = User.objects.filter(username__startswith=f"{prefix}-").delete()
            self.stdout.write(f"Cleared {deleted} previously seeded object(s).")

        counties = list(REPUBLIC_COUNTIES)
        if options["include_northern_ireland"]:
            counties += NORTHERN_COUNTIES
        weights = [POPULOUS_COUNTIES.get(county, 1) for county in counties]
        orientations = list(ORIENTATION_FACTOR)
        # Weighted so that most real roofs are south-ish, as they are in life.
        orientation_weights = [
            8 if ORIENTATION_FACTOR[o] > 0.9 else 3 if ORIENTATION_FACTOR[o] > 0.75 else 1
            for o in orientations
        ]

        this_year = timezone.localdate().year
        this_month = timezone.localdate().month
        years = list(range(this_year - years_back + 1, this_year + 1))

        created_users, created_systems, created_readings = self._build(
            rng,
            prefix,
            count,
            counties,
            weights,
            orientations,
            orientation_weights,
            years,
            this_year,
            this_month,
            options["password"],
        )

        self.stdout.write(
            self.style.SUCCESS(
                f"Seeded {created_users} contributor(s), {created_systems} system(s) "
                f"and {created_readings} reading(s) across {years[0]}–{years[-1]}."
            )
        )
        if not options["password"]:
            self.stdout.write(
                "Demo accounts have unusable passwords — none of them can sign in. "
                "Pass --password to change that for a local demo."
            )

    def _guard(self):
        """Refuse to write demo rows into anything that might be real.

        The old command had no guard at all: running it against production would
        have added a thousand accounts with a shared, publicly-known password.
        """
        from django.conf import settings

        if os.environ.get("DJANGO_ALLOW_DEMO_SEED", "").lower() in {"1", "true", "yes"}:
            return
        if settings.DEBUG:
            return
        raise CommandError(
            "Refusing to seed demo data: DEBUG is off and DJANGO_ALLOW_DEMO_SEED is "
            "not set. If this really is a throwaway environment, run it as:\n"
            "  DJANGO_ALLOW_DEMO_SEED=true python manage.py seed_demo_data"
        )

    @transaction.atomic
    def _build(
        self,
        rng,
        prefix,
        count,
        counties,
        weights,
        orientations,
        orientation_weights,
        years,
        this_year,
        this_month,
        password,
    ):
        existing = set(
            User.objects.filter(username__startswith=f"{prefix}-").values_list(
                "username", flat=True
            )
        )

        users, systems = [], []
        for index in range(count):
            username = f"{prefix}-{index:05d}"
            if username in existing:
                continue
            user = User(username=username, email="")
            if password:
                user.set_password(password)
            else:
                # Nobody can authenticate as a demo contributor.
                user.set_unusable_password()
            users.append(user)

        User.objects.bulk_create(users, batch_size=500)
        # bulk_create returns the objects with PKs on PostgreSQL, but re-reading
        # keeps this correct if anyone points it at another backend.
        created_users = {
            u.username: u for u in User.objects.filter(username__in=[u.username for u in users])
        }

        for _username, user in sorted(created_users.items()):
            county = rng.choices(counties, weights=weights, k=1)[0]
            orientation = rng.choices(orientations, weights=orientation_weights, k=1)[0]
            array = Decimal(str(round(rng.triangular(1.6, 12.0, 4.4), 2)))
            # Inverters are commonly sized a little under the array.
            inverter = Decimal(str(round(float(array) / rng.uniform(1.0, 1.35), 2)))
            battery = (
                Decimal(str(round(rng.choice([2.4, 5.0, 5.2, 9.6, 10.0, 13.5]), 2)))
                if rng.random() < 0.35
                else None
            )
            systems.append(
                PVSystem(
                    owner=user,
                    label="",
                    county=county,
                    orientation=orientation,
                    array_size_kwp=array,
                    inverter_size_kw=max(inverter, Decimal("0.50")),
                    battery_capacity_kwh=battery,
                    commissioned_year=rng.randint(2018, min(this_year, years[-1])),
                )
            )

        PVSystem.objects.bulk_create(systems, batch_size=500)
        stored_systems = list(PVSystem.objects.filter(owner__username__startswith=f"{prefix}-"))

        readings = []
        for system in stored_systems:
            # A per-system quality factor: shading, soiling, an ageing inverter.
            quality = rng.gauss(1.0, 0.09)
            quality = min(max(quality, 0.65), 1.25)
            orientation_factor = ORIENTATION_FACTOR.get(system.orientation, 0.85)
            location_factor = (
                1.06
                if system.county in SUNNIER_COUNTIES
                else 0.93
                if system.county in DULLER_COUNTIES
                else 1.0
            )
            start_year = max(years[0], system.commissioned_year or years[0])

            for year in years:
                if year < start_year:
                    continue
                # Whole-year weather: 2023 was duller than 2022, and so on.
                year_factor = rng.uniform(0.92, 1.08)
                last_month = this_month - 1 if year == this_year else 12
                for month in range(1, last_month + 1):
                    baseline = BASELINE_MONTHLY_YIELD[month]
                    monthly_noise = rng.uniform(0.78, 1.22)
                    specific = baseline * orientation_factor * location_factor * quality
                    specific *= year_factor * monthly_noise
                    energy = Decimal(str(round(specific * float(system.array_size_kwp), 2)))
                    readings.append(
                        MonthlyGeneration(
                            system=system,
                            year=year,
                            month=month,
                            energy_generated_kwh=max(energy, Decimal("0.00")),
                        )
                    )

        # ignore_conflicts keeps a re-run from tripping the unique constraint;
        # the old code caught every exception instead, which also hid real bugs.
        MonthlyGeneration.objects.bulk_create(readings, batch_size=2000, ignore_conflicts=True)

        return len(created_users), len(stored_systems), len(readings)
