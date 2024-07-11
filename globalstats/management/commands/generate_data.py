import random
from django.core.management.base import BaseCommand
from django.contrib.auth.models import User
from globalstats.models import SolarEnergyRecord
from faker import Faker
from django.utils import timezone

fake = Faker()

MONTH_CHOICES = [
    'January', 'February', 'March', 'April', 'May', 'June',
    'July', 'August', 'September', 'October', 'November', 'December'
]

COUNTY_CHOICES = [
    "Carlow", "Cavan", "Clare", "Cork", "Donegal", "Dublin", "Galway", "Kerry",
    "Kildare", "Kilkenny", "Laois", "Leitrim", "Limerick", "Longford", "Louth",
    "Mayo", "Meath", "Monaghan", "Offaly", "Roscommon", "Sligo", "Tipperary",
    "Waterford", "Westmeath", "Wexford", "Wicklow"
]

ORIENTATION = [
    "N",
    "E",
    "S",
    "W",
    "N/E",
    "N/W",
    "S/E",
    "S/W",
    "E/W",
    "N/S",
    "N/E/S",
    "N/W/S",
    "E/N/W",
    "E/S/W",
    "FLAT",
]

class Command(BaseCommand):
    help = 'Generate random data for SolarEnergyRecord model'

    def handle(self, *args, **kwargs):
        # Create 1000 users
        existing_user = []
        for _ in range(1000):
            username = fake.user_name()
            if username in existing_user:
                continue
            existing_user.append(username)
            print(f"created user {username}")
            email = fake.email()
            user = User.objects.create_user(username=username, email=email, password='password123')
            orientation = random.choice(ORIENTATION)
            county = random.choice(COUNTY_CHOICES)
            inverter_size=round(random.uniform(1.00, 6.00), ndigits=2)
            panels_size=round(random.uniform(1.00, 8.00), ndigits=2)

            # Create SolarEnergyRecord for each month
            for month in MONTH_CHOICES:
                try:
                    SolarEnergyRecord.objects.create(
                        user=user,
                        month=month,
                        year="2024",
                        county=county,
                        inverter_size=inverter_size,
                        panels_size=panels_size,
                        orientation=orientation,
                        power_generated=round(random.uniform(50, 1000), 2),  # Random power generated between 50 and 1000 kWh
                        input_date=timezone.now()
                    )
                except Exception as e:
                    pass

        self.stdout.write(self.style.SUCCESS('Successfully generated random data'))
