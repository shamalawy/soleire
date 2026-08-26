"""Aggregation layer for the public statistics.

Two rules apply to everything in this module, and they are the reason the
queries live here instead of in the views:

1. **Anonymity.** A bucket (a county, an orientation, a size band...) is only
   published once at least ``settings.SOLEIRE_MIN_GROUP_SIZE`` distinct systems
   *belonging to distinct contributors* have fed into it. Suppressed buckets are
   returned with ``suppressed=True`` and no figures, so the UI can honestly say
   "4 counties hidden — not enough contributors yet" instead of pretending they
   do not exist.

2. **Comparability.** Raw kWh totals mostly measure how many people in a county
   happened to sign up. The headline metric is therefore *specific yield*:
   kWh generated per kWp installed. Totals are still shown, clearly labelled as
   sample totals rather than county-wide generation.

A caveat worth stating plainly: suppression thresholds protect against casual
re-identification, not against a determined attacker who diffs successive
snapshots of the site. Do not treat this as a formal privacy guarantee.
"""

import hashlib
import json
import logging
from decimal import Decimal

from django.conf import settings
from django.core.cache import cache
from django.db.models import Case, CharField, Count, Max, Min, Q, Sum, Value, When
from django.db.models.functions import Coalesce

from globalstats.aggregates import Median, PercentileCont
from globalstats.constants import (
    ALL_COUNTIES,
    COUNTY_TO_PROVINCE,
    MONTH_ABBREVIATIONS,
    MONTH_TO_SEASON,
    SYSTEM_SIZE_BANDS,
    Orientation,
    Season,
)
from globalstats.models import MonthlyGeneration

logger = logging.getLogger("soleire")

# Annotations shared by every grouped query below.
_SYSTEMS = Count("system", distinct=True)
_CONTRIBUTORS = Count("system__owner", distinct=True)
_ENERGY = Coalesce(Sum("energy_generated_kwh"), Value(Decimal("0")))
_CAPACITY = Coalesce(Sum("system__array_size_kwp"), Value(Decimal("0")))


def min_group_size():
    return getattr(settings, "SOLEIRE_MIN_GROUP_SIZE", 3)


def base_queryset():
    """Every reading that is eligible for publication.

    ``plausible()`` drops physically impossible rows; ``select_related`` avoids
    a query per row when the caller walks back to the system.
    """
    return MonthlyGeneration.objects.plausible().select_related("system")


# ---------------------------------------------------------------------------
# Caching
# ---------------------------------------------------------------------------


# Bumped whenever a reading or a system changes; every cache key is namespaced
# by it, so one write retires every stale aggregate at once. Set with no expiry
# so the namespace itself cannot quietly lapse and resurrect old entries.
STATS_VERSION_KEY = "soleire:stats:version"


def caching_enabled():
    return bool(getattr(settings, "STATS_CACHE_SECONDS", 0))


def stats_version():
    version = cache.get(STATS_VERSION_KEY)
    if version is None:
        version = 1
        cache.set(STATS_VERSION_KEY, version, None)
    return version


def invalidate_stats():
    """Retire every cached aggregate. Called from the model signals.

    Without this a contributor could file a whole year and watch the public
    figures sit unchanged until the TTL lapsed — which reads as the submission
    having been lost.
    """
    if not caching_enabled():
        return
    try:
        cache.incr(STATS_VERSION_KEY)
    except ValueError:
        # Nothing cached yet, so there is nothing stale to retire.
        cache.set(STATS_VERSION_KEY, 1, None)


def _cached(key_parts, producer):
    """Memoise an aggregate for SOLEIRE_STATS_CACHE_SECONDS.

    The TTL is a backstop; the real invalidation is `invalidate_stats`, which
    the model signals fire on every write. That keeps the county league table
    off the database on ordinary page views without ever showing a contributor
    a figure that predates their own submission.
    """
    ttl = getattr(settings, "STATS_CACHE_SECONDS", 0)
    if not ttl:
        return producer()
    digest = hashlib.sha256(
        json.dumps(key_parts, sort_keys=True, default=str).encode()
    ).hexdigest()[:24]
    key = f"soleire:stats:{stats_version()}:{digest}"
    hit = cache.get(key)
    if hit is None:
        hit = producer()
        cache.set(key, hit, ttl)
    return hit


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _to_float(value):
    if value is None:
        return None
    return round(float(value), 2)


def _specific_yield(energy, capacity):
    """kWh per kWp, energy-weighted across the bucket.

    Dividing the summed energy by the summed capacity weights each system by
    how big it is, which is what "what does a kWp deliver in Cork" asks. The
    unweighted mean of per-system yields is reported separately as the median.
    """
    if not capacity:
        return None
    return round(float(energy) / float(capacity), 1)


def _quantile(sorted_values, fraction):
    """Linearly-interpolated quantile, matching PostgreSQL's percentile_cont.

    Used where the values are per-system annual totals rather than raw rows,
    which is a Python-side computation because the input is itself an aggregate.
    """
    if not sorted_values:
        return None
    if len(sorted_values) == 1:
        return round(sorted_values[0], 0)
    position = fraction * (len(sorted_values) - 1)
    lower = int(position)
    upper = min(lower + 1, len(sorted_values) - 1)
    weight = position - lower
    value = sorted_values[lower] * (1 - weight) + sorted_values[upper] * weight
    return round(value, 0)


def _suppress(row, systems, contributors):
    """Blank out the figures in ``row`` unless the bucket clears the threshold."""
    k = min_group_size()
    if systems >= k and contributors >= k:
        row["suppressed"] = False
        return row
    return {
        **{key: None for key in row if key not in {"key", "label", "group"}},
        "key": row.get("key"),
        "label": row.get("label"),
        "group": row.get("group"),
        "suppressed": True,
        "systems": None,
        "contributors": None,
    }


def available_years():
    """Years that actually have readings, newest first."""

    def produce():
        rows = base_queryset().values_list("year", flat=True).order_by("-year").distinct()
        return list(rows)

    return _cached(["years"], produce)


def latest_year(default=None):
    years = available_years()
    if years:
        return years[0]
    from django.utils import timezone

    return default if default is not None else timezone.localdate().year


# ---------------------------------------------------------------------------
# Headline figures
# ---------------------------------------------------------------------------


MONTHS_IN_YEAR = 12


def complete_year_systems(year):
    """Systems that reported all twelve months of ``year``.

    Annual figures must only come from these. Averaging whatever months happen
    to have been filed and calling the result a yearly yield would flatter any
    contributor who only bothered to record the summer.
    """
    return (
        base_queryset()
        .filter(year=year)
        .values("system_id")
        .annotate(months=Count("id"))
        .filter(months=MONTHS_IN_YEAR)
        .values_list("system_id", flat=True)
    )


def latest_complete_year():
    """The most recent year in which at least one system reported every month."""
    for year in available_years():
        if complete_year_systems(year).exists():
            return year
    return None


def annual_summary(year=None):
    """Whole-year kWh/kWp, computed only over systems with all twelve months.

    Because every included system contributes exactly 12 rows, the summed
    per-reading capacity is twelve times the installed capacity — so the
    energy-weighted monthly figure scales up by exactly 12 with no
    extrapolation involved.
    """

    def produce():
        target = year if year is not None else latest_complete_year()
        if target is None:
            return {
                "year": None,
                "annual_yield": None,
                "systems": 0,
                "contributors": 0,
                "median_annual_yield": None,
                "p25": None,
                "p75": None,
            }

        qs = base_queryset().filter(year=target, system_id__in=complete_year_systems(target))
        agg = qs.aggregate(
            systems=_SYSTEMS,
            contributors=_CONTRIBUTORS,
            energy=_ENERGY,
            capacity=_CAPACITY,
        )
        monthly = _specific_yield(agg["energy"], agg["capacity"])
        published = agg["systems"] >= min_group_size() and agg["contributors"] >= min_group_size()

        # The spread has to come from whole-year totals per system. Taking the
        # monthly percentiles and multiplying by twelve would compare a
        # December against a June and report a "middle half" spanning most of
        # the plausible range, which says nothing about how systems differ.
        per_system = (
            qs.values("system_id", "system__array_size_kwp")
            .annotate(total=Sum("energy_generated_kwh"))
            .order_by()
        )
        annual_yields = sorted(
            float(row["total"]) / float(row["system__array_size_kwp"])
            for row in per_system
            if row["system__array_size_kwp"]
        )

        return {
            "year": target,
            "systems": agg["systems"],
            "contributors": agg["contributors"],
            "annual_yield": round(monthly * MONTHS_IN_YEAR, 0) if published and monthly else None,
            "median_annual_yield": _quantile(annual_yields, 0.5) if published else None,
            "p25": _quantile(annual_yields, 0.25) if published else None,
            "p75": _quantile(annual_yields, 0.75) if published else None,
            "suppressed": not published,
        }

    return _cached(["annual_summary", year], produce)


def annual_county_breakdown(year):
    """Annual kWh/kWp per county, complete years only, threshold applied."""

    def produce():
        if year is None:
            return []
        system_ids = list(complete_year_systems(year))
        if not system_ids:
            return []
        rows = (
            base_queryset()
            .filter(year=year, system_id__in=system_ids)
            .values("system__county")
            .annotate(
                systems=_SYSTEMS,
                contributors=_CONTRIBUTORS,
                energy=_ENERGY,
                capacity=_CAPACITY,
            )
            .order_by()
        )
        out = []
        for row in rows:
            monthly = _specific_yield(row["energy"], row["capacity"])
            record = {
                "key": row["system__county"],
                "label": row["system__county"],
                "group": None,
                "systems": row["systems"],
                "contributors": row["contributors"],
                "annual_yield": round(monthly * MONTHS_IN_YEAR, 0) if monthly else None,
            }
            out.append(_suppress(record, row["systems"], row["contributors"]))
        out.sort(key=lambda r: (r["suppressed"], -(r.get("annual_yield") or 0)))
        return out

    return _cached(["annual_county_breakdown", year], produce)


def national_summary(year=None):
    """Top-line numbers for the landing page.

    ``year=None`` means all time.
    """

    def produce():
        qs = base_queryset()
        if year is not None:
            qs = qs.filter(year=year)
        agg = qs.aggregate(
            readings=Count("id"),
            systems=_SYSTEMS,
            contributors=_CONTRIBUTORS,
            counties=Count("system__county", distinct=True),
            total_energy_kwh=_ENERGY,
            total_capacity_kwp_months=_CAPACITY,
            first_year=Min("year"),
            last_year=Max("year"),
        )
        # Installed capacity must count each system once, not once per reading.
        distinct_capacity = (
            qs.values("system_id", "system__array_size_kwp")
            .distinct()
            .aggregate(total=Coalesce(Sum("system__array_size_kwp"), Value(Decimal("0"))))
        )["total"]

        spread = qs.with_specific_yield().aggregate(
            median=Median("specific_yield"),
            p25=PercentileCont("specific_yield", percentile=0.25),
            p75=PercentileCont("specific_yield", percentile=0.75),
        )

        # The national totals need the same floor as every other bucket. With
        # two contributors on the site, publishing a national energy total
        # hands each of them the other's annual output by subtraction — the
        # county tables would all be suppressed while the headline gave it
        # away. Participation counts stay: knowing that four people have signed
        # up identifies nobody, and hiding it would make an empty site look
        # broken rather than new.
        k = min_group_size()
        published = agg["systems"] >= k and agg["contributors"] >= k

        def gated(value):
            return value if published else None

        return {
            "year": year,
            "readings": agg["readings"],
            "systems": agg["systems"],
            "contributors": agg["contributors"],
            "counties": agg["counties"],
            "total_energy_kwh": gated(_to_float(agg["total_energy_kwh"])),
            "installed_capacity_kwp": gated(_to_float(distinct_capacity)),
            "monthly_yield": gated(
                _specific_yield(agg["total_energy_kwh"], agg["total_capacity_kwp_months"])
            ),
            "median_monthly_yield": gated(_to_float(spread["median"])),
            "p25_monthly_yield": gated(_to_float(spread["p25"])),
            "p75_monthly_yield": gated(_to_float(spread["p75"])),
            "first_year": agg["first_year"],
            "last_year": agg["last_year"],
            "suppressed": not published,
            "min_group_size": k,
        }

    return _cached(["national_summary", year], produce)


# ---------------------------------------------------------------------------
# Grouped breakdowns
# ---------------------------------------------------------------------------


def _grouped(field, labels, year=None, month=None, county=None, group_of=None, sort_by="yield"):
    """Group readings by ``field`` and apply the anonymity threshold.

    ``labels`` maps a raw database value to a human label; ``group_of`` maps it
    to an optgroup-style heading (used for province headings on counties).
    """
    qs = base_queryset()
    if year is not None:
        qs = qs.filter(year=year)
    if month is not None:
        qs = qs.filter(month=month)
    if county:
        qs = qs.filter(system__county=county)

    rows = (
        qs.values(field)
        .annotate(
            systems=_SYSTEMS,
            contributors=_CONTRIBUTORS,
            readings=Count("id"),
            total_energy_kwh=_ENERGY,
            capacity_kwp_months=_CAPACITY,
        )
        .order_by()
    )

    # Medians need the per-reading yield, so run a second pass and join in
    # Python — one extra query rather than one per bucket.
    median_rows = {
        row[field]: row["median_yield"]
        for row in qs.with_specific_yield()
        .values(field)
        .annotate(median_yield=Median("specific_yield"))
        .order_by()
    }

    out = []
    for row in rows:
        raw = row[field]
        record = {
            "key": raw,
            "label": labels(raw) if callable(labels) else labels.get(raw, str(raw)),
            "group": group_of(raw) if group_of else None,
            "systems": row["systems"],
            "contributors": row["contributors"],
            "readings": row["readings"],
            "total_energy_kwh": _to_float(row["total_energy_kwh"]),
            "specific_yield": _specific_yield(row["total_energy_kwh"], row["capacity_kwp_months"]),
            "median_yield": _to_float(median_rows.get(raw)),
        }
        out.append(_suppress(record, row["systems"], row["contributors"]))

    def sort_key(r):
        if r["suppressed"]:
            return (1, 0)
        value = r.get("specific_yield") if sort_by == "yield" else r.get("total_energy_kwh")
        return (0, -(value or 0))

    out.sort(key=sort_key)
    return out


def county_breakdown(year=None, month=None, sort_by="yield"):
    """League table of counties. Suppressed counties are kept, with no figures."""

    def produce():
        rows = _grouped(
            "system__county",
            labels=lambda c: c,
            year=year,
            month=month,
            group_of=lambda c: (
                COUNTY_TO_PROVINCE.get(c).label if COUNTY_TO_PROVINCE.get(c) else None
            ),
            sort_by=sort_by,
        )
        present = {r["key"] for r in rows}
        # Counties with no data at all are listed too, so the map/table is
        # complete and the gap is visible rather than implied.
        for county in ALL_COUNTIES:
            if county not in present:
                province = COUNTY_TO_PROVINCE.get(county)
                rows.append(
                    {
                        "key": county,
                        "label": county,
                        "group": province.label if province else None,
                        "systems": None,
                        "contributors": None,
                        "readings": 0,
                        "total_energy_kwh": None,
                        "specific_yield": None,
                        "median_yield": None,
                        "suppressed": True,
                        "no_data": True,
                    }
                )
        return rows

    return _cached(["county_breakdown", year, month, sort_by], produce)


def province_breakdown(year=None, month=None):
    """Coarser grouping, which lets sparse counties still contribute a figure."""

    def produce():
        qs = base_queryset()
        if year is not None:
            qs = qs.filter(year=year)
        if month is not None:
            qs = qs.filter(month=month)

        whens = [
            When(system__county=county, then=Value(province.label))
            for county, province in COUNTY_TO_PROVINCE.items()
        ]
        annotated = qs.annotate(
            province=Case(*whens, default=Value("Unknown"), output_field=CharField())
        )

        rows = (
            annotated.values("province")
            .annotate(
                systems=_SYSTEMS,
                contributors=_CONTRIBUTORS,
                total_energy_kwh=_ENERGY,
                capacity_kwp_months=_CAPACITY,
            )
            .order_by()
        )
        out = []
        for row in rows:
            record = {
                "key": row["province"],
                "label": row["province"],
                "group": None,
                "systems": row["systems"],
                "contributors": row["contributors"],
                "total_energy_kwh": _to_float(row["total_energy_kwh"]),
                "specific_yield": _specific_yield(
                    row["total_energy_kwh"], row["capacity_kwp_months"]
                ),
            }
            out.append(_suppress(record, row["systems"], row["contributors"]))
        out.sort(key=lambda r: (r["suppressed"], -(r.get("specific_yield") or 0)))
        return out

    return _cached(["province_breakdown", year, month], produce)


def orientation_breakdown(year=None):
    """Answers "is a south-facing roof really worth it?" with community data."""

    def produce():
        labels = dict(Orientation.choices)
        return _grouped(
            "system__orientation",
            labels=lambda o: labels.get(o, o),
            year=year,
        )

    return _cached(["orientation_breakdown", year], produce)


def size_band_breakdown(year=None):
    """Specific yield by array size band — does a bigger array yield less per kWp?"""

    def produce():
        qs = base_queryset()
        if year is not None:
            qs = qs.filter(year=year)

        whens = []
        for label, low, high in SYSTEM_SIZE_BANDS:
            condition = Q()
            if low is not None:
                condition &= Q(system__array_size_kwp__gte=Decimal(str(low)))
            if high is not None:
                condition &= Q(system__array_size_kwp__lt=Decimal(str(high)))
            whens.append(When(condition, then=Value(label)))

        annotated = qs.annotate(
            band=Case(*whens, default=Value("Unknown"), output_field=CharField())
        )
        rows = (
            annotated.values("band")
            .annotate(
                systems=_SYSTEMS,
                contributors=_CONTRIBUTORS,
                total_energy_kwh=_ENERGY,
                capacity_kwp_months=_CAPACITY,
            )
            .order_by()
        )
        by_band = {r["band"]: r for r in rows}

        out = []
        for label, _low, _high in SYSTEM_SIZE_BANDS:
            row = by_band.get(label)
            if not row:
                out.append(
                    {
                        "key": label,
                        "label": label,
                        "group": None,
                        "systems": None,
                        "contributors": None,
                        "total_energy_kwh": None,
                        "specific_yield": None,
                        "suppressed": True,
                        "no_data": True,
                    }
                )
                continue
            record = {
                "key": label,
                "label": label,
                "group": None,
                "systems": row["systems"],
                "contributors": row["contributors"],
                "total_energy_kwh": _to_float(row["total_energy_kwh"]),
                "specific_yield": _specific_yield(
                    row["total_energy_kwh"], row["capacity_kwp_months"]
                ),
            }
            out.append(_suppress(record, row["systems"], row["contributors"]))
        # Keep the natural size ordering rather than sorting by yield.
        return out

    return _cached(["size_band_breakdown", year], produce)


def battery_breakdown(year=None):
    """Do systems with storage report different generation? (They should not —
    a battery shifts consumption, not production — so this doubles as a sanity
    check on data quality.)"""

    def produce():
        qs = base_queryset()
        if year is not None:
            qs = qs.filter(year=year)
        annotated = qs.annotate(
            has_battery=Case(
                When(
                    Q(system__battery_capacity_kwh__isnull=False)
                    & Q(system__battery_capacity_kwh__gt=0),
                    then=Value("With battery"),
                ),
                default=Value("No battery"),
                output_field=CharField(),
            )
        )
        rows = (
            annotated.values("has_battery")
            .annotate(
                systems=_SYSTEMS,
                contributors=_CONTRIBUTORS,
                total_energy_kwh=_ENERGY,
                capacity_kwp_months=_CAPACITY,
            )
            .order_by()
        )
        out = []
        for row in rows:
            record = {
                "key": row["has_battery"],
                "label": row["has_battery"],
                "group": None,
                "systems": row["systems"],
                "contributors": row["contributors"],
                "total_energy_kwh": _to_float(row["total_energy_kwh"]),
                "specific_yield": _specific_yield(
                    row["total_energy_kwh"], row["capacity_kwp_months"]
                ),
            }
            out.append(_suppress(record, row["systems"], row["contributors"]))
        return out

    return _cached(["battery_breakdown", year], produce)


# ---------------------------------------------------------------------------
# Time series
# ---------------------------------------------------------------------------


def monthly_series(year=None, county=None):
    """Month-by-month specific yield — the seasonality curve.

    Only possible now that month is stored as an integer; ordering by the old
    CharField gave April, August, December, February...
    """

    def produce():
        qs = base_queryset()
        if year is not None:
            qs = qs.filter(year=year)
        if county:
            qs = qs.filter(system__county=county)

        rows = (
            qs.values("year", "month")
            .annotate(
                systems=_SYSTEMS,
                contributors=_CONTRIBUTORS,
                total_energy_kwh=_ENERGY,
                capacity_kwp_months=_CAPACITY,
            )
            .order_by("year", "month")
        )
        out = []
        for row in rows:
            record = {
                "key": f"{row['year']}-{row['month']:02d}",
                "label": f"{MONTH_ABBREVIATIONS[row['month']]} {row['year']}",
                "group": None,
                "year": row["year"],
                "month": row["month"],
                "systems": row["systems"],
                "contributors": row["contributors"],
                "total_energy_kwh": _to_float(row["total_energy_kwh"]),
                "specific_yield": _specific_yield(
                    row["total_energy_kwh"], row["capacity_kwp_months"]
                ),
            }
            suppressed = _suppress(record, row["systems"], row["contributors"])
            # Keep the x-axis position even when the value is withheld.
            suppressed["year"] = row["year"]
            suppressed["month"] = row["month"]
            suppressed["label"] = record["label"]
            out.append(suppressed)
        return out

    return _cached(["monthly_series", year, county], produce)


def year_on_year(county=None):
    """One series per year, indexed by month, for overlaying on a single chart."""

    def produce():
        qs = base_queryset()
        if county:
            qs = qs.filter(system__county=county)
        rows = (
            qs.values("year", "month")
            .annotate(
                systems=_SYSTEMS,
                contributors=_CONTRIBUTORS,
                total_energy_kwh=_ENERGY,
                capacity_kwp_months=_CAPACITY,
            )
            .order_by("year", "month")
        )
        series = {}
        k = min_group_size()
        for row in rows:
            bucket = series.setdefault(row["year"], [None] * 12)
            if row["systems"] >= k and row["contributors"] >= k:
                bucket[row["month"] - 1] = _specific_yield(
                    row["total_energy_kwh"], row["capacity_kwp_months"]
                )
        return [
            {"year": year, "values": values}
            for year, values in sorted(series.items(), reverse=True)
        ]

    return _cached(["year_on_year", county], produce)


# Meteorological order, so the panel reads as a year rather than an alphabet.
SEASON_ORDER = [Season.WINTER, Season.SPRING, Season.SUMMER, Season.AUTUMN]


def seasonal_breakdown(year=None):
    """Share of one year's output delivered in each meteorological season.

    Strictly one calendar year. Running this across "all years" would sum, say,
    nine springs against six autumns and present the ratio as seasonality, when
    it is really an artefact of where the data happens to start and stop. If any
    month of the chosen year is missing or suppressed, the shares would not add
    up to a year either, so nothing is returned and the caller hides the panel.
    """

    def produce():
        target = year if year is not None else latest_complete_year()
        if target is None:
            return []

        rows = monthly_series(year=target)
        by_month = {row["month"]: row["specific_yield"] for row in rows}
        if any(by_month.get(month) is None for month in range(1, 13)):
            return []

        totals = {}
        for month in range(1, 13):
            season = MONTH_TO_SEASON[month]
            entry = totals.setdefault(season, {"yield": 0.0, "months": 0})
            entry["yield"] += by_month[month]
            entry["months"] += 1

        overall = sum(entry["yield"] for entry in totals.values()) or 1
        return [
            {
                "key": str(season.value),
                "label": season.label,
                "year": target,
                "total_yield": round(totals[season]["yield"], 1),
                "share_pct": round(100 * totals[season]["yield"] / overall, 1),
                "months": totals[season]["months"],
            }
            for season in SEASON_ORDER
            if season in totals
        ]

    return _cached(["seasonal_breakdown", year], produce)


# ---------------------------------------------------------------------------
# Personal benchmarking
# ---------------------------------------------------------------------------


def benchmark_system(system, year):
    """Compare one contributor's system against its county and the whole set.

    Returns per-month rows plus an annual summary. This is the payoff for
    contributing: "your roof did 8% better than the Cork median in June".
    """
    readings = list(MonthlyGeneration.objects.filter(system=system, year=year).order_by("month"))
    if not readings:
        return None

    county_rows = {
        (r["year"], r["month"]): r for r in _monthly_reference(year=year, county=system.county)
    }
    national_rows = {(r["year"], r["month"]): r for r in _monthly_reference(year=year, county=None)}

    size = system.array_size_kwp or Decimal("1")
    months = []
    mine_total = Decimal("0")
    for reading in readings:
        own_yield = round(float(reading.energy_generated_kwh) / float(size), 1)
        mine_total += reading.energy_generated_kwh
        county = county_rows.get((year, reading.month))
        national = national_rows.get((year, reading.month))
        months.append(
            {
                "month": reading.month,
                "label": MONTH_ABBREVIATIONS[reading.month],
                "energy_kwh": _to_float(reading.energy_generated_kwh),
                "own_yield": own_yield,
                "county_yield": county["specific_yield"] if county else None,
                "national_yield": national["specific_yield"] if national else None,
                "vs_county_pct": _delta_pct(
                    own_yield, county["specific_yield"] if county else None
                ),
                "vs_national_pct": _delta_pct(
                    own_yield, national["specific_yield"] if national else None
                ),
            }
        )

    own_annual = round(float(mine_total) / float(size), 1)
    county_annual = _sum_or_none(m["county_yield"] for m in months)
    national_annual = _sum_or_none(m["national_yield"] for m in months)

    return {
        "system": system,
        "year": year,
        "months": months,
        "total_energy_kwh": _to_float(mine_total),
        "own_annual_yield": own_annual,
        "county_annual_yield": county_annual,
        "national_annual_yield": national_annual,
        "vs_county_pct": _delta_pct(own_annual, county_annual),
        "vs_national_pct": _delta_pct(own_annual, national_annual),
        "months_reported": len(months),
    }


def _monthly_reference(year, county):
    """Peer figures for benchmarking, subject to the same suppression rule."""
    return monthly_series(year=year, county=county)


def _delta_pct(own, reference):
    if own is None or not reference:
        return None
    return round(100 * (own - reference) / reference, 1)


def _sum_or_none(values):
    collected = [v for v in values if v is not None]
    if not collected:
        return None
    return round(sum(collected), 1)


def data_quality_report():
    """Counts of readings excluded from the statistics, for the about page.

    Being open about what was thrown away is part of making the numbers
    trustworthy.
    """

    def produce():
        total = MonthlyGeneration.objects.count()
        kept = MonthlyGeneration.objects.plausible().count()
        return {
            "total_readings": total,
            "published_readings": kept,
            "excluded_readings": total - kept,
            "excluded_pct": round(100 * (total - kept) / total, 2) if total else 0.0,
        }

    return _cached(["data_quality"], produce)
