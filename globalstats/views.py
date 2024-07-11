from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from .forms import SolarEnergyRecordForm
from .models import SolarEnergyRecord, MONTH_CHOICES, YEARS_CHOICES
from .forms import UserRegisterForm
from django.shortcuts import render, redirect
from django.contrib.auth import authenticate, login
from django.contrib import messages
from django.db.models import Sum
from django.db.models import Q

@login_required
def user_statistics(request):
    if request.method == 'POST':
        form = SolarEnergyRecordForm(request.POST)
        if form.is_valid():
            record = form.save(commit=False)
            record.user = request.user
            record.save()
            return redirect('user_statistics')
    else:
        form = SolarEnergyRecordForm()
    records = SolarEnergyRecord.objects.filter(user=request.user)
    return render(request, 'user_statistics.html', {'records': records, 'form': form})

@login_required
def edit_record(request, record_id):
    record = get_object_or_404(SolarEnergyRecord, id=record_id, user=request.user)
    if request.method == 'POST':
        form = SolarEnergyRecordForm(request.POST, instance=record)
        if form.is_valid():
            form.save()
            return redirect('user_statistics')
    else:
        form = SolarEnergyRecordForm(instance=record)
    return render(request, 'edit_record.html', {'form': form, 'record': record})

@login_required
def delete_record(request, record_id):
    record = get_object_or_404(SolarEnergyRecord, id=record_id, user=request.user)
    if request.method == 'POST':
        record.delete()
        return redirect('user_statistics')
    return render(request, 'delete_record.html', {'record': record})

def register(request):
    if request.method == 'POST':
        form = UserRegisterForm(request.POST)
        if form.is_valid():
            form.save()
            username = form.cleaned_data.get('username')
            password = form.cleaned_data.get('password1')
            user = authenticate(username=username, password=password)
            login(request, user)
            messages.success(request, f'Account created for {username}!')
            return redirect('user_statistics')
    else:
        form = UserRegisterForm()
    return render(request, 'register.html', {'form': form})

def county_monthly_totals(request):
    selected_month = request.GET.get('month', 'January')  # Default to January if no month is selected
    selected_year = request.GET.get('year', '2024')
    monthly_totals = SolarEnergyRecord.objects.filter(Q(month=selected_month) & Q(year=selected_year)).values('county').annotate(total_power=Sum('power_generated')).order_by('-total_power')
    
    return render(request, 'county_monthly_totals.html', {
        'monthly_totals': monthly_totals,
        'selected_month': selected_month,
        'selected_year': selected_year,
        'months': [month[0] for month in MONTH_CHOICES],
        'years': [year[0] for year in YEARS_CHOICES],
    })