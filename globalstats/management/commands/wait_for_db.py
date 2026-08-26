"""Block until the configured database accepts connections.

Compose's `depends_on: service_healthy` covers the common case, but a restarted
database, a managed instance still provisioning, or a plain `docker run` all
leave the web process racing the database. Polling here keeps the entrypoint
simple and gives a clear log line instead of a stack trace.
"""

import logging
import time

from django.core.management.base import BaseCommand, CommandError
from django.db import connections
from django.db.utils import OperationalError

logger = logging.getLogger("soleire")


class Command(BaseCommand):
    help = "Wait for the default database connection to become available."

    def add_arguments(self, parser):
        parser.add_argument(
            "--timeout",
            type=float,
            default=60.0,
            help="Seconds to keep retrying before giving up (default: 60).",
        )
        parser.add_argument(
            "--interval",
            type=float,
            default=1.0,
            help="Seconds between attempts (default: 1).",
        )

    def handle(self, *args, **options):
        timeout = options["timeout"]
        interval = options["interval"]
        deadline = time.monotonic() + timeout
        attempt = 0
        last_error = None

        while time.monotonic() < deadline:
            attempt += 1
            connection = connections["default"]
            try:
                connection.ensure_connection()
            except OperationalError as exc:
                last_error = exc
                # Drop the half-open connection so the next attempt redials.
                connection.close()
                self.stdout.write(f"  attempt {attempt}: database unavailable, retrying...")
                time.sleep(interval)
            else:
                self.stdout.write(self.style.SUCCESS(f"Database ready after {attempt} attempt(s)."))
                return

        raise CommandError(
            f"Database still unavailable after {timeout:.0f}s ({attempt} attempts). "
            f"Last error: {last_error}"
        )
