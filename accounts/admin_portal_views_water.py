"""
Water management views for admin portal
"""
from datetime import date, datetime
from decimal import Decimal
from calendar import monthrange
from django.shortcuts import render, redirect
from django.contrib import messages
from django.db import transaction
from django.db.models import Q
from django.views.decorators.http import require_http_methods

from .decorators import admin_required
from water.models import WaterReading, WaterRate
from water.services import compute_water_reading, create_or_update_monthly_bill_from_reading
from billing.models import MonthlyBill
from rentals.models import Lease


@admin_required
def admin_water(request):
    """Water Management dashboard with bulk entry"""
    
    # Get month/year from query params or default to current
    today = date.today()
    month = int(request.GET.get('month', today.month))
    year = int(request.GET.get('year', today.year))
    search = request.GET.get('search', '').strip().lower()
    
    reading_date = date(year, month, 1)
    
    # Get water rate for this month (latest rate before or on this date)
    rate = None
    current_rate_obj = None
    try:
        current_rate_obj = WaterRate.objects.filter(effective_date__lte=reading_date).order_by('-effective_date').first()
        if current_rate_obj:
            rate = float(current_rate_obj.rate_per_cu_m)
    except Exception:
        pass
    
    # Get active leases (no end_date or end_date >= reading month)
    active_leases = Lease.objects.filter(
        Q(end_date__isnull=True) | Q(end_date__gte=reading_date),
        start_date__lte=reading_date
    ).select_related('tenant', 'unit').order_by('unit__number')
    
    # Apply search filter if provided
    if search:
        active_leases = active_leases.filter(
            Q(unit__number__icontains=search) |
            Q(tenant__first_name__icontains=search) |
            Q(tenant__last_name__icontains=search) |
            Q(tenant__email__icontains=search)
        )
    
    # Get previous month's date for auto-fill
    if month == 1:
        prev_year = year - 1
        prev_month = 12
    else:
        prev_year = year
        prev_month = month - 1
    prev_date = date(prev_year, prev_month, 1)
    
    # Build readings data
    readings_data = []
    filled_count = 0
    missing_count = 0
    
    for lease in active_leases:
        # Get previous reading (any reading before current month, ordered by most recent)
        prev_reading = WaterReading.objects.filter(
            lease=lease,
            reading_month__lt=reading_date
        ).order_by('-reading_month').first()
        
        # If no previous reading found, try year/month match as fallback
        if not prev_reading:
            prev_reading = WaterReading.objects.filter(
                lease=lease,
                reading_month__year=prev_year,
                reading_month__month=prev_month
            ).first()
        
        previous_reading = prev_reading.current_reading if prev_reading else 0
        
        # Get current reading if exists
        existing = WaterReading.objects.filter(
            lease=lease,
            reading_month=reading_date
        ).first()
        
        # Get bill status
        existing_bill = MonthlyBill.objects.filter(
            lease=lease,
            billing_month=reading_date,
            source_water_reading__isnull=False
        ).first()
        
        has_reading = existing is not None
        if has_reading:
            filled_count += 1
        else:
            missing_count += 1
        
        current_reading = existing.current_reading if existing else None
        usage = existing.consumption if existing else 0
        amount = existing.computed_amount if existing else 0
        
        # Check if this is first billing (lease started in previous month)
        # First billing = lease started in previous month AND no previous water reading exists
        last_day_of_prev_month = monthrange(prev_year, prev_month)[1]
        prev_month_end = date(prev_year, prev_month, last_day_of_prev_month)
        
        is_first_billing = (
            lease.start_date.year == prev_year and 
            lease.start_date.month == prev_month and
            not prev_reading  # No previous water reading means this is first billing
        )
        
        # Get tenant full name (fallback to username)
        tenant_full_name = lease.tenant.get_full_name() or lease.tenant.username or ''
        
        readings_data.append({
            'lease_id': lease.id,
            'unit_number': lease.unit.number,
            'tenant_name': tenant_full_name,
            'previous_reading': previous_reading,
            'current_reading': current_reading,
            'has_reading': has_reading,
            'usage': usage,
            'amount': amount,
            'bill_paid': existing_bill.status == 'PAID' if existing_bill else False,
            'is_first_billing': is_first_billing,
            'lease_start': lease.start_date,
        })
    
    # Month/year choices for dropdowns
    month_choices = [(i, date(2000, i, 1).strftime('%B')) for i in range(1, 13)]
    year_choices = range(today.year - 1, today.year + 2)
    
    context = {
        'today': today,
        'month': month,
        'year': year,
        'month_name': date(year, month, 1).strftime('%B'),
        'month_choices': month_choices,
        'year_choices': year_choices,
        'rate': rate,
        'current_rate': f"{rate:.2f}" if rate else None,
        'total_units': len(readings_data),
        'filled_count': filled_count,
        'missing_count': missing_count,
        'readings_data': readings_data,
        'search': search,
    }
    
    return render(request, "admin_portal/water_management.html", context)


@admin_required
@require_http_methods(["POST"])
def admin_water_process(request):
    """Process bulk water readings"""
    
    month = int(request.POST.get('month', date.today().month))
    year = int(request.POST.get('year', date.today().year))
    reading_date = date(year, month, 1)
    
    # Get water rate
    try:
        water_rate = WaterRate.objects.filter(effective_date__lte=reading_date).order_by('-effective_date').first()
        if not water_rate:
            messages.error(request, f"No water rate set for {reading_date.strftime('%B %Y')}")
            return redirect('/admin-portal/water/')
        rate = water_rate.rate_per_cu_m
    except Exception as e:
        messages.error(request, f"Error getting water rate: {e}")
        return redirect('/admin-portal/water/')
    
    lease_ids = request.POST.getlist('lease_ids')
    created_count = 0
    updated_count = 0
    skipped_count = 0
    error_count = 0
    
    with transaction.atomic():
        for lease_id in lease_ids:
            prefix = f'reading_{lease_id}'
            current_reading = request.POST.get(prefix, '').strip()
            
            if not current_reading:
                continue
            
            try:
                current_reading = Decimal(current_reading)
                lease = Lease.objects.get(pk=lease_id)
                
                # Get previous reading for validation
                if month == 1:
                    prev_year = year - 1
                    prev_month = 12
                else:
                    prev_year = year
                    prev_month = month - 1
                prev_date = date(prev_year, prev_month, 1)
                
                prev_reading = WaterReading.objects.filter(
                    lease=lease,
                    reading_month__year=prev_year,
                    reading_month__month=prev_month
                ).first()
                previous_reading = prev_reading.current_reading if prev_reading else Decimal('0')
                
                # Skip if bill is paid
                existing_bill = MonthlyBill.objects.filter(
                    lease=lease,
                    billing_month=reading_date,
                    source_water_reading__isnull=False,
                    status='PAID'
                ).first()
                
                if existing_bill:
                    skipped_count += 1
                    continue
                
                # Create or update WaterReading
                reading, created = WaterReading.objects.update_or_create(
                    lease=lease,
                    reading_month=reading_date,
                    defaults={
                        'previous_reading': previous_reading,
                        'current_reading': current_reading,
                        'is_first_reading': not prev_reading,
                    }
                )
                
                # Force update reading values even if existed
                reading.previous_reading = previous_reading
                reading.current_reading = current_reading
                reading.is_first_reading = not prev_reading
                
                # Compute and save
                compute_water_reading(reading)
                reading.save()
                
                # Create/update MonthlyBill
                try:
                    bill, bill_created = create_or_update_monthly_bill_from_reading(
                        reading,
                        computed_by=request.user,
                        force_update=True
                    )
                    if bill_created:
                        created_count += 1
                    else:
                        updated_count += 1
                except Exception as e:
                    messages.warning(request, f"Unit {lease.unit.number}: {e}")
                    error_count += 1
                    
            except Lease.DoesNotExist:
                messages.error(request, f"Lease {lease_id} not found")
                error_count += 1
            except Exception as e:
                messages.error(request, f"Error processing lease {lease_id}: {e}")
                error_count += 1
    
    # Show results
    if created_count > 0:
        messages.success(request, f"Created {created_count} water bills")
    if updated_count > 0:
        messages.success(request, f"Updated {updated_count} water bills")
    if skipped_count > 0:
        messages.info(request, f"Skipped {skipped_count} paid bills")
    if error_count > 0:
        messages.warning(request, f"{error_count} errors occurred")
    
    return redirect(f'/admin-portal/water/?month={month}&year={year}')


@admin_required
@require_http_methods(["POST"])
def admin_water_rate(request):
    """Create or update water rate"""
    
    effective_date = request.POST.get('effective_date')
    rate_per_cu_m = request.POST.get('rate_per_cu_m')
    notes = request.POST.get('notes', '')
    
    if not effective_date or not rate_per_cu_m:
        messages.error(request, "Please provide both effective date and rate")
        return redirect('/admin-portal/water/')
    
    try:
        rate_value = Decimal(rate_per_cu_m)
        eff_date = datetime.strptime(effective_date, '%Y-%m-%d').date()
        
        # Create new rate (allow multiple rates with different effective dates)
        WaterRate.objects.create(
            rate_per_cu_m=rate_value,
            effective_date=eff_date,
            notes=notes,
            created_by=request.user
        )
        
        messages.success(request, f"Water rate set to ₱{rate_value} per m³ effective {eff_date}")
        
    except Exception as e:
        messages.error(request, f"Error setting water rate: {e}")
    
    return redirect('/admin-portal/water/')


@admin_required
@require_http_methods(["POST"])
def admin_water_recompute(request):
    """Recompute all water readings for a month to fix data issues"""
    
    month = int(request.POST.get('month', date.today().month))
    year = int(request.POST.get('year', date.today().year))
    reading_date = date(year, month, 1)
    
    # Get water rate
    try:
        water_rate = WaterRate.objects.filter(effective_date__lte=reading_date).order_by('-effective_date').first()
        if not water_rate:
            messages.error(request, f"No water rate set for {reading_date.strftime('%B %Y')}")
            return redirect(f'/admin-portal/water/?month={month}&year={year}')
        rate = water_rate.rate_per_cu_m
    except Exception as e:
        messages.error(request, f"Error getting water rate: {e}")
        return redirect(f'/admin-portal/water/?month={month}&year={year}')
    
    # Get all readings for this month
    readings = WaterReading.objects.filter(reading_month=reading_date)
    
    fixed_count = 0
    skipped_count = 0
    
    for reading in readings:
        try:
            # Check if bill is paid - skip if so
            existing_bill = MonthlyBill.objects.filter(
                lease=reading.lease,
                billing_month=reading_date,
                source_water_reading__isnull=False,
                status='PAID'
            ).first()
            
            if existing_bill:
                skipped_count += 1
                continue
            
            # Recompute the reading
            compute_water_reading(reading)
            reading.save()
            
            # Update the monthly bill
            create_or_update_monthly_bill_from_reading(
                reading,
                computed_by=request.user,
                force_update=True
            )
            
            fixed_count += 1
            
        except Exception as e:
            messages.warning(request, f"Could not fix {reading.lease.unit.number}: {e}")
    
    messages.success(request, f"Fixed {fixed_count} readings, skipped {skipped_count} paid bills")
    return redirect(f'/admin-portal/water/?month={month}&year={year}')
