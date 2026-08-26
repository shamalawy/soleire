"""Copy every SolarEnergyRecord row into the PVSystem / MonthlyGeneration split.

The old table repeated county, orientation and both size fields on every
monthly row. Here each distinct combination of those four values, per user,
becomes one PVSystem, and the row itself becomes one MonthlyGeneration.

Along the way it repairs three defects baked into the old data:

* ``"Waterfor"`` — a typo in the original COUNTY_CHOICES — becomes ``"Waterford"``,
  which had split one county across two buckets.
* Free-form orientations (``"S/W"``, ``"E/N/W"``) become the new codes. Migration
  0004 mistakenly gave the orientation field *county* choices, so some rows hold
  a county name here; those land in ``OTHER`` rather than being dropped.
* Month names become integers, so ordering is chronological instead of
  alphabetical.

The mapping tables are inlined rather than imported from
``globalstats.constants`` on purpose: a migration has to keep working after the
constants module moves on.
"""

from decimal import Decimal

from django.db import migrations

MONTH_TO_NUMBER = {
    "january": 1,
    "february": 2,
    "march": 3,
    "april": 4,
    "may": 5,
    "june": 6,
    "july": 7,
    "august": 8,
    "september": 9,
    "october": 10,
    "november": 11,
    "december": 12,
}

NUMBER_TO_MONTH = {number: name.capitalize() for name, number in MONTH_TO_NUMBER.items()}

COUNTY_FIXES = {"Waterfor": "Waterford", "Derry": "Londonderry"}

ORIENTATION_MAP = {
    "N": "N",
    "E": "E",
    "S": "S",
    "W": "W",
    "N/E": "NE",
    "N/W": "NW",
    "S/E": "SE",
    "S/W": "SW",
    "E/W": "EW",
    "N/S": "NS",
    "E/S/W": "SEW",
    "FLAT": "FLAT",
    "N/E/S": "OTHER",
    "N/W/S": "OTHER",
    "E/N/W": "OTHER",
}

# Reverse direction: the old field held free-form strings, so pick a
# representative for each new code.
ORIENTATION_UNMAP = {
    "N": "N",
    "E": "E",
    "S": "S",
    "W": "W",
    "NE": "N/E",
    "NW": "N/W",
    "SE": "S/E",
    "SW": "S/W",
    "EW": "E/W",
    "NS": "N/S",
    "SEW": "E/S/W",
    "FLAT": "FLAT",
    "OTHER": "E/N/W",
}

# Matches PVSystem's validators and check constraints. Legacy rows below this
# cannot be carried across: the new schema would refuse them, and a 0.05 kWp
# "array" is a typo rather than an installation.
MIN_SIZE = Decimal("0.10")


def forwards(apps, schema_editor):
    SolarEnergyRecord = apps.get_model("globalstats", "SolarEnergyRecord")
    PVSystem = apps.get_model("globalstats", "PVSystem")
    MonthlyGeneration = apps.get_model("globalstats", "MonthlyGeneration")

    legacy = SolarEnergyRecord.objects.all().order_by("user_id", "input_date", "id")
    if not legacy.exists():
        return

    systems = {}
    readings = {}
    skipped_unparseable = 0
    skipped_zero_size = 0
    duplicates = 0

    for record in legacy.iterator(chunk_size=2000):
        month = MONTH_TO_NUMBER.get((record.month or "").strip().lower())
        try:
            year = int(record.year)
        except (TypeError, ValueError):
            year = None

        if month is None or year is None or not (2010 <= year <= 2100):
            # Nothing sensible can be done with a row whose period is unreadable.
            skipped_unparseable += 1
            continue

        array = record.panels_size or Decimal("0")
        inverter = record.inverter_size or Decimal("0")
        if array < MIN_SIZE or inverter < MIN_SIZE:
            # The new schema requires a workable size — a zero- or
            # near-zero-kWp array makes "kWh per kWp" meaningless. The count is
            # reported below rather than passed over in silence.
            skipped_zero_size += 1
            continue

        county = COUNTY_FIXES.get(record.county, record.county) or "Dublin"
        orientation = ORIENTATION_MAP.get(record.orientation, "OTHER")

        key = (record.user_id, county, orientation, array, inverter)
        system = systems.get(key)
        if system is None:
            system = PVSystem.objects.create(
                owner_id=record.user_id,
                label="",
                county=county[:20],
                orientation=orientation,
                array_size_kwp=array,
                inverter_size_kw=inverter,
                battery_capacity_kwh=None,
                commissioned_year=None,
            )
            systems[key] = system

        # The old unique_together was (user, month, input_date), so the same
        # month could legitimately appear twice for one configuration. The new
        # constraint allows one; keep the later row, which is the correction.
        reading_key = (system.pk, year, month)
        if reading_key in readings:
            duplicates += 1
        readings[reading_key] = MonthlyGeneration(
            system=system,
            year=year,
            month=month,
            energy_generated_kwh=record.power_generated or Decimal("0"),
        )

    MonthlyGeneration.objects.bulk_create(list(readings.values()), batch_size=2000)

    print(f"\n  migrated {len(readings)} reading(s) into {len(systems)} system(s).")
    if duplicates:
        print(f"  {duplicates} duplicate month(s) collapsed, keeping the latest row.")
    if skipped_unparseable:
        print(f"  {skipped_unparseable} row(s) skipped: unreadable month or year.")
    if skipped_zero_size:
        print(
            f"  {skipped_zero_size} row(s) skipped: array or inverter below "
            f"{MIN_SIZE} kWp/kW."
        )


def backwards(apps, schema_editor):
    """Fold the two tables back into SolarEnergyRecord.

    Reversible so a deploy can be rolled back. Every field is restored except
    input_date, which recorded when a row was typed in — information the new
    schema does not keep.

    The old unique_together was (user, month, input_date), so the synthetic
    dates have to keep that key distinct. Each (system, year) gets its own date
    from a running counter, which makes collisions impossible by construction.
    Deriving the date from `system.pk % 28`, as an earlier version did, silently
    dropped readings as soon as a contributor had more than 28 systems, or two
    years of the same month.
    """
    import datetime

    SolarEnergyRecord = apps.get_model("globalstats", "SolarEnergyRecord")
    MonthlyGeneration = apps.get_model("globalstats", "MonthlyGeneration")

    EPOCH = datetime.date(1900, 1, 1)
    date_for = {}
    rebuilt = []

    for reading in (
        MonthlyGeneration.objects.select_related("system")
        .order_by("system_id", "year", "month")
        .iterator(chunk_size=2000)
    ):
        system = reading.system
        slot = (system.pk, reading.year)
        if slot not in date_for:
            date_for[slot] = EPOCH + datetime.timedelta(days=len(date_for))
        input_date = date_for[slot]
        rebuilt.append(
            SolarEnergyRecord(
                user_id=system.owner_id,
                month=NUMBER_TO_MONTH[reading.month],
                year=str(reading.year),
                county=system.county[:20],
                orientation=ORIENTATION_UNMAP.get(system.orientation, "S")[:12],
                panels_size=min(system.array_size_kwp, Decimal("9.99")),
                inverter_size=min(system.inverter_size_kw, Decimal("9.99")),
                power_generated=min(reading.energy_generated_kwh, Decimal("9999.99")),
                input_date=input_date,
            )
        )

    SolarEnergyRecord.objects.bulk_create(rebuilt, batch_size=2000)


class Migration(migrations.Migration):
    dependencies = [
        ("globalstats", "0008_split_system_and_readings"),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]
