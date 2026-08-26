"""Data model for anonymously-contributed Irish solar generation figures.

Two tables rather than one. The original design stored county, orientation and
array size on every monthly row, which meant a single household could claim to
be in Cork in January and Dublin in February, and made "kWh per kWp" ambiguous.
Installation facts now live on `PVSystem`; only the reading itself lives on
`MonthlyGeneration`.

The link to `auth.User` exists solely so a contributor can edit their own rows.
Nothing user-identifying is ever exposed by the public statistics — see
`globalstats/stats.py` for the aggregation rules that enforce that.
"""

from decimal import Decimal

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import F, Q
from django.utils import timezone

from globalstats.constants import (
    COUNTY_CHOICES,
    COUNTY_TO_PROVINCE,
    FIRST_DATA_YEAR,
    MONTH_TO_SEASON,
    Month,
    Orientation,
)

# Smallest array or inverter the site will record. Anything below this is a
# typo rather than an installation. Field validators and database constraints
# both use it, so the two can never disagree.
MIN_SYSTEM_SIZE = Decimal("0.10")
MAX_SYSTEM_SIZE = Decimal("1000.00")


def current_year():
    """Callable default so the value is not frozen at import time."""
    return timezone.localdate().year


def max_data_year():
    """Readings may be filed for the current year but not the future."""
    return timezone.localdate().year


class PVSystem(models.Model):
    """One photovoltaic installation belonging to one contributor.

    A contributor may register more than one — a house plus a shed array, or a
    second install after an extension — which the previous single-table design
    could not express.
    """

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="pv_systems",
    )
    label = models.CharField(
        max_length=60,
        blank=True,
        help_text="Private nickname to tell your systems apart. Never shown publicly.",
    )
    county = models.CharField(
        max_length=20,
        choices=COUNTY_CHOICES,
        db_index=True,
        help_text="County the array is installed in.",
    )
    orientation = models.CharField(
        max_length=8,
        choices=Orientation.choices,
        help_text="Which way the panels face. Split arrays have a combined option.",
    )
    array_size_kwp = models.DecimalField(
        "array size (kWp)",
        max_digits=6,
        decimal_places=2,
        validators=[
            MinValueValidator(MIN_SYSTEM_SIZE),
            MaxValueValidator(MAX_SYSTEM_SIZE),
        ],
        help_text="Total peak DC rating of the panels, in kilowatt-peak (kWp).",
    )
    inverter_size_kw = models.DecimalField(
        "inverter size (kW)",
        max_digits=6,
        decimal_places=2,
        validators=[
            MinValueValidator(MIN_SYSTEM_SIZE),
            MaxValueValidator(MAX_SYSTEM_SIZE),
        ],
        help_text="Continuous AC output rating of the inverter, in kilowatts (kW).",
    )
    battery_capacity_kwh = models.DecimalField(
        "battery capacity (kWh)",
        max_digits=6,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[
            # Without the minimum, a negative capacity cleared form validation
            # and only failed at the check constraint — a 500 rather than a
            # field error.
            MinValueValidator(Decimal("0.00")),
            MaxValueValidator(Decimal("1000.00")),
        ],
        help_text="Usable storage capacity, if you have a battery. Leave blank if not.",
    )
    commissioned_year = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
        validators=[MinValueValidator(1990), MaxValueValidator(2100)],
        help_text="Year the system was switched on. Optional.",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "PV system"
        verbose_name_plural = "PV systems"
        ordering = ["owner_id", "id"]
        constraints = [
            # The bound matches the field validators exactly. When the
            # constraint was merely "> 0" the database could hold a 0.05 kWp
            # array that the form then refused to save, leaving the row
            # uneditable by its owner.
            models.CheckConstraint(
                condition=Q(array_size_kwp__gte=MIN_SYSTEM_SIZE),
                name="pvsystem_array_size_positive",
            ),
            models.CheckConstraint(
                condition=Q(inverter_size_kw__gte=MIN_SYSTEM_SIZE),
                name="pvsystem_inverter_size_positive",
            ),
            models.CheckConstraint(
                condition=Q(battery_capacity_kwh__isnull=True) | Q(battery_capacity_kwh__gte=0),
                name="pvsystem_battery_non_negative",
            ),
        ]
        indexes = [
            models.Index(fields=["county", "orientation"], name="pvsystem_county_orient"),
        ]

    def __str__(self):
        name = self.label or f"system #{self.pk}"
        return f"{name} — {self.array_size_kwp} kWp, {self.county}"

    @property
    def province(self):
        return COUNTY_TO_PROVINCE.get(self.county)

    @property
    def has_battery(self):
        return self.battery_capacity_kwh is not None and self.battery_capacity_kwh > 0

    @property
    def dc_ac_ratio(self):
        """Array kWp divided by inverter kW. Above ~1.3 means routine clipping."""
        if not self.inverter_size_kw:
            return None
        return self.array_size_kwp / self.inverter_size_kw


class MonthlyGenerationQuerySet(models.QuerySet):
    """Reusable filters. Kept on the queryset so they compose in the stats layer."""

    def for_year(self, year):
        return self.filter(year=year)

    def for_period(self, year, month):
        return self.filter(year=year, month=month)

    def with_specific_yield(self):
        """Annotate kWh generated per kWp installed — the only fair comparison
        between a 2 kWp and a 12 kWp system."""
        return self.annotate(
            specific_yield=models.ExpressionWrapper(
                F("energy_generated_kwh") / F("system__array_size_kwp"),
                output_field=models.DecimalField(max_digits=12, decimal_places=3),
            )
        )

    def plausible(self):
        """Drop readings that are physically impossible for Ireland.

        Almost always a unit mix-up (Wh entered as kWh) or a mistyped array
        size. Excluding them keeps one bad row from dominating a county average.
        """
        from globalstats.constants import MAX_PLAUSIBLE_MONTHLY_SPECIFIC_YIELD

        return self.filter(
            energy_generated_kwh__lte=F("system__array_size_kwp")
            * MAX_PLAUSIBLE_MONTHLY_SPECIFIC_YIELD
        )


class MonthlyGeneration(models.Model):
    """How much one system generated in one calendar month."""

    system = models.ForeignKey(
        PVSystem,
        on_delete=models.CASCADE,
        related_name="readings",
    )
    year = models.PositiveSmallIntegerField(
        validators=[MinValueValidator(FIRST_DATA_YEAR), MaxValueValidator(2100)],
        help_text=f"Four-digit year, {FIRST_DATA_YEAR} or later.",
    )
    month = models.PositiveSmallIntegerField(choices=Month.choices)
    energy_generated_kwh = models.DecimalField(
        "energy generated (kWh)",
        max_digits=10,
        decimal_places=2,
        validators=[
            MinValueValidator(Decimal("0")),
            MaxValueValidator(Decimal("1000000.00")),
        ],
        help_text="Total kWh your system produced that month (from your inverter app or meter).",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = MonthlyGenerationQuerySet.as_manager()

    class Meta:
        verbose_name = "monthly generation reading"
        ordering = ["-year", "-month"]
        constraints = [
            # One reading per system per calendar month. The old constraint was
            # (user, month, input_date), which let the same January be filed
            # twice on two different days and ignored the year entirely.
            models.UniqueConstraint(
                fields=["system", "year", "month"],
                name="unique_reading_per_system_month",
            ),
            models.CheckConstraint(
                condition=Q(month__gte=1) & Q(month__lte=12),
                name="reading_month_in_range",
            ),
            models.CheckConstraint(
                condition=Q(year__gte=FIRST_DATA_YEAR) & Q(year__lte=2100),
                name="reading_year_in_range",
            ),
            models.CheckConstraint(
                condition=Q(energy_generated_kwh__gte=0),
                name="reading_energy_non_negative",
            ),
        ]
        indexes = [
            # Covers the "national trend" and "this month by county" queries.
            models.Index(fields=["year", "month"], name="reading_year_month"),
            models.Index(fields=["system", "year", "month"], name="reading_system_period"),
        ]

    def __str__(self):
        return f"{self.get_month_display()} {self.year} — {self.energy_generated_kwh} kWh"

    @property
    def specific_yield(self):
        """kWh per kWp for this reading, or None if the array size is unusable."""
        size = self.system.array_size_kwp
        if not size:
            return None
        return self.energy_generated_kwh / size

    @property
    def season(self):
        return MONTH_TO_SEASON.get(self.month)

    @property
    def period_label(self):
        return f"{self.get_month_display()} {self.year}"
