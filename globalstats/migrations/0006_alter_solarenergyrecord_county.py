# Generated by Django 5.0.6 on 2024-07-07 03:29

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('globalstats', '0005_solarenergyrecord_inverter_size_and_more'),
    ]

    operations = [
        migrations.AlterField(
            model_name='solarenergyrecord',
            name='county',
            field=models.CharField(choices=[('Carlow', 'Carlow'), ('Cavan', 'Cavan'), ('Clare', 'Clare'), ('Cork', 'Cork'), ('Donegal', 'Donegal'), ('Dublin', 'Dublin'), ('Galway', 'Galway'), ('Kerry', 'Kerry'), ('Kildare', 'Kildare'), ('Kilkenny', 'Kilkenny'), ('Laois', 'Laois'), ('Leitrim', 'Leitrim'), ('Limerick', 'Limerick'), ('Longford', 'Longford'), ('Louth', 'Louth'), ('Mayo', 'Mayo'), ('Meath', 'Meath'), ('Monaghan', 'Monaghan'), ('Offaly', 'Offaly'), ('Roscommon', 'Roscommon'), ('Sligo', 'Sligo'), ('Tipperary', 'Tipperary'), ('Waterfor', 'Waterfor'), ('Westmeath', 'Westmeath'), ('Wexford', 'Wexford'), ('Wicklow', 'Wicklow')], max_length=20),
        ),
    ]
