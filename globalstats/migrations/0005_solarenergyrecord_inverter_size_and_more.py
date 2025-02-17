# Generated by Django 5.0.6 on 2024-07-07 02:50

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('globalstats', '0004_solarenergyrecord_orientation_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='solarenergyrecord',
            name='inverter_size',
            field=models.DecimalField(decimal_places=2, default=1.2, max_digits=3),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name='solarenergyrecord',
            name='panels_size',
            field=models.DecimalField(decimal_places=2, default=1.2, max_digits=3),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name='solarenergyrecord',
            name='year',
            field=models.CharField(choices=[('2020', '2020'), ('2021', '2021'), ('2022', '2022'), ('2023', '2023'), ('2024', '2024')], default='2024', max_length=4),
            preserve_default=False,
        ),
    ]
