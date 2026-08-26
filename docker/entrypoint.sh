#!/usr/bin/env sh
#
# Container entrypoint: block until PostgreSQL accepts connections, apply
# migrations, optionally bootstrap a superuser, then hand off to the CMD.
set -eu

echo "[entrypoint] waiting for the database..."
python manage.py wait_for_db --timeout "${DJANGO_DB_WAIT_TIMEOUT:-60}"

# A non-default schema has to exist before migrate can write into it.
if [ -n "${POSTGRES_SCHEMA:-}" ]; then
    echo "[entrypoint] ensuring schema '${POSTGRES_SCHEMA}' exists..."
    python manage.py ensure_schema
fi

if [ "${DJANGO_MIGRATE_ON_START:-true}" = "true" ]; then
    echo "[entrypoint] applying migrations..."
    python manage.py migrate --noinput
fi

# Creates the shared statistics cache table. A no-op once it exists, and
# harmless when a different cache backend is configured.
python manage.py createcachetable

# Opt-in convenience for fresh environments. Django's --noinput createsuperuser
# reads DJANGO_SUPERUSER_PASSWORD from the environment.
#
# "Already exists" is the one failure worth ignoring, so it is matched
# explicitly rather than discarding stderr wholesale — otherwise a genuine
# fault (a permissions problem, a password that fails validation) would be
# logged as "already present" and the container would carry on with no admin
# account and no indication why.
if [ -n "${DJANGO_SUPERUSER_USERNAME:-}" ] && [ -n "${DJANGO_SUPERUSER_PASSWORD:-}" ]; then
    echo "[entrypoint] ensuring superuser '${DJANGO_SUPERUSER_USERNAME}' exists..."
    if superuser_output=$(python manage.py createsuperuser --noinput \
            --username "${DJANGO_SUPERUSER_USERNAME}" \
            --email "${DJANGO_SUPERUSER_EMAIL:-}" 2>&1); then
        echo "[entrypoint] superuser created."
    elif printf '%s' "$superuser_output" | grep -qi "already exists\|is already taken"; then
        echo "[entrypoint] superuser already present, skipping."
    else
        echo "[entrypoint] ERROR: could not create the superuser:" >&2
        printf '%s\n' "$superuser_output" >&2
        exit 1
    fi
fi

echo "[entrypoint] starting: $*"
exec "$@"
