"""Drop the legacy table, now that 0009 has copied every row out of it.

Kept as a separate migration so an operator can stop after 0009, verify the
counts line up, and only then take the irreversible-in-practice step. Reversing
this recreates the table; reversing 0009 refills it.
"""

from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("globalstats", "0009_migrate_legacy_records"),
    ]

    operations = [
        migrations.DeleteModel(name="SolarEnergyRecord"),
    ]
