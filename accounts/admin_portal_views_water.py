"""
Water management views for admin portal
"""
import csv
from datetime import date, datetime
from decimal import Decimal
from calendar import monthrange
from django.http import HttpResponse
from django.shortcuts import render, redirect
from django.contrib import messages
from django.db import transaction
from django.db.models import Q
from django.views.decorators.http import require_http_methods

from .decorators import admin_required
from water.models import WaterBillingSettings, WaterReading, WaterRate
from water.services import (
    compute_water_reading,
    create_or_update_monthly_bill_from_reading,
    get_water_billing_settings_for_month,
    is_water_bill_locked,
    previous_unpaid_water_balance,
)
from billing.models import MonthlyBill
from rentals.models import Lease


def _active_water_leases(reading_date):
    billed_lease_ids = MonthlyBill.objects.filter(
        billing_month__year=reading_date.year,
        billing_month__month=reading_date.month,
        lease__tenant__is_active=True,
    ).values_list("lease_id", flat=True)
    return Lease.objects.filter(
        Q(end_date__isnull=True) | Q(end_date__gte=reading_date),
        Q(status=Lease.STATUS_ACTIVE)
        | Q(is_active=True)
        | Q(unit__status="OCCUPIED", tenant__is_active=True)
        | Q(id__in=billed_lease_ids),
        start_date__lt=reading_date
    ).select_related('tenant', 'tenant__tenantprofile', 'unit').order_by('unit__number')


def _tenant_display_name(user):
    profile = getattr(user, "tenantprofile", None)
    if profile:
        full_name = f"{profile.first_name or ''} {profile.last_name or ''}".strip()
        if full_name:
            return full_name
    return user.get_full_name() or user.email or user.username or ""


def _water_search_filter(queryset, search):
    if not search:
        return queryset
    return queryset.filter(
        Q(unit__number__icontains=search) |
        Q(tenant__tenantprofile__first_name__icontains=search) |
        Q(tenant__tenantprofile__last_name__icontains=search) |
        Q(tenant__email__icontains=search)
    )


def _total_month_usage_for_leases(lease_ids, reading_date):
    return sum(
        WaterReading.objects.filter(
            lease_id__in=lease_ids,
            reading_month=reading_date,
        ).values_list('consumption', flat=True),
        Decimal("0.00"),
    )


def _recompute_unpaid_water_readings_for_month(reading_date, computed_by):
    readings = list(WaterReading.objects.select_related('lease__unit').filter(reading_month=reading_date))
    if not readings:
        return 0, 0, 0

    billing_settings = get_water_billing_settings_for_month(reading_date)
    total_month_consumption = sum((reading.consumption for reading in readings), Decimal("0.00"))
    fixed_count = 0
    skipped_count = 0
    error_count = 0

    for reading in readings:
        try:
            existing_bill = MonthlyBill.objects.filter(
                lease=reading.lease,
                billing_month=reading_date,
            ).first()
            if is_water_bill_locked(existing_bill):
                skipped_count += 1
                continue

            compute_water_reading(
                reading,
                total_month_consumption=total_month_consumption,
                shared_pump_total=billing_settings.shared_pump_total,
                vat_percent=billing_settings.vat_percent,
                previous_unpaid_water_amount=previous_unpaid_water_balance(reading.lease, reading_date),
            )
            reading.save()
            create_or_update_monthly_bill_from_reading(
                reading,
                computed_by=computed_by,
                force_update=True,
            )
            fixed_count += 1
        except Exception:
            error_count += 1

    return fixed_count, skipped_count, error_count


@admin_required
def admin_water(request):
    """Water Management dashboard with bulk entry"""
    
    # Get month/year from query params or default to current
    today = date.today()
    month = int(request.GET.get('month', today.month))
    year = int(request.GET.get('year', today.year))
    search = request.GET.get('search', '').strip().lower()
    
    reading_date = date(year, month, 1)
    billing_settings = get_water_billing_settings_for_month(reading_date)

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
    active_leases_qs = _active_water_leases(reading_date)
    all_active_lease_ids = list(active_leases_qs.values_list('id', flat=True))
    active_leases = active_leases_qs
    
    # Apply search filter if provided
    active_leases = _water_search_filter(active_leases, search)
    
    # Get previous month's date for auto-fill
    if month == 1:
        prev_year = year - 1
        prev_month = 12
    else:
        prev_year = year
        prev_month = month - 1
    prev_date = date(prev_year, prev_month, 1)
    
    active_leases = list(active_leases)
    lease_ids = [lease.id for lease in active_leases]
    current_readings = {
        reading.lease_id: reading
        for reading in WaterReading.objects.filter(
            lease_id__in=lease_ids,
            reading_month=reading_date,
        )
    }
    previous_readings = {}
    for reading in WaterReading.objects.filter(
        lease_id__in=lease_ids,
        reading_month__lt=reading_date,
    ).order_by('lease_id', '-reading_month', '-id'):
        previous_readings.setdefault(reading.lease_id, reading)
    bill_statuses = {
        bill.lease_id: bill
        for bill in MonthlyBill.objects.filter(
            lease_id__in=lease_ids,
            billing_month=reading_date,
        )
    }
    previous_unpaid_water = {lease_id: Decimal("0.00") for lease_id in lease_ids}
    previous_unpaid_bills = MonthlyBill.objects.filter(
        lease_id__in=lease_ids,
        billing_month__lt=reading_date,
    ).filter(Q(status="UNPAID") | Q(status="PARTIALLY_PAID"))
    for bill in previous_unpaid_bills:
        previous_unpaid_water[ bill.lease_id ] += bill.water_balance

    total_month_usage = _total_month_usage_for_leases(all_active_lease_ids, reading_date)

    # Build readings data
    readings_data = []
    filled_count = 0
    missing_count = 0
    
    for lease in active_leases:
        # Get previous reading (any reading before current month, ordered by most recent)
        prev_reading = previous_readings.get(lease.id)
        previous_reading = prev_reading.current_reading if prev_reading else 0
        existing = current_readings.get(lease.id)
        existing_bill = bill_statuses.get(lease.id)
        
        has_reading = existing is not None
        if has_reading:
            filled_count += 1
        else:
            missing_count += 1
        
        current_reading = existing.current_reading if existing else None
        usage = existing.consumption if existing else 0
        amount = existing.computed_amount if existing else 0
        usage_share_percent = (
            (usage / total_month_usage * Decimal("100.00")).quantize(Decimal("0.01"))
            if existing and total_month_usage > 0
            else Decimal("0.00")
        )
        
        # Check if this is first billing (lease started in previous month)
        # First billing = lease started in previous month AND no previous water reading exists
        last_day_of_prev_month = monthrange(prev_year, prev_month)[1]
        prev_month_end = date(prev_year, prev_month, last_day_of_prev_month)
        
        is_first_billing = (
            lease.start_date.year == prev_year and 
            lease.start_date.month == prev_month and
            not prev_reading  # No previous water reading means this is first billing
        )
        
        tenant_full_name = _tenant_display_name(lease.tenant)
        
        readings_data.append({
            'lease_id': lease.id,
            'unit_number': lease.unit.number,
            'tenant_name': tenant_full_name,
            'previous_reading': previous_reading,
            'current_reading': current_reading,
            'has_reading': has_reading,
            'usage': usage,
            'usage_share_percent': usage_share_percent,
            'amount': amount,
            'base_water_amount': existing.base_water_amount if existing else 0,
            'shared_pump_amount': existing.shared_pump_amount if existing else 0,
            'vat_percent': existing.vat_percent if existing else billing_settings.vat_percent,
            'vat_amount': existing.vat_amount if existing else 0,
            'previous_unpaid_water_amount': existing.previous_unpaid_water_amount if existing else previous_unpaid_water.get(lease.id, Decimal("0.00")),
            'rate_used': existing.rate_used if existing else (Decimal(str(rate)) if rate else Decimal("0.00")),
            'reference': existing_bill.payment_reference if existing_bill else "",
            'bill_paid': is_water_bill_locked(existing_bill),
            'bill_status': existing_bill.status if existing_bill else "",
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
        'shared_pump_total': billing_settings.shared_pump_total,
        'vat_percent': billing_settings.vat_percent,
        'total_units': len(readings_data),
        'filled_count': filled_count,
        'missing_count': missing_count,
        'readings_data': readings_data,
        'search': search,
    }
    
    return render(request, "admin_portal/water_management.html", context)


@admin_required
def admin_water_export_csv(request):
    today = date.today()
    month = int(request.GET.get('month', today.month))
    year = int(request.GET.get('year', today.year))
    search = request.GET.get('search', '').strip().lower()
    reading_date = date(year, month, 1)

    active_leases_qs = _active_water_leases(reading_date)
    all_active_lease_ids = list(active_leases_qs.values_list('id', flat=True))
    total_month_usage = _total_month_usage_for_leases(all_active_lease_ids, reading_date)
    active_leases = list(_water_search_filter(active_leases_qs, search))
    lease_ids = [lease.id for lease in active_leases]

    current_readings = {
        reading.lease_id: reading
        for reading in WaterReading.objects.filter(
            lease_id__in=lease_ids,
            reading_month=reading_date,
        )
    }
    bill_statuses = {
        bill.lease_id: bill
        for bill in MonthlyBill.objects.filter(
            lease_id__in=lease_ids,
            billing_month=reading_date,
        )
    }

    filename = f"water_billing_{year}_{month:02d}.csv"
    response = HttpResponse(content_type="text/csv")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    writer = csv.writer(response)
    writer.writerow([
        "Billing Month",
        "Unit",
        "Tenant",
        "Last Reading (m3)",
        "Current Reading (m3)",
        "Usage (m3)",
        "Rate",
        "Shared Pump Rate (%)",
        "Shared Pump Price",
        "Base Water Amount",
        "VAT Percent",
        "VAT Amount",
        "Previous Unpaid Water",
        "Final Water Price",
        "Status",
        "Reference",
    ])

    for lease in active_leases:
        reading = current_readings.get(lease.id)
        bill = bill_statuses.get(lease.id)
        usage = reading.consumption if reading else Decimal("0.00")
        usage_share_percent = (
            (usage / total_month_usage * Decimal("100.00")).quantize(Decimal("0.01"))
            if reading and total_month_usage > 0
            else Decimal("0.00")
        )
        tenant_name = _tenant_display_name(lease.tenant)
        status = "Water Paid" if is_water_bill_locked(bill) else ("Completed" if reading else "Pending")
        writer.writerow([
            reading_date.strftime("%B %Y"),
            lease.unit.number,
            tenant_name,
            reading.previous_reading if reading else "",
            reading.current_reading if reading else "",
            usage if reading else "",
            reading.rate_used if reading else "",
            usage_share_percent if reading else "",
            reading.shared_pump_amount if reading else "",
            reading.base_water_amount if reading else "",
            reading.vat_percent if reading else "",
            reading.vat_amount if reading else "",
            reading.previous_unpaid_water_amount if reading else "",
            reading.computed_amount if reading else "",
            status,
            bill.payment_reference if bill else "",
        ])

    return response


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
    touched_reading_ids = []
    billing_settings = get_water_billing_settings_for_month(reading_date)

    for lease_id in lease_ids:
        prefix = f'reading_{lease_id}'
        current_reading = request.POST.get(prefix, '').strip()

        if not current_reading:
            continue

        try:
            current_reading = Decimal(current_reading)
            lease = _active_water_leases(reading_date).get(pk=lease_id)

            existing_bill = MonthlyBill.objects.filter(
                lease=lease,
                billing_month=reading_date,
            ).first()
            if is_water_bill_locked(existing_bill):
                skipped_count += 1
                continue

            if WaterReading.objects.filter(lease=lease, reading_month=reading_date).exists():
                skipped_count += 1
                continue

            with transaction.atomic():
                prev_reading = WaterReading.objects.filter(
                    lease=lease,
                    reading_month__lt=reading_date,
                ).order_by('-reading_month', '-id').first()
                previous_reading = prev_reading.current_reading if prev_reading else Decimal('0')

                reading = WaterReading(
                    lease=lease,
                    reading_month=reading_date,
                    previous_reading=previous_reading,
                    current_reading=current_reading,
                    is_first_reading=not prev_reading,
                    read_by=request.user,
                )
                compute_water_reading(
                    reading,
                    total_month_consumption=Decimal("0.00"),
                    shared_pump_total=Decimal("0.00"),
                    vat_percent=billing_settings.vat_percent,
                    previous_unpaid_water_amount=previous_unpaid_water_balance(lease, reading_date),
                )
                reading.save()
                touched_reading_ids.append(reading.id)

        except Lease.DoesNotExist:
            messages.error(request, f"Lease {lease_id} not found")
            error_count += 1
        except Exception as e:
            messages.error(request, f"Error processing lease {lease_id}: {e}")
            error_count += 1

    if touched_reading_ids:
        month_readings = list(WaterReading.objects.filter(reading_month=reading_date))
        total_month_consumption = sum((reading.consumption for reading in month_readings), Decimal("0.00"))
        touched_readings = WaterReading.objects.select_related('lease__unit').filter(id__in=touched_reading_ids)

        for reading in touched_readings:
            try:
                compute_water_reading(
                    reading,
                    total_month_consumption=total_month_consumption,
                    shared_pump_total=billing_settings.shared_pump_total,
                    vat_percent=billing_settings.vat_percent,
                    previous_unpaid_water_amount=previous_unpaid_water_balance(reading.lease, reading_date),
                )
                reading.save()

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
                messages.warning(request, f"Unit {reading.lease.unit.number}: {e}")
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
    settings_month = request.POST.get('settings_month')
    shared_pump_total = request.POST.get('shared_pump_total', '0')
    vat_percent = request.POST.get('vat_percent', '12')
    notes = request.POST.get('notes', '')
    settings_date = None
    
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
        settings_date = datetime.strptime(settings_month, '%Y-%m-%d').date() if settings_month else date(eff_date.year, eff_date.month, 1)
        WaterBillingSettings.objects.update_or_create(
            reading_month=settings_date,
            defaults={
                'shared_pump_total': Decimal(shared_pump_total or '0'),
                'vat_percent': Decimal(vat_percent or '12'),
                'notes': notes,
                'updated_by': request.user,
            }
        )
        
        messages.success(request, f"Water rate set to ₱{rate_value} per m³ effective {eff_date}")
        
    except Exception as e:
        messages.error(request, f"Error setting water rate: {e}")
    
    if settings_date:
        fixed_count, skipped_count, error_count = _recompute_unpaid_water_readings_for_month(
            settings_date,
            request.user,
        )
        messages.info(
            request,
            f"Recomputed {fixed_count} unpaid water reading(s) for shared pump/VAT, "
            f"skipped {skipped_count} paid reading(s)."
        )
        if error_count:
            messages.warning(request, f"{error_count} water reading(s) could not be recomputed.")
        return redirect(f'/admin-portal/water/?month={settings_date.month}&year={settings_date.year}')

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
    readings = list(WaterReading.objects.select_related('lease__unit').filter(reading_month=reading_date))
    billing_settings = get_water_billing_settings_for_month(reading_date)
    total_month_consumption = sum((reading.consumption for reading in readings), Decimal("0.00"))
    
    fixed_count = 0
    skipped_count = 0
    
    for reading in readings:
        try:
            # Skip only when the water portion has already been paid.
            existing_bill = MonthlyBill.objects.filter(
                lease=reading.lease,
                billing_month=reading_date,
            ).first()
            
            if is_water_bill_locked(existing_bill):
                skipped_count += 1
                continue
            
            # Recompute the reading
            compute_water_reading(
                reading,
                total_month_consumption=total_month_consumption,
                shared_pump_total=billing_settings.shared_pump_total,
                vat_percent=billing_settings.vat_percent,
                previous_unpaid_water_amount=previous_unpaid_water_balance(reading.lease, reading_date),
            )
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
