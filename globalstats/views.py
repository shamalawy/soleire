"""Views: a public statistics site plus a private area for contributors.

Public pages never touch a username. Everything they render comes out of
`globalstats.stats`, which applies the minimum-group-size rule before any
figure leaves the database.
"""

import csv
import logging

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.core.paginator import Paginator
from django.db import IntegrityError, transaction
from django.db.models import Count, Sum
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_GET, require_http_methods

from globalstats import stats
from globalstats.constants import ALL_COUNTIES, MONTH_ABBREVIATIONS, Month
from globalstats.forms import (
    AnnualGenerationForm,
    AnonymousRegisterForm,
    MonthlyGenerationForm,
    PVSystemForm,
    StatsFilterForm,
)
from globalstats.identifiers import generate_username
from globalstats.models import MonthlyGeneration, PVSystem

logger = logging.getLogger("soleire")


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _filter_form(request):
    return StatsFilterForm(request.GET or None, available_years=stats.available_years())


def _filter_context(form):
    """Resolve the validated filter values plus the data needed to re-render it."""
    year = form.cleaned("year")
    return {
        "filter_form": form,
        "selected_year": year,
        "selected_month": form.cleaned("month"),
        "selected_county": form.cleaned("county"),
        "selected_metric": form.cleaned("metric", "yield"),
        "available_years": stats.available_years(),
        "months": Month.choices,
        "counties": ALL_COUNTIES,
        "min_group_size": stats.min_group_size(),
    }


def _chart(rows, label_key="label", value_key="specific_yield", unit="kWh/kWp"):
    """Shape a breakdown into the payload the SVG chart script consumes.

    Suppressed buckets are passed through with a null value so the chart can
    draw a visible gap and the legend can explain it, rather than silently
    omitting them.
    """
    return {
        "unit": unit,
        "points": [
            {
                "label": row[label_key],
                "value": row.get(value_key),
                "suppressed": bool(row.get("suppressed")),
                "systems": row.get("systems"),
            }
            for row in rows
        ],
    }


# ---------------------------------------------------------------------------
# Public statistics
# ---------------------------------------------------------------------------


@require_GET
def home(request):
    """National dashboard: headline figures, seasonality, county leaders."""
    form = _filter_form(request)
    context = _filter_context(form)
    year = context["selected_year"]

    summary = stats.national_summary(year=year)
    annual = stats.annual_summary(year=year)
    counties = stats.county_breakdown(year=year)
    published = [c for c in counties if not c["suppressed"]]
    series = stats.monthly_series(year=year)

    context.update(
        {
            "summary": summary,
            "annual": annual,
            "top_counties": published[:8],
            "hidden_county_count": sum(
                1 for c in counties if c["suppressed"] and not c.get("no_data")
            ),
            "county_chart": _chart(published[:12]),
            "trend_chart": _chart(series),
            "seasons": stats.seasonal_breakdown(year=year),
            "has_data": summary["readings"] > 0,
        }
    )
    return render(request, "stats/home.html", context)


@require_GET
def county_stats(request):
    """Full county league table, grouped by province."""
    form = _filter_form(request)
    context = _filter_context(form)
    metric = context["selected_metric"]
    value_key = "specific_yield" if metric == "yield" else "total_energy_kwh"

    rows = stats.county_breakdown(
        year=context["selected_year"], month=context["selected_month"], sort_by=metric
    )
    published = [r for r in rows if not r["suppressed"]]

    # Whole-year figures, from systems that reported all twelve months. Only
    # meaningful when a single year is selected and no month narrows it.
    annual_rows = {}
    if context["selected_year"] and not context["selected_month"]:
        annual_rows = {
            row["key"]: row["annual_yield"]
            for row in stats.annual_county_breakdown(context["selected_year"])
            if not row["suppressed"]
        }
    for row in published:
        row["annual_yield"] = annual_rows.get(row["key"])

    context.update(
        {
            "rows": rows,
            "published": published,
            "withheld": [r for r in rows if r["suppressed"] and not r.get("no_data")],
            "no_data": [r for r in rows if r.get("no_data")],
            "provinces": stats.province_breakdown(
                year=context["selected_year"], month=context["selected_month"]
            ),
            "chart": _chart(
                published,
                value_key=value_key,
                unit="kWh/kWp" if metric == "yield" else "kWh",
            ),
            "value_key": value_key,
            "show_annual": bool(annual_rows),
            "annual_summary": stats.annual_summary(year=context["selected_year"])
            if context["selected_year"] and not context["selected_month"]
            else None,
        }
    )
    return render(request, "stats/counties.html", context)


@require_GET
def trends(request):
    """Seasonality and year-on-year comparison."""
    form = _filter_form(request)
    context = _filter_context(form)
    county = context["selected_county"]

    series = stats.monthly_series(year=context["selected_year"], county=county)
    yoy = stats.year_on_year(county=county)

    context.update(
        {
            "series": series,
            "trend_chart": _chart(series),
            "year_on_year": {
                "unit": "kWh/kWp",
                "labels": [MONTH_ABBREVIATIONS[m] for m in range(1, 13)],
                "series": [
                    {"name": str(entry["year"]), "values": entry["values"]} for entry in yoy
                ],
            },
            "seasons": stats.seasonal_breakdown(year=context["selected_year"]),
        }
    )
    return render(request, "stats/trends.html", context)


@require_GET
def system_comparison(request):
    """Does orientation, array size or storage change what a kWp delivers?"""
    form = _filter_form(request)
    context = _filter_context(form)
    year = context["selected_year"]

    orientation = stats.orientation_breakdown(year=year)
    size_bands = stats.size_band_breakdown(year=year)
    battery = stats.battery_breakdown(year=year)

    context.update(
        {
            "orientation": orientation,
            "size_bands": size_bands,
            "battery": battery,
            "orientation_chart": _chart([r for r in orientation if not r["suppressed"]]),
            "size_chart": _chart([r for r in size_bands if not r["suppressed"]]),
        }
    )
    return render(request, "stats/systems.html", context)


@require_GET
def about(request):
    """Methodology, privacy stance and an honest data-quality report."""
    return render(
        request,
        "stats/about.html",
        {
            "min_group_size": stats.min_group_size(),
            "quality": stats.data_quality_report(),
            "summary": stats.national_summary(),
            "annual": stats.annual_summary(),
        },
    )


# ---------------------------------------------------------------------------
# Open data exports (aggregates only — never row-level readings)
# ---------------------------------------------------------------------------


def _csv_response(filename, header, rows):
    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    writer = csv.writer(response)
    writer.writerow(header)
    writer.writerows(rows)
    return response


@require_GET
def export_counties_csv(request):
    """The county league table as CSV, suppression already applied."""
    form = _filter_form(request)
    year = form.cleaned("year")
    rows = stats.county_breakdown(year=year, month=form.cleaned("month"))
    suffix = year or "all-years"
    return _csv_response(
        f"soleire-counties-{suffix}.csv",
        [
            "county",
            "province",
            "systems",
            "contributors",
            "total_kwh",
            "kwh_per_kwp",
            "median_kwh_per_kwp",
        ],
        [
            [
                r["label"],
                r["group"] or "",
                r["systems"] or "",
                r["contributors"] or "",
                r["total_energy_kwh"] if r["total_energy_kwh"] is not None else "",
                r["specific_yield"] if r["specific_yield"] is not None else "",
                r["median_yield"] if r.get("median_yield") is not None else "",
            ]
            for r in rows
        ],
    )


@require_GET
def export_monthly_csv(request):
    """The national monthly series as CSV."""
    form = _filter_form(request)
    rows = stats.monthly_series(year=form.cleaned("year"), county=form.cleaned("county"))
    return _csv_response(
        "soleire-monthly.csv",
        ["year", "month", "systems", "contributors", "total_kwh", "kwh_per_kwp"],
        [
            [
                r["year"],
                r["month"],
                r["systems"] or "",
                r["contributors"] or "",
                r["total_energy_kwh"] if r["total_energy_kwh"] is not None else "",
                r["specific_yield"] if r["specific_yield"] is not None else "",
            ]
            for r in rows
        ],
    )


@require_GET
def stats_api(request, dataset):
    """JSON for anyone who wants to build on the aggregates."""
    form = _filter_form(request)
    year = form.cleaned("year")
    month = form.cleaned("month")
    county = form.cleaned("county")

    datasets = {
        "summary": lambda: stats.national_summary(year=year),
        "annual": lambda: stats.annual_summary(year=year),
        "annual-counties": lambda: stats.annual_county_breakdown(
            year or stats.latest_complete_year()
        ),
        "counties": lambda: stats.county_breakdown(year=year, month=month),
        "provinces": lambda: stats.province_breakdown(year=year, month=month),
        "monthly": lambda: stats.monthly_series(year=year, county=county),
        "year-on-year": lambda: stats.year_on_year(county=county),
        "orientation": lambda: stats.orientation_breakdown(year=year),
        "size-bands": lambda: stats.size_band_breakdown(year=year),
        "battery": lambda: stats.battery_breakdown(year=year),
        "seasons": lambda: stats.seasonal_breakdown(year=year),
    }
    if dataset not in datasets:
        raise Http404(f"Unknown dataset {dataset!r}")

    return JsonResponse(
        {
            "dataset": dataset,
            "filters": {"year": year, "month": month, "county": county},
            "min_group_size": stats.min_group_size(),
            "data": datasets[dataset](),
        },
        json_dumps_params={"indent": 2},
    )


@require_GET
def healthz(request):
    """Liveness/readiness probe used by the container HEALTHCHECK.

    Touches the database so a healthy web process with a dead database is not
    reported as ready.
    """
    from django.db import connection

    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
    except Exception:
        logger.exception("health check failed: database unreachable")
        return JsonResponse({"status": "error", "database": "unreachable"}, status=503)
    return JsonResponse({"status": "ok", "database": "ok"})


# ---------------------------------------------------------------------------
# Accounts
# ---------------------------------------------------------------------------


# Session key holding the handle offered to the visitor currently on the
# registration page.
PENDING_HANDLE = "soleire_pending_handle"


def _pending_handle(request):
    """The handle on offer, held in the session so a reload does not change it.

    Stability matters: someone who has already copied the handle into their
    password manager must not have it swapped out from under them by a refresh
    or a failed password confirmation.
    """
    handle = request.session.get(PENDING_HANDLE)
    if handle and not User.objects.filter(username=handle).exists():
        return handle
    handle = generate_username()
    request.session[PENDING_HANDLE] = handle
    return handle


@require_http_methods(["GET", "POST"])
def register(request):
    """Create an account with a site-issued handle and no personal details.

    Nothing here asks the visitor for identifying information — there is no
    username field to fill in and no email field at all.
    """
    if request.user.is_authenticated:
        return redirect("my_records")

    handle = _pending_handle(request)

    if request.method == "POST":
        form = AnonymousRegisterForm(request.POST, username=handle)
        if form.is_valid():
            try:
                with transaction.atomic():
                    user = form.save()
            except IntegrityError:
                # Two visitors were offered the same handle and one got there
                # first. Issue a fresh one rather than failing the sign-up.
                request.session.pop(PENDING_HANDLE, None)
                handle = _pending_handle(request)
                form = AnonymousRegisterForm(request.POST, username=handle)
                if form.is_valid():
                    user = form.save()
                else:
                    return render(
                        request,
                        "accounts/register.html",
                        {"form": form, "handle": handle},
                    )

            request.session.pop(PENDING_HANDLE, None)
            # `authenticate()` can return None (an inactive account, a custom
            # backend); logging in the freshly-created user directly avoids the
            # crash the old code had when it passed None to login().
            login(request, user, backend="django.contrib.auth.backends.ModelBackend")
            return redirect("welcome")
    else:
        form = AnonymousRegisterForm(username=handle)

    return render(request, "accounts/register.html", {"form": form, "handle": handle})


@login_required
@require_GET
def welcome(request):
    """Shown once, straight after sign-up: here is your handle, save it.

    A separate page rather than a flash message, because this is the only
    moment the handle can be recovered and it deserves a screen of its own.
    """
    return render(
        request,
        "accounts/welcome.html",
        {"handle": request.user.get_username()},
    )


@login_required
@require_http_methods(["GET", "POST"])
def delete_account(request):
    """Erase the account and every reading attached to it.

    A site that asks people to hand over data has to let them take it back.
    """
    if request.method == "POST":
        if request.POST.get("confirm") != request.user.get_username():
            messages.error(request, "Type your username exactly to confirm.")
            return redirect("delete_account")
        user = request.user
        logout(request)
        user.delete()
        messages.success(request, "Your account and all your readings have been deleted.")
        return redirect("home")

    counts = PVSystem.objects.filter(owner=request.user).aggregate(
        systems=Count("id", distinct=True), readings=Count("readings")
    )
    return render(request, "accounts/delete_account.html", {"counts": counts})


# ---------------------------------------------------------------------------
# Contributor area
# ---------------------------------------------------------------------------


def _owned_system(request, system_id):
    """Fetch a system or 404 — never 403, which would confirm it exists."""
    return get_object_or_404(PVSystem, pk=system_id, owner=request.user)


def _owned_reading(request, reading_id):
    return get_object_or_404(
        MonthlyGeneration.objects.select_related("system"),
        pk=reading_id,
        system__owner=request.user,
    )


@login_required
@require_GET
def my_records(request):
    """Overview of a contributor's systems and how complete each one is.

    Deliberately does not list every reading — that lives on the per-system
    page, which paginates. A contributor with ten years of monthly data would
    otherwise render 120 rows per system here.
    """
    systems = (
        PVSystem.objects.filter(owner=request.user)
        .annotate(
            reading_count=Count("readings"),
            total_kwh=Sum("readings__energy_generated_kwh"),
        )
        .order_by("id")
    )

    this_year = timezone.localdate().year
    recent = {
        (r.system_id, r.month): r
        for r in MonthlyGeneration.objects.filter(system__owner=request.user, year=this_year)
    }

    cards = []
    for system in systems:
        filed = {month for (system_id, month) in recent if system_id == system.pk}
        cards.append(
            {
                "system": system,
                "reading_count": system.reading_count,
                "total_kwh": system.total_kwh,
                "missing_this_year": _missing_months_from(filed, this_year),
            }
        )

    return render(
        request,
        "contribute/my_records.html",
        {"cards": cards, "this_year": this_year},
    )


@login_required
@require_GET
def system_detail(request, system_id):
    """One system's readings, paginated and filterable by year."""
    system = _owned_system(request, system_id)

    readings = MonthlyGeneration.objects.filter(system=system).order_by("-year", "-month")
    years = sorted(set(readings.values_list("year", flat=True)), reverse=True)

    selected_year = None
    raw_year = request.GET.get("year")
    if raw_year and raw_year.isdigit() and int(raw_year) in years:
        selected_year = int(raw_year)
        readings = readings.filter(year=selected_year)

    paginator = Paginator(readings, settings.SOLEIRE_PAGE_SIZE)
    page = paginator.get_page(request.GET.get("page"))

    rows = [
        {
            "reading": reading,
            "specific_yield": round(reading.specific_yield, 1)
            if reading.specific_yield is not None
            else None,
        }
        for reading in page
    ]

    annual = (
        MonthlyGeneration.objects.filter(system=system)
        .values("year")
        .annotate(total_kwh=Sum("energy_generated_kwh"), months=Count("id"))
        .order_by("-year")
    )

    return render(
        request,
        "contribute/system_detail.html",
        {
            "system": system,
            "page": page,
            "rows": rows,
            "years": years,
            "selected_year": selected_year,
            "annual": [
                {
                    "year": row["year"],
                    "total_kwh": row["total_kwh"],
                    "months": row["months"],
                    "specific_yield": round(
                        float(row["total_kwh"]) / float(system.array_size_kwp), 1
                    )
                    if system.array_size_kwp
                    else None,
                }
                for row in annual
            ],
        },
    )


def _missing_months_from(filed, year):
    """Months of ``year`` that have already happened but have no reading."""
    today = timezone.localdate()
    last_month = today.month if year == today.year else 12
    return [
        {"value": m, "label": MONTH_ABBREVIATIONS[m]}
        for m in range(1, last_month + 1)
        if m not in filed
    ]


@login_required
@require_http_methods(["GET", "POST"])
def system_create(request):
    if request.method == "POST":
        form = PVSystemForm(request.POST)
        if form.is_valid():
            system = form.save(commit=False)
            system.owner = request.user
            system.save()
            messages.success(request, "System registered. Now add some readings.")
            return redirect("reading_bulk", system_id=system.pk)
    else:
        form = PVSystemForm()
    return render(request, "contribute/system_form.html", {"form": form, "is_new": True})


@login_required
@require_http_methods(["GET", "POST"])
def system_edit(request, system_id):
    system = _owned_system(request, system_id)
    if request.method == "POST":
        form = PVSystemForm(request.POST, instance=system)
        if form.is_valid():
            form.save()
            messages.success(request, "System updated.")
            return redirect("my_records")
    else:
        form = PVSystemForm(instance=system)
    return render(
        request,
        "contribute/system_form.html",
        {"form": form, "system": system, "is_new": False},
    )


@login_required
@require_http_methods(["GET", "POST"])
def system_delete(request, system_id):
    system = _owned_system(request, system_id)
    if request.method == "POST":
        system.delete()
        messages.success(request, "System and its readings deleted.")
        return redirect("my_records")
    return render(
        request,
        "contribute/confirm_delete.html",
        {
            "object_label": str(system),
            "detail": f"{system.readings.count()} reading(s) will be deleted with it.",
            "cancel_url": reverse("my_records"),
        },
    )


@login_required
@require_http_methods(["GET", "POST"])
def reading_bulk(request, system_id):
    """Enter (or correct) a whole year of readings in one go."""
    system = _owned_system(request, system_id)

    if request.method == "POST":
        form = AnnualGenerationForm(request.POST, system=system)
        if form.is_valid():
            created, updated = _save_annual(system, form)
            messages.success(
                request,
                f"Saved {created} new and {updated} updated reading(s) for "
                f"{form.cleaned_data['year']}.",
            )
            return redirect("system_detail", system_id=system.pk)
    else:
        year = _requested_year(request)
        existing = {
            f"month_{r.month}": r.energy_generated_kwh
            for r in MonthlyGeneration.objects.filter(system=system, year=year)
        }
        form = AnnualGenerationForm(initial={"year": year, **existing}, system=system)

    return render(
        request,
        "contribute/reading_bulk.html",
        {"form": form, "system": system, "available_years": stats.available_years()},
    )


def _requested_year(request):
    """Read ?year= for the bulk form, ignoring anything that is not a sane year."""
    raw = request.GET.get("year")
    today = timezone.localdate()
    if raw and raw.isdigit():
        year = int(raw)
        if 2000 <= year <= today.year:
            return year
    return today.year


@transaction.atomic
def _save_annual(system, form):
    """Upsert each supplied month. Atomic so a partial year is never left behind."""
    created = updated = 0
    for year, month, energy in form.readings():
        _obj, was_created = MonthlyGeneration.objects.update_or_create(
            system=system,
            year=year,
            month=month,
            defaults={"energy_generated_kwh": energy},
        )
        if was_created:
            created += 1
        else:
            updated += 1
    return created, updated


@login_required
@require_http_methods(["GET", "POST"])
def reading_create(request, system_id):
    system = _owned_system(request, system_id)
    if request.method == "POST":
        form = MonthlyGenerationForm(request.POST, system=system)
        if form.is_valid():
            reading = form.save(commit=False)
            reading.system = system
            try:
                # The savepoint matters: PostgreSQL aborts a transaction on any
                # error, so without it this would only survive because the
                # project happens to run in autocommit. Switching on
                # ATOMIC_REQUESTS later would otherwise break the recovery.
                with transaction.atomic():
                    reading.save()
            except IntegrityError:
                # Lost a race with a concurrent submission of the same month.
                form.add_error(None, "That month was just filed. Reload and edit it instead.")
            else:
                messages.success(request, f"Recorded {reading.period_label}.")
                return redirect("system_detail", system_id=system.pk)
    else:
        form = MonthlyGenerationForm(system=system, initial=_prefill_month(request))
    return render(
        request,
        "contribute/reading_form.html",
        {"form": form, "system": system, "is_new": True},
    )


def _prefill_month(request):
    """Let "add March" links from the dashboard prefill the form."""
    initial = {}
    raw_month = request.GET.get("month")
    raw_year = request.GET.get("year")
    if raw_month and raw_month.isdigit() and 1 <= int(raw_month) <= 12:
        initial["month"] = int(raw_month)
    if raw_year and raw_year.isdigit():
        initial["year"] = int(raw_year)
    return initial


@login_required
@require_http_methods(["GET", "POST"])
def reading_edit(request, reading_id):
    reading = _owned_reading(request, reading_id)
    if request.method == "POST":
        form = MonthlyGenerationForm(request.POST, instance=reading, system=reading.system)
        if form.is_valid():
            form.save()
            messages.success(request, "Reading updated.")
            return redirect("system_detail", system_id=reading.system_id)
    else:
        form = MonthlyGenerationForm(instance=reading, system=reading.system)
    return render(
        request,
        "contribute/reading_form.html",
        {"form": form, "system": reading.system, "reading": reading, "is_new": False},
    )


@login_required
@require_http_methods(["GET", "POST"])
def reading_delete(request, reading_id):
    reading = _owned_reading(request, reading_id)
    if request.method == "POST":
        system_id = reading.system_id
        reading.delete()
        messages.success(request, "Reading deleted.")
        return redirect("system_detail", system_id=system_id)
    return render(
        request,
        "contribute/confirm_delete.html",
        {
            "object_label": f"{reading.period_label} — {reading.energy_generated_kwh} kWh",
            "detail": f"From {reading.system}.",
            "cancel_url": reverse("my_records"),
        },
    )


@login_required
@require_GET
def benchmark(request, system_id):
    """How one system compares with its county and the whole dataset."""
    system = _owned_system(request, system_id)
    years = sorted(
        MonthlyGeneration.objects.filter(system=system).values_list("year", flat=True).distinct(),
        reverse=True,
    )
    if not years:
        messages.info(request, "Add at least one reading before benchmarking.")
        return redirect("reading_bulk", system_id=system.pk)

    requested = _requested_year(request)
    year = requested if requested in years else years[0]
    report = stats.benchmark_system(system, year)

    chart = None
    if report:
        chart = {
            "unit": "kWh/kWp",
            "labels": [m["label"] for m in report["months"]],
            "series": [
                {"name": "Your system", "values": [m["own_yield"] for m in report["months"]]},
                {
                    "name": f"{system.county} median",
                    "values": [m["county_yield"] for m in report["months"]],
                },
                {
                    "name": "All Ireland",
                    "values": [m["national_yield"] for m in report["months"]],
                },
            ],
        }

    return render(
        request,
        "contribute/benchmark.html",
        {
            "system": system,
            "report": report,
            "chart": chart,
            "years": years,
            "selected_year": year,
            "min_group_size": stats.min_group_size(),
        },
    )


@login_required
@require_GET
def export_my_data(request):
    """Everything this account has contributed, as CSV. Data portability."""
    readings = (
        MonthlyGeneration.objects.filter(system__owner=request.user)
        .select_related("system")
        .order_by("system_id", "year", "month")
    )
    return _csv_response(
        "my-soleire-data.csv",
        [
            "system_label",
            "county",
            "orientation",
            "array_size_kwp",
            "inverter_size_kw",
            "battery_capacity_kwh",
            "year",
            "month",
            "energy_generated_kwh",
            "kwh_per_kwp",
        ],
        [
            [
                r.system.label,
                r.system.county,
                r.system.get_orientation_display(),
                r.system.array_size_kwp,
                r.system.inverter_size_kw,
                r.system.battery_capacity_kwh if r.system.battery_capacity_kwh is not None else "",
                r.year,
                r.get_month_display(),
                r.energy_generated_kwh,
                round(r.specific_yield, 2) if r.specific_yield is not None else "",
            ]
            for r in readings
        ],
    )
