"""Form validation, including the query-string handling on the public pages."""

from decimal import Decimal
from unittest import mock

from django.test import TestCase
from django.utils import timezone

from globalstats.constants import Orientation
from globalstats.forms import (
    AnnualGenerationForm,
    AnonymousRegisterForm,
    MonthlyGenerationForm,
    PVSystemForm,
    StatsFilterForm,
)
from globalstats.identifiers import (
    ADJECTIVES,
    NOUNS,
    UsernameGenerationError,
    build_username,
    generate_username,
)
from globalstats.tests.factories import make_reading, make_system, make_user


class SystemFormTests(TestCase):
    def base(self, **overrides):
        data = {
            "label": "Roof",
            "county": "Cork",
            "orientation": Orientation.SOUTH,
            "array_size_kwp": "4.50",
            "inverter_size_kw": "4.00",
            "battery_capacity_kwh": "",
            "commissioned_year": "",
        }
        data.update(overrides)
        return data

    def test_accepts_a_realistic_system(self):
        self.assertTrue(PVSystemForm(self.base()).is_valid())

    def test_rejects_a_future_commissioning_year(self):
        form = PVSystemForm(self.base(commissioned_year=timezone.localdate().year + 1))
        self.assertFalse(form.is_valid())
        self.assertIn("commissioned_year", form.errors)

    def test_flags_a_likely_swapped_array_and_inverter(self):
        form = PVSystemForm(self.base(array_size_kwp="12.00", inverter_size_kw="1.00"))
        self.assertFalse(form.is_valid())
        self.assertIn("inverter_size_kw", form.errors)

    def test_rejects_a_zero_array(self):
        self.assertFalse(PVSystemForm(self.base(array_size_kwp="0")).is_valid())

    def test_rejects_an_unknown_county(self):
        self.assertFalse(PVSystemForm(self.base(county="Yorkshire")).is_valid())


class MonthlyGenerationFormTests(TestCase):
    def setUp(self):
        self.system = make_system(array="4.00")

    def test_accepts_a_plausible_reading(self):
        form = MonthlyGenerationForm(
            {"year": 2024, "month": 6, "energy_generated_kwh": "500"}, system=self.system
        )
        self.assertTrue(form.is_valid(), form.errors)

    def test_rejects_a_future_year(self):
        form = MonthlyGenerationForm(
            {"year": timezone.localdate().year + 1, "month": 1, "energy_generated_kwh": "100"},
            system=self.system,
        )
        self.assertFalse(form.is_valid())
        self.assertIn("year", form.errors)

    def test_rejects_a_month_that_has_not_happened(self):
        today = timezone.localdate()
        if today.month == 12:
            self.skipTest("no future month available inside the current year")
        form = MonthlyGenerationForm(
            {"year": today.year, "month": today.month + 1, "energy_generated_kwh": "100"},
            system=self.system,
        )
        self.assertFalse(form.is_valid())
        self.assertIn("month", form.errors)

    def test_rejects_a_duplicate_month(self):
        make_reading(self.system, year=2024, month=3)
        form = MonthlyGenerationForm(
            {"year": 2024, "month": 3, "energy_generated_kwh": "100"}, system=self.system
        )
        self.assertFalse(form.is_valid())
        self.assertIn("month", form.errors)

    def test_editing_the_existing_row_is_not_a_duplicate(self):
        reading = make_reading(self.system, year=2024, month=3)
        form = MonthlyGenerationForm(
            {"year": 2024, "month": 3, "energy_generated_kwh": "250"},
            instance=reading,
            system=self.system,
        )
        self.assertTrue(form.is_valid(), form.errors)

    def test_rejects_an_impossible_yield(self):
        """4 kWp cannot produce 4,000 kWh in a month anywhere, let alone Ireland."""
        form = MonthlyGenerationForm(
            {"year": 2024, "month": 6, "energy_generated_kwh": "4000"}, system=self.system
        )
        self.assertFalse(form.is_valid())
        self.assertIn("energy_generated_kwh", form.errors)
        self.assertIn("units", str(form.errors["energy_generated_kwh"]).lower())


class AnnualGenerationFormTests(TestCase):
    def setUp(self):
        self.system = make_system(array="4.00")

    def test_accepts_a_partial_year(self):
        form = AnnualGenerationForm(
            {"year": 2024, "month_1": "50", "month_6": "500"}, system=self.system
        )
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(
            list(form.readings()), [(2024, 1, Decimal("50")), (2024, 6, Decimal("500"))]
        )

    def test_requires_at_least_one_month(self):
        form = AnnualGenerationForm({"year": 2024}, system=self.system)
        self.assertFalse(form.is_valid())

    def test_flags_only_the_implausible_month(self):
        form = AnnualGenerationForm(
            {"year": 2024, "month_1": "50", "month_6": "40000"}, system=self.system
        )
        self.assertFalse(form.is_valid())
        self.assertIn("month_6", form.errors)
        self.assertNotIn("month_1", form.errors)

    def test_month_fields_are_in_calendar_order(self):
        form = AnnualGenerationForm(system=self.system)
        labels = [field.label for field in form.month_fields()]
        self.assertEqual(labels[0], "January")
        self.assertEqual(labels[-1], "December")
        self.assertEqual(len(labels), 12)


class StatsFilterFormTests(TestCase):
    """The old view dropped ?month= straight into a query and a page heading."""

    def test_garbage_falls_back_to_the_default(self):
        form = StatsFilterForm(
            {"year": "banana", "month": "<script>", "county": "Nowhere"},
            available_years=[2024, 2025],
        )
        self.assertIsNone(form.cleaned("year"))
        self.assertIsNone(form.cleaned("month"))
        self.assertIsNone(form.cleaned("county"))

    def test_valid_values_pass_through_typed(self):
        form = StatsFilterForm(
            {"year": "2025", "month": "6", "county": "Cork"}, available_years=[2024, 2025]
        )
        self.assertEqual(form.cleaned("year"), 2025)
        self.assertEqual(form.cleaned("month"), 6)
        self.assertEqual(form.cleaned("county"), "Cork")

    def test_one_bad_field_does_not_discard_a_good_one(self):
        """A stale bookmark with a dead year should keep its county filter."""
        form = StatsFilterForm({"year": "1066", "county": "Cork"}, available_years=[2025])
        self.assertIsNone(form.cleaned("year"))
        self.assertEqual(form.cleaned("county"), "Cork")

    def test_empty_query_string_yields_defaults(self):
        form = StatsFilterForm({}, available_years=[2025])
        self.assertEqual(form.cleaned("metric", "yield"), "yield")


class AnonymousRegisterFormTests(TestCase):
    """Registration must be incapable of collecting personal information."""

    HANDLE = "bright-heron-4712"

    def valid(self, **overrides):
        data = {
            "password1": "correct-horse-battery",
            "password2": "correct-horse-battery",
            "saved_credentials": "on",
        }
        data.update(overrides)
        return data

    def test_accepts_a_password_and_nothing_else(self):
        form = AnonymousRegisterForm(self.valid(), username=self.HANDLE)
        self.assertTrue(form.is_valid(), form.errors)
        user = form.save()
        self.assertEqual(user.username, self.HANDLE)

    def test_there_is_no_email_field(self):
        self.assertNotIn("email", AnonymousRegisterForm(username=self.HANDLE).fields)

    def test_there_is_no_username_field(self):
        """Nothing the visitor types can become their identifier."""
        self.assertNotIn("username", AnonymousRegisterForm(username=self.HANDLE).fields)

    def test_a_submitted_username_is_ignored(self):
        """A crafted POST must not let anyone choose their own handle."""
        form = AnonymousRegisterForm(
            self.valid(username="my.real.name@example.com"), username=self.HANDLE
        )
        self.assertTrue(form.is_valid(), form.errors)
        user = form.save()
        self.assertEqual(user.username, self.HANDLE)

    def test_email_is_never_populated(self):
        form = AnonymousRegisterForm(self.valid(email="me@example.com"), username=self.HANDLE)
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.save().email, "")

    def test_confirmation_is_required(self):
        """Nobody should get an unrecoverable account without acknowledging it."""
        data = self.valid()
        del data["saved_credentials"]
        form = AnonymousRegisterForm(data, username=self.HANDLE)
        self.assertFalse(form.is_valid())
        self.assertIn("saved_credentials", form.errors)
        self.assertIn("cannot be recovered", str(form.errors["saved_credentials"]))

    def test_short_password_is_rejected(self):
        form = AnonymousRegisterForm(
            self.valid(password1="sun123", password2="sun123"), username=self.HANDLE
        )
        self.assertFalse(form.is_valid())

    def test_mismatched_passwords_are_rejected(self):
        form = AnonymousRegisterForm(
            self.valid(password2="something-else-entirely"), username=self.HANDLE
        )
        self.assertFalse(form.is_valid())

    def test_a_missing_handle_fails_loudly(self):
        form = AnonymousRegisterForm(self.valid(), username=None)
        self.assertFalse(form.is_valid())
        self.assertIn("expired", str(form.errors))


class HandleGenerationTests(TestCase):
    def test_shape_is_two_words_and_four_digits(self):
        for _ in range(50):
            handle = build_username()
            self.assertRegex(handle, r"^[a-z]+-[a-z]+-\d{4}$")

    def test_generated_handles_are_unused(self):
        taken = generate_username()
        make_user(username=taken)
        self.assertNotEqual(generate_username(), taken)

    def test_handles_are_not_sequential_or_repeating(self):
        """Predictable handles would let anyone enumerate contributors."""
        handles = {build_username() for _ in range(200)}
        self.assertGreater(len(handles), 190)

    def test_gives_up_rather_than_looping_forever(self):
        with mock.patch("globalstats.identifiers.build_username", return_value="taken-handle-1234"):
            make_user(username="taken-handle-1234")
            with self.assertRaises(UsernameGenerationError):
                generate_username(attempts=3)

    def test_no_word_appears_in_both_lists(self):
        self.assertEqual(set(ADJECTIVES) & set(NOUNS), set())
