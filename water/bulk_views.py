"""
Bulk Water Reading Entry Views
Handles multi-tenant water reading entry in a single form.
"""
from django.shortcuts import render, redirect
from django.contrib import messages
from django.contrib.auth.decorators import login_required, user_passes_test
from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from datetime import date, timedelta
from decimal import Decimal
import calendar

from rentals.models import Lease
from billing.models import MonthlyBill
from .models import WaterReading, WaterRate, WaterComputationLog
from .services import compute_water_reading


def is_admin(user):
    return user.is_authenticated and user.role == "ADMIN"


@login_required
@user_passes_test(is_admin)
def bulk_water_reading_entry(request):
    """
    Bulk water reading entry page.
    Shows all active leases for selected month with previous readings auto-filled.
    """
    # Get selected month (default to current month)
    year = int(request.GET.get('year', date.today().year))
    month = int(request.GET.get('month', date.today().month))
    reading_date = date(year, month, 1)
    
    # Calculate previous month for auto-fill
    if month == 1:
        prev_year = year - 1
        prev_month = 12
    else:
        prev_year = year
        prev_month = month - 1
    prev_reading_date = date(prev_year, prev_month, 1)
    
    # Get active rate for this month
    try:
        rate = WaterRate.objects.filter(
            effective_date__lte=reading_date
        ).order_by('-effective_date').first()
        rate_per_cu_m = rate.rate_per_cu_m if rate else None
    except:
        rate_per_cu_m = None
    
    # Get all active leases (no end_date or end_date >= reading month)
    active_leases = Lease.objects.filter(
        Q(end_date__isnull=True) | Q(end_date__gte=reading_date),
        start_date__lte=reading_date
    ).select_related('tenant', 'unit').order_by('unit__number')
    
    # Prepare data for each lease
    lease_data = []
    for lease in active_leases:
        # Check if reading already exists for this month
        existing = WaterReading.objects.filter(
            lease=lease,
            reading_month=reading_date
        ).first()
        
        # Get previous month's reading for auto-fill
        prev_reading = WaterReading.objects.filter(
            lease=lease,
            reading_month=prev_reading_date
        ).first()
        
        # Check if bill exists and is paid
        existing_bill = MonthlyBill.objects.filter(
            lease=lease,
            billing_month=reading_date,
            source_water_reading__isnull=False
        ).first()
        
        lease_data.append({
            'lease': lease,
            'tenant_name': lease.tenant.get_full_name() or lease.tenant.email,
            'unit_number': lease.unit.number,
            'previous_reading': prev_reading.current_reading if prev_reading else 0,
            'current_reading': existing.current_reading if existing else '',
            'is_first_reading': existing.is_first_reading if existing else not prev_reading,
            'existing': existing,
            'bill_exists': existing_bill is not None,
            'bill_paid': existing_bill.status == 'PAID' if existing_bill else False,
        })
    
    context = {
        'reading_date': reading_date,
        'prev_reading_date': prev_reading_date,
        'rate_per_cu_m': rate_per_cu_m,
        'lease_data': lease_data,
        'months': list(range(1, 13)),
        'years': list(range(2024, 2028)),
        'selected_month': month,
        'selected_year': year,
    }
    
    return render(request, 'water/bulk_entry.html', context)


@login_required
@user_passes_test(is_admin)
def bulk_water_reading_process(request):
    """
    Process bulk water reading submission.
    Creates/updates readings and bills for all submitted entries.
    """
    if request.method != 'POST':
        return redirect('water:bulk_entry')
    
    year = int(request.POST.get('year', date.today().year))
    month = int(request.POST.get('month', date.today().month))
    reading_date = date(year, month, 1)
    
    # Get active rate
    try:
        rate = WaterRate.objects.filter(
            effective_date__lte=reading_date
        ).order_by('-effective_date').first()
        if not rate:
            messages.error(request, "No WaterRate configured for this month. Please set a rate first.")
            return redirect('water:bulk_entry')
        rate_per_cu_m = rate.rate_per_cu_m
    except Exception as e:
        messages.error(request, f"Error fetching WaterRate: {e}")
        return redirect('water:bulk_entry')
    
    # Get all lease IDs from form
    lease_ids = request.POST.getlist('lease_ids')
    
    results = {
        'created': [],
        'updated': [],
        'errors': [],
        'skipped': [],
    }
    
    with transaction.atomic():
        for lease_id in lease_ids:
            try:
                lease = Lease.objects.get(id=lease_id)
                
                # Get form data
                prefix = f'lease_{lease_id}_'
                current_reading = request.POST.get(prefix + 'current_reading', '').strip()
                is_first = request.POST.get(prefix + 'is_first_reading') == 'on'
                
                # Skip if no reading provided
                if not current_reading:
                    continue
                
                try:
                    current_reading = Decimal(current_reading)
                except:
                    results['errors'].append(f"{lease.unit.number}: Invalid reading value")
                    continue
                
                # Get previous reading
                if month == 1:
                    prev_year = year - 1
                    prev_month = 12
                else:
                    prev_year = year
                    prev_month = month - 1
                prev_date = date(prev_year, prev_month, 1)
                
                prev_reading_obj = WaterReading.objects.filter(
                    lease=lease,
                    reading_month=prev_date
                ).first()
                previous_reading = prev_reading_obj.current_reading if prev_reading_obj else Decimal('0')
                
                # Validation
                if not is_first and current_reading < previous_reading:
                    results['errors'].append(
                        f"{lease.unit.number}: Current reading ({current_reading}) "
                        f"must be >= previous reading ({previous_reading})"
                    )
                    continue
                
                # Check for paid bill
                existing_bill = MonthlyBill.objects.filter(
                    lease=lease,
                    billing_month=reading_date,
                    source_water_reading__isnull=False,
                    status='PAID'
                ).first()
                
                if existing_bill:
                    results['skipped'].append(
                        f"{lease.unit.number}: Bill #{existing_bill.id} is already PAID"
                    )
                    continue
                
                # Create or update WaterReading
                reading, created = WaterReading.objects.update_or_create(
                    lease=lease,
                    reading_month=reading_date,
                    defaults={
                        'previous_reading': previous_reading,
                        'current_reading': current_reading,
                        'is_first_reading': is_first,
                    }
                )
                
                # Compute the reading
                compute_water_reading(reading)
                reading.save()  # Save computed values
                
                # Create MonthlyBill
                from .services import create_or_update_monthly_bill_from_reading
                try:
                    bill, bill_created = create_or_update_monthly_bill_from_reading(
                        reading,
                        computed_by=request.user,
                        force_update=True
                    )
                    
                    if created:
                        results['created'].append(
                            f"{lease.unit.number}: Bill #{bill.id} (₱{reading.computed_amount})"
                        )
                    else:
                        results['updated'].append(
                            f"{lease.unit.number}: Bill #{bill.id} updated (₱{reading.computed_amount})"
                        )
                        
                except Exception as e:
                    results['errors'].append(f"{lease.unit.number}: Bill creation failed - {e}")
                    
            except Lease.DoesNotExist:
                results['errors'].append(f"Lease {lease_id}: Not found")
            except Exception as e:
                results['errors'].append(f"Lease {lease_id}: {e}")
    
    # Show results
    if results['created']:
        messages.success(request, f"✅ Created {len(results['created'])} bills: " + ", ".join(results['created'][:5]))
    if results['updated']:
        messages.info(request, f"📝 Updated {len(results['updated'])} bills: " + ", ".join(results['updated'][:5]))
    if results['skipped']:
        messages.warning(request, f"⏭️ Skipped {len(results['skipped'])} paid bills")
    if results['errors']:
        for error in results['errors'][:10]:  # Show first 10 errors
            messages.error(request, f"❌ {error}")
    
    return redirect(f'/water/bulk-entry/?year={year}&month={month}')
