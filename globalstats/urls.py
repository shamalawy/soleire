"""URL map.

Split out of `soleir/urls.py` so the app is self-contained and its routes can
be mounted under a prefix if the site ever grows a second app.

The old `/statistics/` and `/county_totals/` paths are kept as permanent
redirects — they will be sitting in people's bookmarks and in the community
forum posts that brought them here.
"""

from django.contrib.auth import views as auth_views
from django.urls import path
from django.views.generic import RedirectView

from globalstats import views

urlpatterns = [
    # ---- public statistics -------------------------------------------------
    path("", views.home, name="home"),
    path("stats/counties/", views.county_stats, name="county_stats"),
    path("stats/trends/", views.trends, name="trends"),
    path("stats/systems/", views.system_comparison, name="system_comparison"),
    path("about/", views.about, name="about"),
    # ---- open data ---------------------------------------------------------
    path("data/counties.csv", views.export_counties_csv, name="export_counties_csv"),
    path("data/monthly.csv", views.export_monthly_csv, name="export_monthly_csv"),
    path("api/stats/<slug:dataset>/", views.stats_api, name="stats_api"),
    path("healthz/", views.healthz, name="healthz"),
    # ---- accounts ----------------------------------------------------------
    path(
        "accounts/login/",
        auth_views.LoginView.as_view(
            template_name="accounts/login.html", redirect_authenticated_user=True
        ),
        name="login",
    ),
    # Django 5 only accepts POST here, which is why every logout control in the
    # templates is a form button rather than a link.
    path("accounts/logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("accounts/register/", views.register, name="register"),
    path("accounts/welcome/", views.welcome, name="welcome"),
    path("accounts/delete/", views.delete_account, name="delete_account"),
    path(
        "accounts/password-change/",
        auth_views.PasswordChangeView.as_view(
            template_name="accounts/password_change.html",
            success_url="/accounts/password-change/done/",
        ),
        name="password_change",
    ),
    path(
        "accounts/password-change/done/",
        auth_views.PasswordChangeDoneView.as_view(
            template_name="accounts/password_change_done.html"
        ),
        name="password_change_done",
    ),
    # ---- contributor area --------------------------------------------------
    path("me/", views.my_records, name="my_records"),
    path("me/export.csv", views.export_my_data, name="export_my_data"),
    path("me/systems/new/", views.system_create, name="system_create"),
    path("me/systems/<int:system_id>/", views.system_detail, name="system_detail"),
    path("me/systems/<int:system_id>/edit/", views.system_edit, name="system_edit"),
    path("me/systems/<int:system_id>/delete/", views.system_delete, name="system_delete"),
    path("me/systems/<int:system_id>/year/", views.reading_bulk, name="reading_bulk"),
    path("me/systems/<int:system_id>/readings/new/", views.reading_create, name="reading_create"),
    path("me/systems/<int:system_id>/benchmark/", views.benchmark, name="benchmark"),
    path("me/readings/<int:reading_id>/edit/", views.reading_edit, name="reading_edit"),
    path("me/readings/<int:reading_id>/delete/", views.reading_delete, name="reading_delete"),
    # ---- legacy routes -----------------------------------------------------
    path("login/", RedirectView.as_view(pattern_name="login", permanent=True)),
    path("register/", RedirectView.as_view(pattern_name="register", permanent=True)),
    path("statistics/", RedirectView.as_view(pattern_name="my_records", permanent=True)),
    path("county_totals/", RedirectView.as_view(pattern_name="county_stats", permanent=True)),
]
