"""Tiny typed helpers for reading configuration out of the environment.

Deliberately dependency-free: the whole surface is four readers plus a
PostgreSQL URL parser, which is less code than wiring up django-environ and
keeps the container image small.
"""

import os
from urllib.parse import unquote, urlparse

from django.core.exceptions import ImproperlyConfigured

TRUTHY = {"1", "true", "t", "yes", "y", "on"}
FALSY = {"0", "false", "f", "no", "n", "off"}


def get(name, default=None):
    """Return ``$name``, treating an empty/whitespace value as unset."""
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    return raw.strip()


def get_bool(name, default=False):
    raw = get(name)
    if raw is None:
        return default
    lowered = raw.lower()
    if lowered in TRUTHY:
        return True
    if lowered in FALSY:
        return False
    raise ImproperlyConfigured(
        f"{name}={raw!r} is not a boolean; use one of {sorted(TRUTHY | FALSY)}"
    )


def get_int(name, default):
    raw = get(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ImproperlyConfigured(f"{name}={raw!r} is not an integer") from exc


def get_list(name, default=()):
    """Split a comma-separated value, dropping blanks."""
    raw = get(name)
    if raw is None:
        return list(default)
    return [item.strip() for item in raw.split(",") if item.strip()]


def parse_database_url(url):
    """Turn ``postgres://user:pw@host:port/name`` into Django DATABASES parts.

    Only PostgreSQL is accepted — the project targets Postgres-specific
    features (generated columns, per-schema search paths) and silently falling
    back to SQLite would hide a misconfiguration until a query failed.
    """
    parsed = urlparse(url)
    if parsed.scheme not in {"postgres", "postgresql", "psql"}:
        raise ImproperlyConfigured(
            f"DATABASE_URL must use a postgres:// scheme, got {parsed.scheme!r}"
        )
    name = unquote(parsed.path or "").lstrip("/")
    if not name:
        raise ImproperlyConfigured("DATABASE_URL is missing a database name")
    return {
        "NAME": name,
        "USER": unquote(parsed.username or ""),
        "PASSWORD": unquote(parsed.password or ""),
        "HOST": parsed.hostname or "",
        "PORT": str(parsed.port or ""),
    }
