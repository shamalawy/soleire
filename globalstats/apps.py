from django.apps import AppConfig


class GlobalstatsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "globalstats"

    def ready(self):
        # Importing for the side effect of registering the cache-invalidation
        # signal handlers.
        from globalstats import signals  # noqa: F401
