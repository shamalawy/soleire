"""Create the PVSystem / MonthlyGeneration tables.

Deliberately does NOT drop SolarEnergyRecord — 0009 copies the rows across and
0010 removes the old table, so the three run as a safe create/copy/drop.
"""

import django.core.validators
import django.db.models.deletion
from decimal import Decimal
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("globalstats", "0007_alter_solarenergyrecord_power_generated"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="PVSystem",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                    ),
                ),
                (
                    "label",
                    models.CharField(
                        blank=True,
                        help_text="Private nickname to tell your systems apart. Never shown publicly.",
                        max_length=60,
                    ),
                ),
                (
                    "county",
                    models.CharField(
                        choices=[
                            (
                                "Republic of Ireland",
                                [
                                    ("Carlow", "Carlow"),
                                    ("Cavan", "Cavan"),
                                    ("Clare", "Clare"),
                                    ("Cork", "Cork"),
                                    ("Donegal", "Donegal"),
                                    ("Dublin", "Dublin"),
                                    ("Galway", "Galway"),
                                    ("Kerry", "Kerry"),
                                    ("Kildare", "Kildare"),
                                    ("Kilkenny", "Kilkenny"),
                                    ("Laois", "Laois"),
                                    ("Leitrim", "Leitrim"),
                                    ("Limerick", "Limerick"),
                                    ("Longford", "Longford"),
                                    ("Louth", "Louth"),
                                    ("Mayo", "Mayo"),
                                    ("Meath", "Meath"),
                                    ("Monaghan", "Monaghan"),
                                    ("Offaly", "Offaly"),
                                    ("Roscommon", "Roscommon"),
                                    ("Sligo", "Sligo"),
                                    ("Tipperary", "Tipperary"),
                                    ("Waterford", "Waterford"),
                                    ("Westmeath", "Westmeath"),
                                    ("Wexford", "Wexford"),
                                    ("Wicklow", "Wicklow"),
                                ],
                            ),
                            (
                                "Northern Ireland",
                                [
                                    ("Antrim", "Antrim"),
                                    ("Armagh", "Armagh"),
                                    ("Down", "Down"),
                                    ("Fermanagh", "Fermanagh"),
                                    ("Londonderry", "Londonderry"),
                                    ("Tyrone", "Tyrone"),
                                ],
                            ),
                        ],
                        db_index=True,
                        help_text="County the array is installed in.",
                        max_length=20,
                    ),
                ),
                (
                    "orientation",
                    models.CharField(
                        choices=[
                            ("S", "South"),
                            ("SE", "South-East"),
                            ("SW", "South-West"),
                            ("EW", "East–West (split array)"),
                            ("E", "East"),
                            ("W", "West"),
                            ("SEW", "South + East + West"),
                            ("NS", "North–South (split array)"),
                            ("FLAT", "Flat / horizontal"),
                            ("NE", "North-East"),
                            ("NW", "North-West"),
                            ("N", "North"),
                            ("OTHER", "Other / mixed"),
                        ],
                        help_text="Which way the panels face. Split arrays have a combined option.",
                        max_length=8,
                    ),
                ),
                (
                    "array_size_kwp",
                    models.DecimalField(
                        decimal_places=2,
                        help_text="Total peak DC rating of the panels, in kilowatt-peak (kWp).",
                        max_digits=6,
                        validators=[
                            django.core.validators.MinValueValidator(Decimal("0.10")),
                            django.core.validators.MaxValueValidator(Decimal("1000.00")),
                        ],
                        verbose_name="array size (kWp)",
                    ),
                ),
                (
                    "inverter_size_kw",
                    models.DecimalField(
                        decimal_places=2,
                        help_text="Continuous AC output rating of the inverter, in kilowatts (kW).",
                        max_digits=6,
                        validators=[
                            django.core.validators.MinValueValidator(Decimal("0.10")),
                            django.core.validators.MaxValueValidator(Decimal("1000.00")),
                        ],
                        verbose_name="inverter size (kW)",
                    ),
                ),
                (
                    "battery_capacity_kwh",
                    models.DecimalField(
                        blank=True,
                        decimal_places=2,
                        help_text="Usable storage capacity, if you have a battery. Leave blank if not.",
                        max_digits=6,
                        null=True,
                        validators=[
                            django.core.validators.MinValueValidator(Decimal("0.00")),
                            django.core.validators.MaxValueValidator(Decimal("1000.00")),
                        ],
                        verbose_name="battery capacity (kWh)",
                    ),
                ),
                (
                    "commissioned_year",
                    models.PositiveSmallIntegerField(
                        blank=True,
                        help_text="Year the system was switched on. Optional.",
                        null=True,
                        validators=[
                            django.core.validators.MinValueValidator(1990),
                            django.core.validators.MaxValueValidator(2100),
                        ],
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "owner",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="pv_systems",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "verbose_name": "PV system",
                "verbose_name_plural": "PV systems",
                "ordering": ["owner_id", "id"],
            },
        ),
        migrations.CreateModel(
            name="MonthlyGeneration",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                    ),
                ),
                (
                    "year",
                    models.PositiveSmallIntegerField(
                        help_text="Four-digit year, 2010 or later.",
                        validators=[
                            django.core.validators.MinValueValidator(2010),
                            django.core.validators.MaxValueValidator(2100),
                        ],
                    ),
                ),
                (
                    "month",
                    models.PositiveSmallIntegerField(
                        choices=[
                            (1, "January"),
                            (2, "February"),
                            (3, "March"),
                            (4, "April"),
                            (5, "May"),
                            (6, "June"),
                            (7, "July"),
                            (8, "August"),
                            (9, "September"),
                            (10, "October"),
                            (11, "November"),
                            (12, "December"),
                        ]
                    ),
                ),
                (
                    "energy_generated_kwh",
                    models.DecimalField(
                        decimal_places=2,
                        help_text="Total kWh your system produced that month (from your inverter app or meter).",
                        max_digits=10,
                        validators=[
                            django.core.validators.MinValueValidator(Decimal("0")),
                            django.core.validators.MaxValueValidator(Decimal("1000000.00")),
                        ],
                        verbose_name="energy generated (kWh)",
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "system",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="readings",
                        to="globalstats.pvsystem",
                    ),
                ),
            ],
            options={
                "verbose_name": "monthly generation reading",
                "ordering": ["-year", "-month"],
            },
        ),
        migrations.AddIndex(
            model_name="pvsystem",
            index=models.Index(fields=["county", "orientation"], name="pvsystem_county_orient"),
        ),
        migrations.AddConstraint(
            model_name="pvsystem",
            constraint=models.CheckConstraint(
                condition=models.Q(("array_size_kwp__gte", Decimal("0.10"))),
                name="pvsystem_array_size_positive",
            ),
        ),
        migrations.AddConstraint(
            model_name="pvsystem",
            constraint=models.CheckConstraint(
                condition=models.Q(("inverter_size_kw__gte", Decimal("0.10"))),
                name="pvsystem_inverter_size_positive",
            ),
        ),
        migrations.AddConstraint(
            model_name="pvsystem",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    ("battery_capacity_kwh__isnull", True),
                    ("battery_capacity_kwh__gte", 0),
                    _connector="OR",
                ),
                name="pvsystem_battery_non_negative",
            ),
        ),
        migrations.AddIndex(
            model_name="monthlygeneration",
            index=models.Index(fields=["year", "month"], name="reading_year_month"),
        ),
        migrations.AddIndex(
            model_name="monthlygeneration",
            index=models.Index(fields=["system", "year", "month"], name="reading_system_period"),
        ),
        migrations.AddConstraint(
            model_name="monthlygeneration",
            constraint=models.UniqueConstraint(
                fields=("system", "year", "month"), name="unique_reading_per_system_month"
            ),
        ),
        migrations.AddConstraint(
            model_name="monthlygeneration",
            constraint=models.CheckConstraint(
                condition=models.Q(("month__gte", 1), ("month__lte", 12)),
                name="reading_month_in_range",
            ),
        ),
        migrations.AddConstraint(
            model_name="monthlygeneration",
            constraint=models.CheckConstraint(
                condition=models.Q(("year__gte", 2010), ("year__lte", 2100)),
                name="reading_year_in_range",
            ),
        ),
        migrations.AddConstraint(
            model_name="monthlygeneration",
            constraint=models.CheckConstraint(
                condition=models.Q(("energy_generated_kwh__gte", 0)),
                name="reading_energy_non_negative",
            ),
        ),
    ]
