from django.contrib import admin
from .models import SolarEnergyRecord

class SolarEnergyRecordAdmin(admin.ModelAdmin):
    list_display = ('user', 'month', 'county', 'power_generated', 'input_date')
    list_filter = ('month', 'county')
    search_fields = ('user__username', 'month')

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        if request.user.is_superuser:
            return qs
        return qs.filter(user=request.user)

admin.site.register(SolarEnergyRecord, SolarEnergyRecordAdmin)