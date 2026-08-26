"""Cache invalidation.

Any write to a system or a reading changes what the public aggregates should
say, so all of them are retired at once. Doing this with signals rather than
sprinkling `invalidate_stats()` through the views means the seed command, the
admin, the shell and a future import script all stay correct for free.
"""

from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from globalstats.models import MonthlyGeneration, PVSystem
from globalstats.stats import invalidate_stats


@receiver(post_save, sender=MonthlyGeneration, dispatch_uid="soleire_reading_saved")
@receiver(post_delete, sender=MonthlyGeneration, dispatch_uid="soleire_reading_deleted")
@receiver(post_save, sender=PVSystem, dispatch_uid="soleire_system_saved")
@receiver(post_delete, sender=PVSystem, dispatch_uid="soleire_system_deleted")
def retire_cached_statistics(sender, **kwargs):
    invalidate_stats()
