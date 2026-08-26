"""Project URL configuration."""

from django.conf import settings
from django.contrib import admin
from django.urls import include, path

# The admin is the one place contributor identities are visible, so it is not
# left on the guessable default path. Override with DJANGO_ADMIN_PATH.
admin_path = getattr(settings, "ADMIN_PATH", "admin")

urlpatterns = [
    path(f"{admin_path}/", admin.site.urls),
    path("", include("globalstats.urls")),
]

admin.site.site_header = "soleire administration"
admin.site.site_title = "soleire"
admin.site.index_title = "Community solar statistics"
