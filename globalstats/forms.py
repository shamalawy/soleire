"""Forms for contributing readings and for filtering the public statistics.

Two things the previous version did not do:

* Validate the query-string parameters on the statistics pages. `?month=<script>`
  or `?year=banana` used to flow straight into a filter and, in the case of
  month, into the page heading.
* Sanity-check submitted readings. A monthly figure that implies an impossible
  yield for Ireland is almost always a unit mix-up, and one such row can skew a
  county average badly.
"""

from decimal import Decimal

from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.utils import timezone

from globalstats.constants import (
    ALL_COUNTIES,
    FIRST_DATA_YEAR,
    MAX_PLAUSIBLE_MONTHLY_SPECIFIC_YIELD,
    Month,
)
from globalstats.models import MonthlyGeneration, PVSystem


class NoColonLabelsMixin:
    """Drop Django's trailing ":" from labels.

    The templates hand-write some labels and generate others; without this the
    two styles sit side by side on the same form.
    """

    def __init__(self, *args, **kwargs):
        kwargs.setdefault("label_suffix", "")
        super().__init__(*args, **kwargs)


class AnonymousRegisterForm(NoColonLabelsMixin, UserCreationForm):
    """Registration with nothing for the contributor to fill in but a password.

    The handle is issued by the site and passed in by the view; there is no
    email field at all. Two consequences worth being explicit about:

    * Nothing a person types can carry identifying information. Left to choose
      a username, people reach for a name they already use somewhere else, and
      that single field would undo the anonymity the dataset depends on.
    * We hold nothing that could recover an account. A lost handle or password
      is unrecoverable, and the template says so in as many words.

    The handle deliberately does not come from POST data. It is rendered as a
    read-only input so browser password managers pick it up alongside the
    password, but the view supplies the authoritative value from the session —
    otherwise anyone could pick their own username by editing the request.
    """

    class Meta:
        model = User
        fields = []

    def __init__(self, *args, username=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.generated_username = username
        # UserCreationForm declares `username`; drop it so nothing the visitor
        # submits can reach the model.
        self.fields.pop("username", None)
        self.fields["password1"].label = "Choose a password"
        self.fields["password2"].label = "Type it again"
        self.fields["password1"].widget.attrs["autocomplete"] = "new-password"
        self.fields["password2"].widget.attrs["autocomplete"] = "new-password"
        self.fields["saved_credentials"] = forms.BooleanField(
            required=True,
            label="I have saved my handle and password",
            error_messages={
                "required": (
                    "Please save your handle and password first. Without them the "
                    "account cannot be recovered by anyone, including us."
                )
            },
        )

    def clean(self):
        cleaned = super().clean()
        if not self.generated_username:
            raise ValidationError("Your handle expired. Reload the page to get a new one.")
        return cleaned

    def save(self, commit=True):
        user = super().save(commit=False)
        # The authoritative handle, from the server — never from the form data.
        user.username = self.generated_username
        user.email = ""
        if commit:
            user.save()
        return user


class PVSystemForm(NoColonLabelsMixin, forms.ModelForm):
    """Register or edit one installation."""

    class Meta:
        model = PVSystem
        fields = [
            "label",
            "county",
            "orientation",
            "array_size_kwp",
            "inverter_size_kw",
            "battery_capacity_kwh",
            "commissioned_year",
        ]
        widgets = {
            "label": forms.TextInput(attrs={"placeholder": "e.g. Main roof"}),
            "array_size_kwp": forms.NumberInput(attrs={"step": "0.01", "min": "0.1"}),
            "inverter_size_kw": forms.NumberInput(attrs={"step": "0.01", "min": "0.1"}),
            "battery_capacity_kwh": forms.NumberInput(attrs={"step": "0.01", "min": "0"}),
            "commissioned_year": forms.NumberInput(attrs={"min": "1990"}),
        }

    def clean_commissioned_year(self):
        year = self.cleaned_data.get("commissioned_year")
        if year and year > timezone.localdate().year:
            raise ValidationError("That year is in the future.")
        return year

    def clean(self):
        cleaned = super().clean()
        array = cleaned.get("array_size_kwp")
        inverter = cleaned.get("inverter_size_kw")
        # Not an error — heavily over-sized arrays are a legitimate design — but
        # a ratio this extreme is usually kW and kWp entered the wrong way round.
        if array and inverter and array > inverter * 3:
            self.add_error(
                "inverter_size_kw",
                "That inverter looks far too small for the array. Check you have "
                "not swapped the two figures (panels in kWp, inverter in kW).",
            )
        return cleaned


class MonthlyGenerationForm(NoColonLabelsMixin, forms.ModelForm):
    """A single month's reading for a known system."""

    class Meta:
        model = MonthlyGeneration
        fields = ["year", "month", "energy_generated_kwh"]
        widgets = {
            "year": forms.NumberInput(attrs={"min": FIRST_DATA_YEAR}),
            "energy_generated_kwh": forms.NumberInput(attrs={"step": "0.01", "min": "0"}),
        }

    def __init__(self, *args, system=None, **kwargs):
        super().__init__(*args, **kwargs)
        # On an edit the system comes from the instance; on a create the view
        # passes it in, because the contributor picks it before the form.
        if system is not None:
            self.system = system
        elif self.instance.pk or self.instance.system_id:
            self.system = self.instance.system
        else:
            self.system = None
        this_year = timezone.localdate().year
        self.fields["year"].initial = this_year
        self.fields["year"].widget.attrs["max"] = this_year

    def clean_year(self):
        year = self.cleaned_data["year"]
        this_year = timezone.localdate().year
        if year > this_year:
            raise ValidationError("You cannot file a reading for a future year.")
        if year < FIRST_DATA_YEAR:
            raise ValidationError(f"Readings before {FIRST_DATA_YEAR} are not accepted.")
        return year

    def clean(self):
        cleaned = super().clean()
        year = cleaned.get("year")
        month = cleaned.get("month")
        energy = cleaned.get("energy_generated_kwh")

        if year and month:
            today = timezone.localdate()
            if year == today.year and month > today.month:
                self.add_error("month", "That month has not happened yet.")

            if self.system is not None:
                clash = MonthlyGeneration.objects.filter(
                    system=self.system, year=year, month=month
                ).exclude(pk=self.instance.pk)
                if clash.exists():
                    self.add_error(
                        "month",
                        "You have already filed a reading for that month. Edit the "
                        "existing one instead.",
                    )

        if energy is not None and self.system is not None:
            check_plausible(energy, self.system.array_size_kwp, self.add_error)

        return cleaned


def check_plausible(energy_kwh, array_size_kwp, add_error):
    """Reject readings that imply an impossible specific yield for Ireland."""
    if not array_size_kwp:
        return
    implied = energy_kwh / array_size_kwp
    if implied > MAX_PLAUSIBLE_MONTHLY_SPECIFIC_YIELD:
        add_error(
            "energy_generated_kwh",
            f"{energy_kwh} kWh from a {array_size_kwp} kWp array is "
            f"{implied:.0f} kWh per kWp in one month. Ireland tops out around "
            f"{MAX_PLAUSIBLE_MONTHLY_SPECIFIC_YIELD}. Check the units — inverter "
            "apps often report watt-hours.",
        )


class AnnualGenerationForm(NoColonLabelsMixin, forms.Form):
    """Twelve months in one submission.

    Most contributors have a full year to hand from their inverter app, and
    filing it a month at a time — twelve page loads — was the single biggest
    obstacle to the dataset growing.
    """

    year = forms.IntegerField(min_value=FIRST_DATA_YEAR)

    def __init__(self, *args, system=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.system = system
        self.fields["year"].initial = timezone.localdate().year
        self.fields["year"].widget.attrs["max"] = timezone.localdate().year
        for month in Month:
            self.fields[f"month_{month.value}"] = forms.DecimalField(
                required=False,
                min_value=Decimal("0"),
                max_digits=10,
                decimal_places=2,
                label=month.label,
                widget=forms.NumberInput(attrs={"step": "0.01", "min": "0", "placeholder": "kWh"}),
            )

    def clean_year(self):
        year = self.cleaned_data["year"]
        if year > timezone.localdate().year:
            raise ValidationError("You cannot file readings for a future year.")
        return year

    def clean(self):
        cleaned = super().clean()
        year = cleaned.get("year")
        today = timezone.localdate()
        supplied = 0

        for month in Month:
            field = f"month_{month.value}"
            energy = cleaned.get(field)
            if energy is None:
                continue
            supplied += 1
            if year == today.year and month.value > today.month:
                self.add_error(field, "That month has not happened yet.")
                continue
            if self.system is not None:
                check_plausible(
                    energy,
                    self.system.array_size_kwp,
                    lambda _f, msg, field=field: self.add_error(field, msg),
                )

        if not supplied:
            raise ValidationError("Enter at least one month's figure.")
        return cleaned

    def readings(self):
        """Yield ``(month, kWh)`` for every month the contributor filled in."""
        year = self.cleaned_data["year"]
        for month in Month:
            energy = self.cleaned_data.get(f"month_{month.value}")
            if energy is not None:
                yield year, month.value, energy

    def month_fields(self):
        """Bound fields in calendar order, for laying out the template grid."""
        return [self[f"month_{month.value}"] for month in Month]


class StatsFilterForm(forms.Form):
    """Validates the query string on every public statistics page.

    Everything is optional; anything invalid falls back to the default rather
    than 500-ing, because these URLs get shared and bookmarked.
    """

    year = forms.IntegerField(required=False)
    month = forms.TypedChoiceField(
        required=False, choices=[("", "Whole year"), *Month.choices], coerce=int, empty_value=None
    )
    county = forms.ChoiceField(
        required=False, choices=[("", "All of Ireland"), *((c, c) for c in ALL_COUNTIES)]
    )
    metric = forms.ChoiceField(
        required=False,
        choices=[("yield", "kWh per kWp"), ("total", "Total kWh reported")],
    )

    def __init__(self, *args, available_years=(), **kwargs):
        super().__init__(*args, **kwargs)
        years = list(available_years)
        self.fields["year"] = forms.TypedChoiceField(
            required=False,
            coerce=int,
            empty_value=None,
            choices=[("", "All years"), *((y, str(y)) for y in years)],
        )

    def cleaned(self, key, default=None):
        """Read one validated value, falling back to ``default`` when absent or bad.

        Per-field rather than all-or-nothing: a stale bookmark with a year that
        no longer has data should not also discard a perfectly good county
        filter sitting next to it.
        """
        self.is_valid()  # populates cleaned_data and errors
        if key in self.errors:
            return default
        value = getattr(self, "cleaned_data", {}).get(key)
        return default if value in (None, "") else value
