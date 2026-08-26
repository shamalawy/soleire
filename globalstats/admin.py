"""Admin configuration.

Deliberately restrained. The admin is the only surface where a contributor's
account can be tied to their readings, so it exposes as little of that link as
possible: no username column, no username search, no free browsing of other
people's rows for non-superusers.
"""

from django.contrib import admin
from django.db.models import Count, Sum

from globalstats.models import MonthlyGeneration, PVSystem


class MonthlyGenerationInline(admin.TabularInline):
    model = MonthlyGeneration
    extra = 0
    fields = ("year", "month", "energy_generated_kwh")
    ordering = ("-year", "-month")
    show_change_link = True


@admin.register(PVSystem)
class PVSystemAdmin(admin.ModelAdmin):
    # `owner` is intentionally absent: the previous admin listed and searched
    # usernames, which made re-identifying a household a two-click job for any
    # staff account.
    list_display = (
        "anonymous_ref",
        "county",
        "orientation",
        "array_size_kwp",
        "inverter_size_kw",
        "reading_count",
        "created_at",
    )
    list_filter = ("county", "orientation", "created_at")
    search_fields = ("county",)
    readonly_fields = ("created_at", "updated_at")
    date_hierarchy = "created_at"
    inlines = [MonthlyGenerationInline]
    list_select_related = False

    @admin.display(description="reference")
    def anonymous_ref(self, obj):
        """A stable opaque handle, so rows can be discussed without naming anyone."""
        return f"PV-{obj.pk:06d}"

    @admin.display(description="readings", ordering="reading_count")
    def reading_count(self, obj):
        return obj.reading_count

    def get_queryset(self, request):
        qs = super().get_queryset(request).annotate(reading_count=Count("readings"))
        if request.user.is_superuser:
            return qs
        return qs.filter(owner=request.user)

    def get_fields(self, request, obj=None):
        fields = [
            "county",
            "orientation",
            "array_size_kwp",
            "inverter_size_kw",
            "battery_capacity_kwh",
            "commissioned_year",
            "label",
            "created_at",
            "updated_at",
        ]
        # Only a superuser can see or change which account a system belongs to.
        if request.user.is_superuser:
            return ["owner", *fields]
        return fields


@admin.register(MonthlyGeneration)
class MonthlyGenerationAdmin(admin.ModelAdmin):
    list_display = ("system_ref", "year", "month", "energy_generated_kwh", "county")
    list_filter = ("year", "month", "system__county")
    search_fields = ("system__county",)
    readonly_fields = ("created_at", "updated_at")
    list_select_related = ("system",)
    ordering = ("-year", "-month")

    @admin.display(description="system")
    def system_ref(self, obj):
        return f"PV-{obj.system_id:06d}"

    @admin.display(description="county", ordering="system__county")
    def county(self, obj):
        return obj.system.county

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        if request.user.is_superuser:
            return qs
        return qs.filter(system__owner=request.user)

    def changelist_view(self, request, extra_context=None):
        """Show the aggregate totals alongside the row list."""
        extra_context = extra_context or {}
        totals = self.get_queryset(request).aggregate(
            readings=Count("id"),
            systems=Count("system", distinct=True),
            total_kwh=Sum("energy_generated_kwh"),
        )
        extra_context["totals"] = totals
        return super().changelist_view(request, extra_context)
