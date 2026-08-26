"""Django settings for the soleire project.

Every deployment-specific value comes from the environment so that one image
can be promoted from a laptop to production unchanged. See `.env.example` for
the full list; anything security-relevant fails loudly rather than falling back
to an insecure default.
"""

from pathlib import Path

from django.core.exceptions import ImproperlyConfigured

from soleir import env

BASE_DIR = Path(__file__).resolve().parent.parent

# --------------------------------------------------------------------------
# Core
# --------------------------------------------------------------------------

DEBUG = env.get_bool("DJANGO_DEBUG", False)

SECRET_KEY = env.get("DJANGO_SECRET_KEY")
if not SECRET_KEY:
    if not DEBUG:
        raise ImproperlyConfigured(
            "DJANGO_SECRET_KEY must be set when DJANGO_DEBUG is false. "
            'Generate one with: python -c "import secrets; print(secrets.token_urlsafe(64))"'
        )
    # Development-only fallback so `manage.py` works straight after a clone.
    SECRET_KEY = "django-insecure-local-development-key-do-not-deploy"

ALLOWED_HOSTS = env.get_list("DJANGO_ALLOWED_HOSTS", default=["localhost", "127.0.0.1", "[::1]"])
if "*" in ALLOWED_HOSTS and not DEBUG:
    raise ImproperlyConfigured(
        "DJANGO_ALLOWED_HOSTS=* disables Host header validation; list real hostnames."
    )

CSRF_TRUSTED_ORIGINS = env.get_list("DJANGO_CSRF_TRUSTED_ORIGINS")

ROOT_URLCONF = "soleir.urls"
WSGI_APPLICATION = "soleir.wsgi.application"
ASGI_APPLICATION = "soleir.asgi.application"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "my_records"
LOGOUT_REDIRECT_URL = "home"

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.humanize",
    "globalstats",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    # Must sit directly below SecurityMiddleware to serve static files itself.
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        # Absolute path: a relative "templates" only resolves when the process
        # happens to be started from the project root.
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

# --------------------------------------------------------------------------
# Database — PostgreSQL only
# --------------------------------------------------------------------------

database_url = env.get("DATABASE_URL")
if database_url:
    _db = env.parse_database_url(database_url)
else:
    _db = {
        "NAME": env.get("POSTGRES_DB", "soleire"),
        "USER": env.get("POSTGRES_USER", "soleire"),
        "PASSWORD": env.get("POSTGRES_PASSWORD", ""),
        "HOST": env.get("POSTGRES_HOST", "localhost"),
        "PORT": env.get("POSTGRES_PORT", "5432"),
    }

# Optional: keep the project's tables in a dedicated schema rather than
# `public`, which matters when the cluster is shared. `manage.py ensure_schema`
# creates it; the entrypoint runs that before migrating.
POSTGRES_SCHEMA = env.get("POSTGRES_SCHEMA")
_db_options = {}
if POSTGRES_SCHEMA:
    if not POSTGRES_SCHEMA.replace("_", "").isalnum():
        raise ImproperlyConfigured(
            f"POSTGRES_SCHEMA={POSTGRES_SCHEMA!r} must be alphanumeric/underscore only."
        )
    _db_options["options"] = f"-c search_path={POSTGRES_SCHEMA},public"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        **_db,
        "CONN_MAX_AGE": env.get_int("DJANGO_CONN_MAX_AGE", 60),
        "CONN_HEALTH_CHECKS": True,
        "OPTIONS": _db_options,
        "TEST": {"NAME": f"test_{_db['NAME']}"},
    }
}

# --------------------------------------------------------------------------
# Authentication
# --------------------------------------------------------------------------

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
        "OPTIONS": {"min_length": 10},
    },
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# Argon2 first (needs argon2-cffi, which is in requirements.txt); the rest stay
# listed so existing PBKDF2 hashes keep verifying and are upgraded on login.
PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.Argon2PasswordHasher",
    "django.contrib.auth.hashers.PBKDF2PasswordHasher",
    "django.contrib.auth.hashers.PBKDF2SHA1PasswordHasher",
    "django.contrib.auth.hashers.ScryptPasswordHasher",
]

# --------------------------------------------------------------------------
# Internationalisation — the dataset is Ireland-specific
# --------------------------------------------------------------------------

LANGUAGE_CODE = "en-ie"
TIME_ZONE = env.get("DJANGO_TIME_ZONE", "Europe/Dublin")
USE_I18N = True
USE_TZ = True

# --------------------------------------------------------------------------
# Static files
# --------------------------------------------------------------------------

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"]

STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {
        # Hashed, compressed filenames served straight from the app process.
        # Falls back to the plain backend under DEBUG so a missing manifest
        # entry doesn't break `runserver`.
        "BACKEND": (
            "whitenoise.storage.CompressedManifestStaticFilesStorage"
            if not DEBUG
            else "whitenoise.storage.CompressedStaticFilesStorage"
        )
    },
}
WHITENOISE_MAX_AGE = 31536000 if not DEBUG else 0

# --------------------------------------------------------------------------
# Security hardening (mostly no-ops under DEBUG)
# --------------------------------------------------------------------------

BEHIND_PROXY = env.get_bool("DJANGO_BEHIND_PROXY", False)
if BEHIND_PROXY:
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    USE_X_FORWARDED_HOST = True

X_FRAME_OPTIONS = "DENY"
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"
SECURE_CROSS_ORIGIN_OPENER_POLICY = "same-origin"

SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SAMESITE = "Lax"
SESSION_COOKIE_AGE = env.get_int("DJANGO_SESSION_COOKIE_AGE", 60 * 60 * 24 * 14)

_https = env.get_bool("DJANGO_SECURE_COOKIES", not DEBUG)
SESSION_COOKIE_SECURE = _https
CSRF_COOKIE_SECURE = _https
# Defaults to on whenever you have declared a TLS-terminating proxy in front:
# without SECURE_PROXY_SSL_HEADER set, redirecting would loop forever, so the
# two settings are tied together rather than defaulted independently.
SECURE_SSL_REDIRECT = env.get_bool("DJANGO_SECURE_SSL_REDIRECT", BEHIND_PROXY)
SECURE_HSTS_SECONDS = env.get_int("DJANGO_SECURE_HSTS_SECONDS", 0 if DEBUG else 31536000)
SECURE_HSTS_INCLUDE_SUBDOMAINS = SECURE_HSTS_SECONDS > 0
SECURE_HSTS_PRELOAD = SECURE_HSTS_SECONDS > 0

DATA_UPLOAD_MAX_NUMBER_FIELDS = 1000

# --------------------------------------------------------------------------
# Caching — public aggregates are recomputed at most once per interval
# --------------------------------------------------------------------------

STATS_CACHE_SECONDS = env.get_int("SOLEIRE_STATS_CACHE_SECONDS", 300)

# The default is the database, not local memory, because gunicorn runs several
# worker processes and LocMemCache gives each one a private copy. Two visitors
# hitting different workers would see different figures for the length of the
# TTL, a contributor would refresh after filing a year and see nothing change,
# and no process could invalidate another's entries. A shared cache in the
# PostgreSQL instance already running costs nothing extra to operate.
#
# Point DJANGO_CACHE_URL at redis://... on a deployment large enough to want it.
cache_url = env.get("DJANGO_CACHE_URL")
if cache_url:
    CACHES = {
        "default": {"BACKEND": "django.core.cache.backends.redis.RedisCache", "LOCATION": cache_url}
    }
elif env.get_bool("DJANGO_CACHE_LOCMEM", False):
    # Single-process only: fine under `runserver`, wrong under gunicorn.
    CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            "LOCATION": "soleire-stats",
        }
    }
else:
    CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.db.DatabaseCache",
            "LOCATION": "soleire_cache",
        }
    }

# --------------------------------------------------------------------------
# Application settings
# --------------------------------------------------------------------------

# k-anonymity floor: an aggregate bucket is only published once this many
# distinct systems have contributed to it. See globalstats/stats.py.
SOLEIRE_MIN_GROUP_SIZE = max(1, env.get_int("SOLEIRE_MIN_GROUP_SIZE", 3))

# Page size for the personal records table.
SOLEIRE_PAGE_SIZE = env.get_int("SOLEIRE_PAGE_SIZE", 24)

# --------------------------------------------------------------------------
# Logging
# --------------------------------------------------------------------------

LOG_LEVEL = env.get("DJANGO_LOG_LEVEL", "DEBUG" if DEBUG else "INFO").upper()

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "verbose": {
            "format": "%(asctime)s %(levelname)-8s %(name)s %(message)s",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "verbose",
        },
    },
    "root": {"handlers": ["console"], "level": LOG_LEVEL},
    "loggers": {
        "django.db.backends": {"level": "INFO", "handlers": ["console"], "propagate": False},
        "soleire": {"level": LOG_LEVEL, "handlers": ["console"], "propagate": False},
    },
}

# Path the Django admin is mounted at, without slashes. Changing it does not
# make the admin secure on its own, but it keeps it out of the way of the
# automated scanners that hammer /admin/ all day.
ADMIN_PATH = env.get("DJANGO_ADMIN_PATH", "admin").strip("/")
