from django import forms
from django.contrib.auth.models import User
from django.contrib.auth.forms import UserCreationForm
from .models import SolarEnergyRecord


class UserRegisterForm(UserCreationForm):
    email = forms.EmailField()

    class Meta:
        model = User
        fields = ['username', 'email', 'password1', 'password2']

class SolarEnergyRecordForm(forms.ModelForm):
    class Meta:
        model = SolarEnergyRecord
        fields = ['month', 'year', 'power_generated', 'orientation', 'panels_size', 'inverter_size', 'county']
        