from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone

MONTH_CHOICES = [
    ('January', 'January'),
    ('February', 'February'),
    ('March', 'March'),
    ('April', 'April'),
    ('May', 'May'),
    ('June', 'June'),
    ('July', 'July'),
    ('August', 'August'),
    ('September', 'September'),
    ('October', 'October'),
    ('November', 'November'),
    ('December', 'December'),
]

COUNTY_CHOICES = [
    ("Carlow", "Carlow"),
    ("Cavan", "Cavan"),
    ("Clare", "Clare"),
    ("Cork", "Cork"),
    ("Donegal", "Donegal"),
    ("Dublin", "Dublin"),
    ("Galway", "Galway"),
    ("Kerry", "Kerry"),
    ("Kildare", "Kildare"),
    ("Kilkenny", "Kilkenny"),
    ("Laois", "Laois"),
    ("Leitrim", "Leitrim"),
    ("Limerick", "Limerick"),
    ("Longford", "Longford"),
    ("Louth", "Louth"),
    ("Mayo", "Mayo"),
    ("Meath", "Meath"),
    ("Monaghan", "Monaghan"),
    ("Offaly", "Offaly"),
    ("Roscommon", "Roscommon"),
    ("Sligo", "Sligo"),
    ("Tipperary", "Tipperary"),
    ("Waterfor", "Waterfor"),
    ("Westmeath", "Westmeath"),
    ("Wexford", "Wexford"),
    ("Wicklow", "Wicklow")
]

SYSTEM_ORIENTATION = [
    ("N", "N"),
    ("E", "E"),
    ("S", "S"),
    ("W", "W"),
    ("N/E", "N/E"),
    ("N/W", "N/W"),
    ("S/E", "S/E"),
    ("S/W", "S/W"),
    ("E/W", "E/W"),
    ("N/S", "N/S"),
    ("N/E/S", "N/E/S"),
    ("N/W/S", "N/W/S"),
    ("E/N/W", "E/N/W"),
    ("E/S/W", "E/S/W"),
    ("FLAT", "FLAT"),
]

YEARS_CHOICES = [
    ("2020", "2020"),
    ("2021", "2021"),
    ("2022", "2022"),
    ("2023", "2023"),
    ("2024", "2024"),
]


class SolarEnergyRecord(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    month = models.CharField(max_length=20, choices=MONTH_CHOICES, null=False)
    year = models.CharField(max_length=4,choices=YEARS_CHOICES, null=False)
    county = models.CharField(max_length=20,choices=COUNTY_CHOICES, null=False)
    orientation = models.CharField(max_length=12,choices=SYSTEM_ORIENTATION)
    panels_size = models.DecimalField(max_digits=3, decimal_places=2, )
    inverter_size = models.DecimalField(max_digits=3, decimal_places=2, )
    power_generated = models.DecimalField(max_digits=6, decimal_places=2, )
    input_date = models.DateField(default=timezone.now)

    def __str__(self):
        return f'{self.user.username} - {self.month} - {self.power_generated} kWh'

    class Meta:
        ordering = ['user', 'input_date']
        unique_together = ('user', 'month', 'input_date')
