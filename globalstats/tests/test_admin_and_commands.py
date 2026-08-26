"""The admin's privacy posture, plus the management commands."""

from io import StringIO

from django.contrib.auth.models import Permission, User
from django.contrib.contenttypes.models import ContentType
from django.core.management import CommandError, call_command
from django.test import TestCase, override_settings
from django.urls import reverse

from globalstats.admin import MonthlyGenerationAdmin, PVSystemAdmin
from globalstats.models import MonthlyGeneration, PVSystem
from globalstats.tests.factories import make_reading, make_system, make_user

PASSWORD = "correct-horse-battery"


class AdminPrivacyTests(TestCase):
    """The admin is the only place identity and readings meet, so it stays lean."""

    @classmethod
    def setUpTestData(cls):
        cls.contributor = make_user(username="identifiable-person")
        cls.system = make_system(owner=cls.contributor, county="Cork")
        make_reading(cls.system, year=2024, month=5)
        cls.staff = User.objects.create_user(
            username="staffer", password=PASSWORD, is_staff=True, is_superuser=False
        )
        # Give the staff account genuine access to the model, so the test proves
        # the queryset filter hides other people's rows rather than the
        # permission check simply denying the page.
        cls.staff.user_permissions.add(
            *Permission.objects.filter(
                content_type=ContentType.objects.get_for_model(PVSystem),
                codename__in=["view_pvsystem", "change_pvsystem"],
            )
        )
        cls.root = User.objects.create_superuser(username="root", password=PASSWORD)

    def test_username_is_not_a_list_column(self):
        self.assertNotIn("owner", PVSystemAdmin.list_display)
        self.assertNotIn("user", PVSystemAdmin.list_display)
        self.assertNotIn("owner", MonthlyGenerationAdmin.list_display)

    def test_username_is_not_searchable(self):
        """The original admin allowed search_fields = ('user__username', ...)."""
        for admin_class in (PVSystemAdmin, MonthlyGenerationAdmin):
            with self.subTest(admin=admin_class.__name__):
                self.assertFalse(
                    any("user" in field or "owner" in field for field in admin_class.search_fields)
                )

    def test_non_superuser_staff_only_see_their_own(self):
        self.client.login(username="staffer", password=PASSWORD)
        response = self.client.get(reverse("admin:globalstats_pvsystem_changelist"))
        self.assertEqual(response.status_code, 200)
        # The contributor's system exists, but this staff account does not own
        # it and the changelist neither lists it nor names its owner.
        self.assertNotContains(response, "identifiable-person")
        self.assertNotContains(response, f"PV-{self.system.pk:06d}")

    def test_only_a_superuser_sees_the_owner_field(self):
        request = type("Req", (), {"user": self.staff})()
        self.assertNotIn("owner", PVSystemAdmin(PVSystem, None).get_fields(request))
        request.user = self.root
        self.assertIn("owner", PVSystemAdmin(PVSystem, None).get_fields(request))

    def test_systems_are_shown_by_opaque_reference(self):
        self.assertEqual(
            PVSystemAdmin(PVSystem, None).anonymous_ref(self.system),
            f"PV-{self.system.pk:06d}",
        )


class WaitForDbTests(TestCase):
    def test_succeeds_against_a_live_database(self):
        out = StringIO()
        call_command("wait_for_db", "--timeout", "5", stdout=out)
        self.assertIn("Database ready", out.getvalue())


class EnsureSchemaTests(TestCase):
    def test_no_op_when_no_schema_is_configured(self):
        out = StringIO()
        with override_settings(POSTGRES_SCHEMA=None):
            call_command("ensure_schema", stdout=out)
        self.assertIn("default schema", out.getvalue())

    def test_refuses_an_unsafe_schema_name(self):
        with override_settings(POSTGRES_SCHEMA='pub"; DROP TABLE x; --'):
            with self.assertRaises(CommandError):
                call_command("ensure_schema", stdout=StringIO())


@override_settings(DEBUG=True)
class SeedDemoDataTests(TestCase):
    def test_creates_systems_and_readings(self):
        call_command("seed_demo_data", "--systems", "6", "--years", "1", stdout=StringIO())
        self.assertEqual(PVSystem.objects.count(), 6)
        self.assertTrue(MonthlyGeneration.objects.exists())

    def test_demo_accounts_cannot_sign_in(self):
        """The original command gave 1,000 accounts the password 'password123'."""
        call_command("seed_demo_data", "--systems", "3", "--years", "1", stdout=StringIO())
        for user in User.objects.filter(username__startswith="demo-"):
            self.assertFalse(user.has_usable_password())

    def test_is_idempotent(self):
        args = ["seed_demo_data", "--systems", "5", "--years", "1"]
        call_command(*args, stdout=StringIO())
        first = (PVSystem.objects.count(), MonthlyGeneration.objects.count())
        call_command(*args, stdout=StringIO())
        self.assertEqual((PVSystem.objects.count(), MonthlyGeneration.objects.count()), first)

    def test_same_seed_gives_the_same_data(self):
        call_command(
            "seed_demo_data", "--systems", "5", "--years", "1", "--seed", "99", stdout=StringIO()
        )
        first = list(PVSystem.objects.order_by("id").values_list("county", "array_size_kwp"))
        call_command(
            "seed_demo_data",
            "--clear",
            "--systems",
            "5",
            "--years",
            "1",
            "--seed",
            "99",
            stdout=StringIO(),
        )
        second = list(PVSystem.objects.order_by("id").values_list("county", "array_size_kwp"))
        self.assertEqual(first, second)

    def test_clear_removes_previous_demo_rows(self):
        call_command("seed_demo_data", "--systems", "4", "--years", "1", stdout=StringIO())
        call_command(
            "seed_demo_data", "--clear", "--systems", "2", "--years", "1", stdout=StringIO()
        )
        self.assertEqual(PVSystem.objects.count(), 2)

    def test_readings_are_plausible(self):
        """The demo data must not itself trip the implausibility filter."""
        call_command("seed_demo_data", "--systems", "20", "--years", "1", stdout=StringIO())
        self.assertEqual(
            MonthlyGeneration.objects.count(),
            MonthlyGeneration.objects.plausible().count(),
        )

    def test_seasonality_is_realistic(self):
        """June should comfortably beat December, or the demo charts are noise.

        Two years, so a complete prior year exists whatever month it is today —
        the current year is only filled up to last month.
        """
        call_command("seed_demo_data", "--systems", "40", "--years", "2", stdout=StringIO())
        from django.db.models import Avg
        from django.utils import timezone

        complete_year = timezone.localdate().year - 1

        def mean(month):
            return MonthlyGeneration.objects.filter(year=complete_year, month=month).aggregate(
                m=Avg("energy_generated_kwh")
            )["m"]

        june, december = mean(6), mean(12)
        self.assertIsNotNone(june)
        self.assertIsNotNone(december)
        self.assertGreater(june, december * 3)


class SeedGuardTests(TestCase):
    @override_settings(DEBUG=False)
    def test_refuses_to_run_outside_debug_without_the_unlock(self):
        """The original command had no guard at all."""
        import os

        previous = os.environ.pop("DJANGO_ALLOW_DEMO_SEED", None)
        try:
            with self.assertRaises(CommandError) as ctx:
                call_command("seed_demo_data", "--systems", "1", stdout=StringIO())
            self.assertIn("DJANGO_ALLOW_DEMO_SEED", str(ctx.exception))
        finally:
            if previous is not None:
                os.environ["DJANGO_ALLOW_DEMO_SEED"] = previous
        self.assertEqual(PVSystem.objects.count(), 0)
