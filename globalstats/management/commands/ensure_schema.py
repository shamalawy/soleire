"""Create the PostgreSQL schema named by POSTGRES_SCHEMA, if it is missing.

`migrate` cannot create its own schema: the connection's search_path already
points at one, so the very first CREATE TABLE fails. This runs first, on a
connection that ignores search_path.
"""

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import connection


class Command(BaseCommand):
    help = "Create the configured PostgreSQL schema if it does not already exist."

    def handle(self, *args, **options):
        schema = getattr(settings, "POSTGRES_SCHEMA", None)
        if not schema:
            self.stdout.write("POSTGRES_SCHEMA is unset; using the default schema.")
            return

        # settings.py already restricts this to [A-Za-z0-9_], so it is safe to
        # inline — schema names cannot be passed as bind parameters to DDL.
        if not schema.replace("_", "").isalnum():
            raise CommandError(f"Refusing to create schema with unsafe name {schema!r}")

        with connection.cursor() as cursor:
            cursor.execute(f'CREATE SCHEMA IF NOT EXISTS "{schema}"')

        self.stdout.write(self.style.SUCCESS(f"Schema {schema!r} is present."))
