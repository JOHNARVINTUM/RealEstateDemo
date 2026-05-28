from datetime import date, datetime, timedelta, timezone
import logging
import os

from django.conf import settings
from django.db.models import Sum, Q, F, ExpressionWrapper, DecimalField, Exists, OuterRef, Subquery, Count
from django.db.models.functions import Coalesce, TruncMonth
from django.db import transaction
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.urls import reverse
from django.http import JsonResponse, HttpResponse
from django.views.decorators.http import require_http_methods, require_GET
from django.core.paginator import Paginator
from django.utils.timezone import now
import json
from django.utils import timezone
from rentals.models import Lease, Unit, TenantProfile, Notification, TenantRiskClassification, Room, TenantAttachment
from billing.models import MonthlyBill
from billing.services import ensure_bills_since_move_in, set_bill_status, approve_manual_payment, reject_manual_payment, cleanup_duplicate_monthly_bills_for_lease
from payments.models import ManualPayment
from maintenance.models import MaintenanceRequest
from water.models import WaterReading
from accounts.admin_portal_forms import _ordinal


def debug_lease_form(request):
    """Debug view for testing lease form JavaScript"""
    from django.template import loader
    
    # Get available units for testing
    units = Unit.objects.filter(is_active=True)
    
    # Get tenants for testing
    tenants = TenantProfile.objects.select_related('user')
    
    return render(request, 'admin_portal/debug_lease_form.html', {
        'units': units,
        'tenants': tenants
    })

def simple_debug(request):
    """Simple debug view without Django template inheritance"""
    return render(request, 'admin_portal/simple_debug.html')
from announcements.models import Announcement
from maintenance.forms import AdminMaintenanceUpdateForm
from rentals.services import TenantRiskService, repair_historical_move_in_payment

from .admin_portal_forms import TenantProfileForm, AnnouncementForm, LeaseForm
from .admin_portal_forms import TenantProfileEditForm
from .admin_portal_forms import ComprehensiveTenantEditForm
from .admin_portal_forms import UnitForm
from rentals.models import UnitImage
from django.utils import timezone as dj_timezone
from django.contrib import messages
from django.contrib.auth.decorators import user_passes_test

def tenant_has_records(tenant):
    """Check if tenant has any records that should prevent hard delete."""
    user = tenant.user
    return (
        Lease.objects.filter(tenant=user).exists()
        or ManualPayment.objects.filter(user=user).exists()
        or MaintenanceRequest.objects.filter(tenant=user).exists()
        or TenantAttachment.objects.filter(tenant=user).exists()
    )


def deactivate_tenant(tenant):
    """Deactivate tenant: disable login, close active leases, free units."""
    today = date.today()
    user = tenant.user

    # Disable account login
    user.is_active = False
    user.save()

    # Close active leases and free units
    active_leases = Lease.objects.filter(tenant=user, status=Lease.STATUS_ACTIVE)
    for lease in active_leases:
        lease.deactivate(end_date=today)

        unit = lease.unit
        unit.status = "AVAILABLE"
        unit.save()


def admin_required(view_func):
    """
    Decorator to ensure user is authenticated and has ADMIN role
    """
    def check(user):
        return user.is_authenticated and (getattr(user, "role", "") == "ADMIN" or user.is_superuser)
    return user_passes_test(check)(view_func)

logger = logging.getLogger(__name__)


@admin_required
def admin_dashboard(request):
    active_leases = Lease.objects.filter(status=Lease.STATUS_ACTIVE)
    total_tenants = active_leases.values("tenant").distinct().count()
    occupied_units = active_leases.count()
    total_units = Unit.objects.filter(is_active=True).count()
    vacant_units = total_units - occupied_units

    today = timezone.now().date()
    current_year = today.year
    current_month = today.month
    current_month_start = today.replace(day=1)
    start_month = current_month_start
    for _ in range(11):
        start_month = (start_month - timedelta(days=1)).replace(day=1)
    next_month_start = (current_month_start + timedelta(days=32)).replace(day=1)

    expected_monthly_rent = active_leases.aggregate(total=Sum("monthly_rent"))["total"] or 0
    
    # Get expected amounts from current month's bills (all active bills)
    current_month_bills = MonthlyBill.objects.filter(
        billing_month__year=current_year,
        billing_month__month=current_month,
    )
    
    month_bill_totals = current_month_bills.aggregate(
        expected_parking=Sum("parking_fee"),
        expected_water_revenue=Sum("water_amount"),
        expected_penalties=Sum("interest"),
        rent_collected=Sum("rent_paid"),
        water_collected=Sum("water_paid"),
        parking_collected=Sum("parking_paid"),
        interest_collected=Sum("interest", filter=Q(status="PAID")),
    )
    expected_parking = month_bill_totals["expected_parking"] or 0
    expected_water_revenue = month_bill_totals["expected_water_revenue"] or 0
    expected_penalties = month_bill_totals["expected_penalties"] or 0
    rent_collected = month_bill_totals["rent_collected"] or 0
    water_collected = month_bill_totals["water_collected"] or 0
    parking_collected = month_bill_totals["parking_collected"] or 0
    interest_collected = month_bill_totals["interest_collected"] or 0
    
    # ACTUAL COLLECTED this month — use _paid fields to capture partial payments too
    # Current-month collected values already come from month_bill_totals above
    rent_collected = rent_collected
    
    water_collected = water_collected
    
    parking_collected = parking_collected
    
    # Late fees collected (from PAID bills only — interest is zeroed out on payment)
    interest_collected = interest_collected
    
    # Total money received this month
    total_collected = rent_collected + water_collected + parking_collected + interest_collected
    
    # Total expected (rent + parking since both are monthly recurring)
    expected_total_rent = expected_monthly_rent + expected_parking
    
    # Collection rate percentage (based on rent + parking collected vs expected)
    total_rent_collected = rent_collected + parking_collected
    collection_rate = (total_rent_collected / expected_total_rent * 100) if expected_total_rent > 0 else 0
    
    overdue_payments = MonthlyBill.objects.filter(status="UNPAID", due_date__lt=today).count()

    
    monthly_bill_totals = {
        (row["month_bucket"].year, row["month_bucket"].month): row["total"] or 0
        for row in MonthlyBill.objects.filter(
            billing_month__gte=start_month,
            billing_month__lt=next_month_start,
            status="PAID",
        ).annotate(
            month_bucket=TruncMonth("billing_month")
        ).values("month_bucket").annotate(
            total=Sum(
                ExpressionWrapper(
                    F("base_rent") + F("water_amount") + F("parking_fee") + F("interest"),
                    output_field=DecimalField()
                )
            )
        )
    }
    water_usage_totals = {
        (row["month_bucket"].year, row["month_bucket"].month): row["total"] or 0
        for row in WaterReading.objects.filter(
            reading_month__gte=start_month,
            reading_month__lt=next_month_start,
        ).annotate(
            month_bucket=TruncMonth("reading_month")
        ).values("month_bucket").annotate(
            total=Sum("consumption")
        )
    }
    maintenance_totals = {
        (row["month_bucket"].year, row["month_bucket"].month): row["count"] or 0
        for row in MaintenanceRequest.objects.filter(
            created_at__date__gte=start_month,
            created_at__date__lt=next_month_start,
        ).annotate(
            month_bucket=TruncMonth("created_at")
        ).values("month_bucket").annotate(
            count=Count("id")
        )
    }

    # Get monthly rental income data for the past 12 months including current month
    monthly_income_data = []
    water_usage_data = []
    maintenance_trend_data = []
    months_labels = []
    
    for i in range(12):
        # Calculate month date: current month minus i months
        if i == 0:
            # Current month
            month_date = current_month_start
        else:
            # Previous months
            # Go back i months from current month
            month_year = current_month_start.year
            month_month = current_month_start.month - i
            
            # Adjust year if month goes below 1
            while month_month <= 0:
                month_month += 12
                month_year -= 1
            
            month_date = datetime(month_year, month_month, 1).date()
        
        month_key = (month_date.year, month_date.month)
        actual_revenue = monthly_bill_totals.get(month_key, 0)
        expected_revenue = expected_monthly_rent
        
        monthly_income_data.append({
            'month': month_date.strftime('%b %Y'),
            'actual': float(actual_revenue),
            'expected': float(expected_revenue)
        })
        monthly_water_usage = water_usage_totals.get(month_key, 0)
        monthly_maintenance_count = maintenance_totals.get(month_key, 0)

        water_usage_data.append({
            'month': month_date.strftime('%b %Y'),
            'consumption': float(monthly_water_usage)
        })
        maintenance_trend_data.append({
            'month': month_date.strftime('%b %Y'),
            'count': monthly_maintenance_count
        })
        months_labels.append(month_date.strftime('%b'))
    
    # Reverse to show oldest to newest
    monthly_income_data.reverse()
    water_usage_data.reverse()
    maintenance_trend_data.reverse()
    months_labels.reverse()

    # Get notifications for admin only (exclude tenant notifications)
    all_notifications = Notification.objects.filter(
        recipient_type__in=['ADMIN', 'SPECIFIC_USER']
    ).order_by('-created_at')
    unread_notifications = all_notifications.filter(is_read=False)
    notifications = all_notifications[:5]  # Quick panel shows latest admin notifications
    unread_count = unread_notifications.count()

    return render(request, "admin_portal/dashboard.html", {
        "total_tenants": total_tenants,
        "total_units": total_units,
        "occupied_units": occupied_units,
        "vacant_units": max(vacant_units, 0),
        "available_units": max(vacant_units, 0),
        # New clear metrics
        "expected_monthly_rent": expected_total_rent,  # rent + parking
        "rent_collected": total_rent_collected,  # rent + parking combined for collection rate
        "base_rent_collected": rent_collected,  # just base rent for breakdown
        "collection_rate": collection_rate,
        "water_collected": water_collected,
        "parking_collected": parking_collected,
        "interest_collected": interest_collected,
        "total_collected": total_collected,
        # Keep old names for compatibility
        "total_revenue": total_collected,
        "monthly_collected": total_rent_collected,
        "overdue_payments": overdue_payments,
        "notifications": notifications,
        "unread_notifications": unread_notifications,
        "unread_count": unread_count,
        "monthly_income_data": monthly_income_data,
        "water_usage_data": water_usage_data,
        "maintenance_trend_data": maintenance_trend_data,
        "months_labels": months_labels,
        "current_month_str": today.strftime("%Y-%m"),
    })


@admin_required
def admin_tenants(request):
    q = request.GET.get("q", "").strip()
    lease_filter = request.GET.get("lease", "").strip()

    today = timezone.localdate()
    tenants_list = TenantProfile.objects.select_related("user").annotate(
        has_active_lease=Exists(
            Lease.objects.filter(
                tenant=OuterRef("user"),
                start_date__lte=today,
            ).filter(
                Q(end_date__isnull=True) | Q(end_date__gte=today)
            )
        )
    )
    if q:
        tenants_list = tenants_list.filter(
            Q(first_name__icontains=q) |
            Q(last_name__icontains=q) |
            Q(contact_no__icontains=q) |
            Q(user__email__icontains=q) |
            Q(user__username__icontains=q)
        )

    if lease_filter == "active":
        tenants_list = tenants_list.filter(has_active_lease=True)
    elif lease_filter == "none":
        tenants_list = tenants_list.filter(has_active_lease=False)

    tenants_list = tenants_list.order_by("first_name", "last_name")
    
    paginator = Paginator(tenants_list, 10)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    page_user_ids = [tenant.user_id for tenant in page_obj]
    lease_user_ids = set(
        Lease.objects.filter(tenant_id__in=page_user_ids).values_list("tenant_id", flat=True)
    )
    payment_user_ids = set(
        ManualPayment.objects.filter(user_id__in=page_user_ids).values_list("user_id", flat=True)
    )
    maintenance_user_ids = set(
        MaintenanceRequest.objects.filter(tenant_id__in=page_user_ids).values_list("tenant_id", flat=True)
    )
    attachment_user_ids = set(
        TenantAttachment.objects.filter(tenant_id__in=page_user_ids).values_list("tenant_id", flat=True)
    )

    for tenant in page_obj:
        tenant.has_records = tenant.user_id in (
            lease_user_ids | payment_user_ids | maintenance_user_ids | attachment_user_ids
        )

    # Calculate stats for the header
    total_tenants_count = TenantProfile.objects.count()
    active_tenants_count = Lease.objects.filter(status=Lease.STATUS_ACTIVE).values("tenant").distinct().count()
    
    today = timezone.now()
    new_tenants_count = TenantProfile.objects.filter(
        user__date_joined__year=today.year, 
        user__date_joined__month=today.month
    ).count()

    return render(request, "admin_portal/tenants.html", {
        "page_obj": page_obj,
        "q": q,
        "lease_filter": lease_filter,
        "total_tenants_count": total_tenants_count,
        "active_tenants_count": active_tenants_count,
        "new_tenants_count": new_tenants_count,
    })


@admin_required
def admin_tenant_detail(request, tenant_id: int):
    from payments.models import ManualPayment
    tenant = get_object_or_404(TenantProfile.objects.select_related("user"), pk=tenant_id)
    leases = list(
        Lease.objects.select_related("unit", "tenant")
        .filter(tenant=tenant.user)
        .order_by("-start_date")
    )
    attachments = TenantAttachment.objects.filter(tenant=tenant.user).select_related('uploaded_by').order_by('-uploaded_at')
    tenant.has_records = tenant_has_records(tenant)

    # Payment history: all MonthlyBills across all leases
    lease_ids = [lease.id for lease in leases]
    bill_history = MonthlyBill.objects.filter(
        lease_id__in=lease_ids
    ).select_related("lease__unit").order_by("-billing_month")[:24]

    # Manual payment submissions (GCash / Cash)
    manual_payments = ManualPayment.objects.filter(
        user=tenant.user
    ).order_by("-created_at")[:20]

    return render(request, "admin_portal/tenant_detail.html", {
        "tenant": tenant,
        "leases": leases,
        "attachments": attachments,
        "bill_history": bill_history,
        "manual_payments": manual_payments,
    })


@admin_required
def admin_create_tenant_profile(request):
    """
    Admin portal: create a TenantProfile row with auto-generated password and email notification.
    """
    # Check tenant limit: cannot have more tenants than total units
    total_units = Unit.objects.filter(is_active=True).count()
    total_tenants = TenantProfile.objects.count()
    if total_tenants >= total_units:
        messages.error(request, f"Cannot add more tenants. Maximum limit ({total_units} tenants for {total_units} units) reached.")
        return redirect("admin_tenants")
    
    form = TenantProfileForm(request.POST or None, request.FILES or None)

    if request.method == "POST" and form.is_valid():
        try:
            tenant_profile = form.save(uploaded_by=request.user)
            
            # Success message with information about auto-generated password and email
            tenant_name = f"{tenant_profile.first_name} {tenant_profile.last_name}"
            success_message = f"Tenant {tenant_name} has been created successfully! "
            success_message += "An auto-generated password has been created and credentials email has been sent to {tenant_profile.user.email}."
            
            messages.success(request, success_message)
            
            # after creating a tenant, redirect admin to create a lease for that tenant
            try:
                tenant_id = tenant_profile.user.id
                return redirect(f"{reverse('admin_create_lease')}?tenant_id={tenant_id}")
            except Exception as e:
                logger.exception("Failed to redirect to create lease for tenant %s: %s", getattr(tenant_profile.user, 'id', None), e)
                messages.warning(request, "Tenant created but could not prefill lease form. Redirecting to tenants list.")
                return redirect("admin_tenants")
                
        except Exception as e:
            logger.exception("Failed to create tenant profile: %s", e)
            messages.error(request, f"Error creating tenant: {str(e)}")

    recent_tenants = TenantProfile.objects.all().order_by('-id')[:5]
    
    return render(request, "admin_portal/tenant_form.html", {
        "title": "Add Tenant",
        "form": form,
        "back_url": reverse("admin_tenants"),
        "recent_tenants": recent_tenants,
        "help_text": "Password will be automatically generated based on the tenant's name and sent via email."
    })


@admin_required
def admin_units(request):
    """Admin portal: list all units with filtering."""
    status_filter = request.GET.get('status', 'all')
    search_query = request.GET.get('search', '')
    
    # Handle filter logic
    if status_filter == 'MAINTENANCE':
        # Show both MAINTENANCE status units AND inactive units (both count as "Being Fixed")
        from django.db.models import Q
        units = Unit.objects.filter(
            Q(status='MAINTENANCE') | Q(is_active=False)
        ).select_related()
    else:
        units = Unit.objects.filter(is_active=True).select_related()
        # Filter by status
        if status_filter != 'all':
            units = units.filter(status=status_filter)
    
    # Search functionality
    if search_query:
        units = units.filter(
            Q(number__icontains=search_query) |
            Q(unit_type__icontains=search_query) |
            Q(description__icontains=search_query)
        )
    
    from django.core.paginator import Paginator
    
    # Get statistics from ALL active units (not the filtered queryset)
    all_active_units = Unit.objects.filter(is_active=True)
    all_inactive_units = Unit.objects.filter(is_active=False)
    total_units_count = all_active_units.count()
    available_units_count = all_active_units.filter(status='AVAILABLE').count()
    occupied_units_count = all_active_units.filter(status='OCCUPIED').count()
    # Being Fixed includes both MAINTENANCE status AND inactive units
    maintenance_units_count = all_active_units.filter(status='MAINTENANCE').count() + all_inactive_units.count()
    
    # Pagination (6 per page)
    paginator = Paginator(units, 6)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    return render(request, "admin_portal/units.html", {
        'page_obj': page_obj,
        'status_filter': status_filter,
        'search_query': search_query,
        'total_units': total_units_count,
        'available_units': available_units_count,
        'occupied_units': occupied_units_count,
        'maintenance_units': maintenance_units_count,
    })


@admin_required
def admin_unit_detail(request, unit_id):
    """Admin portal: view unit details."""
    unit = get_object_or_404(Unit, id=unit_id, is_active=True)
    current_tenant = unit.get_current_tenant()
    unit_images = unit.get_all_images()
    
    return render(request, "admin_portal/unit_detail.html", {
        'unit': unit,
        'current_tenant': current_tenant,
        'unit_images': unit_images,
        'amenities_list': unit.get_amenities_list(),
    })


@admin_required
def admin_create_unit(request):
    """Admin portal: create a Unit row."""
    if request.method == "POST":
        form = UnitForm(request.POST)
        
        if form.is_valid():
            try:
                unit = form.save(commit=False)
                unit.is_active = True
                unit.save()
                
                # Handle image uploads
                handle_image_uploads(request, unit)
                
                # Create real-time notification for admin
                try:
                    Notification.create_notification(
                        title=f"New Unit Created",
                        message=f"Unit {unit.number} ({unit.get_unit_type_display()}) has been created successfully!",
                        notification_type='UNIT',
                        related_unit=unit
                    )
                except Exception as e:
                    logger.exception(f"Failed to create unit creation notification: {e}")
                
                messages.success(request, f'Unit {unit.number} has been created successfully!')
                return redirect("admin_units")
            except Exception as e:
                messages.error(request, f'Error creating unit: {str(e)}')
                logger.exception("Error creating unit")
        else:
            messages.error(request, 'Please correct the errors below.')
    else:
        form = UnitForm()

    return render(request, "admin_portal/unit_form_with_images.html", {
        "title": "Add Unit",
        "action": "Add",
        "form": form,
        "back_url": reverse("admin_units"),
    })


@admin_required
def admin_edit_unit(request, unit_id):
    """Admin portal: edit a Unit row."""
    unit = get_object_or_404(Unit, id=unit_id, is_active=True)
    
    if request.method == "POST":
        form = UnitForm(request.POST, instance=unit)
        
        if form.is_valid():
            try:
                unit = form.save(commit=False)
                unit.is_active = True
                unit.save()
                
                # Handle image uploads and deletions
                handle_image_uploads(request, unit)
                handle_image_deletions(request, unit)
                
                messages.success(request, f'Unit {unit.number} has been updated successfully!')
                return redirect("admin_unit_detail", unit_id=unit.id)
            except Exception as e:
                messages.error(request, f'Error updating unit: {str(e)}')
                logger.exception("Error updating unit")
        else:
            messages.error(request, 'Please correct the errors below.')
    else:
        form = UnitForm(instance=unit)
    
    return render(request, "admin_portal/unit_form_with_images.html", {
        "title": "Edit Unit",
        "action": "Edit",
        "form": form,
        "back_url": reverse("admin_unit_detail", args=[unit.id]),
        "unit_images": unit.get_all_images(),
    })


@admin_required
def admin_delete_unit(request, unit_id):
    """Admin portal: delete a Unit row (soft delete)."""
    unit = get_object_or_404(Unit, id=unit_id)
    
    if request.method == "POST":
        unit.is_active = False
        unit.save()
        messages.success(request, f'Unit {unit.number} has been deleted successfully!')
        return redirect("admin_units")
    
    return render(request, "admin_portal/confirm.html", {
        "title": "Delete Unit",
        "message": f"Delete unit {unit.number}? This will mark it as inactive but preserve all historical data.",
        "post_url": reverse("admin_delete_unit", args=[unit.id]),
        "back_url": reverse("admin_unit_detail", args=[unit.id]),
    })


@admin_required
def admin_toggle_unit_status(request, unit_id):
    """Admin portal: toggle unit status."""
    unit = get_object_or_404(Unit, id=unit_id, is_active=True)
    
    if request.method == "POST":
        new_status = request.POST.get('status')
        if new_status in ['AVAILABLE', 'OCCUPIED', 'MAINTENANCE', 'RESERVED']:
            unit.status = new_status
            unit.save()
            messages.success(request, f'Unit {unit.number} status changed to {new_status}!')
        
        return redirect("admin_unit_detail", unit_id=unit.id)
    
    return redirect("admin_unit_detail", unit_id=unit.id)


@admin_required
def admin_create_lease(request):
    """
    Admin portal: create a Lease row (linking a tenant to a unit) with enhanced payment scheduling.
    """
    from rentals.services import LeaseSchedulingService
    
    # allow pre-filling tenant via ?tenant_id=... when redirected from tenant creation
    initial = {}
    tenant_id = request.GET.get("tenant_id")
    if tenant_id:
        initial["tenant"] = tenant_id

    form = LeaseForm(request.POST or None, initial=initial)
    schedule_preview = None

    if request.method == "POST":
        if form.is_valid():
            try:
                lease = form.save()
                
                # Create real-time notification for admin about new lease
                try:
                    Notification.create_notification(
                        title=f"New Lease Created",
                        message=f"""Lease created for {lease.tenant.email} in Unit {lease.unit.number}

Lease Details:
• Monthly Rent: ₱{lease.monthly_rent:,.2f}
• Advance Payment: ₱{lease.advance_payment_amount:,.2f} ({lease.advance_months} months)
• Security Deposit: ₱{lease.security_deposit:,.2f}
• Total Move-in Cost: ₱{lease.total_move_in_cost:,.2f}
• Lease Start: {lease.start_date.strftime('%B %d, %Y')}
• First Rent Due: {lease.first_rent_due_date.strftime('%B %d, %Y')}""",
                        notification_type='LEASE',
                        related_tenant=lease.tenant,
                        related_unit=lease.unit
                    )
                except Exception as e:
                    logger.exception(f"Failed to create lease notification: {e}")
                
                # Create enhanced welcome notification for tenant with payment details
                try:
                    tenant_name = lease.tenant.tenantprofile.full_name if hasattr(lease.tenant, 'tenantprofile') else lease.tenant.email
                    welcome_message = f"""Welcome to your new home at REALESTATE360+!

Your lease has been successfully created. Here are your payment details:

Unit Information:
• Unit Number: {lease.unit.number}
• Unit Type: {lease.unit.get_unit_type_display()}
• Floor Level: {lease.unit.floor_level}
• Size: {lease.unit.size_sqm} sqm

Payment Schedule:
• Monthly Rent: ₱{lease.monthly_rent:,.2f}
• Security Deposit: ₱{lease.security_deposit:,.2f} (due on move-in)
• Advance Payment: ₱{lease.advance_payment_amount:,.2f} ({lease.advance_months} months prepaid)
• Total Move-in Cost: ₱{lease.total_move_in_cost:,.2f}
• Lease Start Date: {lease.start_date.strftime('%B %d, %Y')}
• First Regular Rent Due: {lease.first_rent_due_date.strftime('%B %d, %Y')}

Your unit features: {lease.unit.description or 'Modern living space with premium amenities.'}
Amenities included: {lease.unit.amenities or 'Contact admin for full amenities list.'}

Payment Due Dates:
• Rent is due on the {_ordinal(lease.due_day)} of each month
• Your advance payment covers the first {lease.advance_months} months
• Regular rent payments start {lease.first_rent_due_date.strftime('%B %d, %Y')}

You can access your tenant portal to view bills, make payments, and request maintenance.

Welcome aboard! We're excited to have you as part of our community!"""
                    
                    Notification.create_notification(
                        title=f"Welcome to Your New Unit {lease.unit.number}!",
                        message=welcome_message,
                        notification_type='SYSTEM',
                        related_tenant=lease.tenant,
                        related_unit=lease.unit
                    )
                except Exception as e:
                    logger.exception(f"Failed to create welcome notification for tenant: {e}")
                
                # Update unit status to OCCUPIED when lease is created
                try:
                    unit = lease.unit
                    unit.status = 'OCCUPIED'
                    unit.save()
                    logger.info(f"Unit {unit.number} status updated to OCCUPIED for lease {lease.id}")
                except Exception as e:
                    logger.exception(f"Failed to update unit status for lease {lease.id}: {e}")
                    # Don't block lease creation if unit status update fails
                
                # Reset tenant's welcome popup flag so they see the welcome message
                try:
                    from rentals.models import TenantProfile
                    tenant_profile = TenantProfile.objects.get(user=lease.tenant)
                    tenant_profile.has_seen_unit_welcome = False
                    tenant_profile.save()
                    logger.info(f"Reset welcome popup flag for tenant {lease.tenant.email}")
                except Exception as e:
                    logger.exception(f"Failed to reset welcome popup flag for tenant {lease.tenant.email}: {e}")

                # Send lease assignment email to tenant
                try:
                    from rentals.services import send_email_via_resend
                    tenant_name = lease.tenant.tenantprofile.full_name if hasattr(lease.tenant, 'tenantprofile') else lease.tenant.email
                    send_email_via_resend(
                        to_email=lease.tenant.email,
                        subject=f"[REALESTATE360+] Unit {lease.unit.number} Assigned to You",
                        message=(
                            f"Dear {tenant_name},\n\n"
                            f"Your unit has been successfully assigned. Here are your lease details:\n\n"
                            f"  Unit Number:        {lease.unit.number}\n"
                            f"  Unit Type:          {lease.unit.get_unit_type_display()}\n"
                            f"  Monthly Rent:       PHP {lease.monthly_rent:,.2f}\n"
                            f"  Security Deposit:   PHP {lease.security_deposit:,.2f}\n"
                            f"  Contract Deposit:   PHP {lease.contract_deposit:,.2f} ({lease.deposit_multiplier}× monthly rent)\n"
                            f"  Parking Fee:        PHP {lease.parking_fee:,.2f}/mo\n"
                            f"  Total Move-in Due:  PHP {lease.total_move_in_cost:,.2f}\n"
                            f"  Lease Start:        {lease.start_date.strftime('%B %d, %Y')}\n"
                            f"  Rent Due:           Every {lease.due_day} of the month\n\n"
                            f"Move-in Breakdown:\n"
                            f"  1st Month Rent:     PHP {lease.monthly_rent:,.2f}\n"
                            f"  + Security Deposit: PHP {lease.security_deposit:,.2f}\n"
                            f"  + Parking Fee:      PHP {lease.parking_fee:,.2f}\n"
                            f"  = Total:            PHP {lease.total_move_in_cost:,.2f}\n\n"
                            f"You can log in to your tenant portal to view your bills and payment schedule.\n\n"
                            f"Welcome to your new home!\n\n"
                            f"REALESTATE360+ Administration"
                        )
                    )
                except Exception as e:
                    logger.exception(f"Failed to send lease assignment email: {e}")
                
                # Lease is created with status=PENDING_PAYMENT (see LeaseForm.save)
                # DO NOT generate bills yet - will happen after payment
                # DO NOT mark unit occupied yet - will happen after payment
                
                # Send lease creation email (tenant can see pending lease)
                try:
                    tenant_name = lease.tenant.tenantprofile.full_name if hasattr(lease.tenant, 'tenantprofile') else lease.tenant.email
                    from django.core.mail import send_mail
                    send_mail(
                        subject="Your Lease is Pending Activation - REALESTATE360+",
                        message=(
                            f"Hi {tenant_name},\n\n"
                            f"Your lease for Unit {lease.unit.number} has been created and is pending activation.\n"
                            f"Please complete the move-in payment to activate your lease and access your tenant portal.\n\n"
                            f"Lease Details:\n"
                            f"- Unit: {lease.unit.number}\n"
                            f"- Monthly Rent: ₱{lease.monthly_rent:,.2f}\n"
                            f"- Start Date: {lease.start_date}\n"
                            f"- Move-in Cost: ₱{lease.total_move_in_cost:,.2f}\n\n"
                            f"Once payment is confirmed, you'll receive access to your tenant portal.\n\n"
                            f"REALESTATE360+ Administration"
                        ),
                        from_email=getattr(settings, 'DEFAULT_FROM_EMAIL', 'noreply@realestate360.com'),
                        recipient_list=[lease.tenant.email],
                        fail_silently=True,
                    )
                except Exception as e:
                    logger.exception(f"Failed to send pending lease email: {e}")
                
                messages.success(
                    request, 
                    f"Lease created for {lease.tenant.email} – Unit {lease.unit.number}. "
                    f"Status: PENDING PAYMENT. Please complete payment to activate."
                )
                
                # Redirect to payment page for this lease
                return redirect("admin_lease_payment", lease_id=lease.id)
                
            except Exception as e:
                logger.exception(f"Error creating lease: {e}")
                messages.error(request, f'Error creating lease: {str(e)}')
        else:
            messages.error(request, 'Please correct the errors below.')
    else:
        # Generate schedule preview for GET request
        if request.GET.get('preview') == '1':
            # Get sample data for preview
            service = LeaseSchedulingService()
            sample_data = {
                'monthly_rent': 17000,
                'advance_months': 2,
                'security_deposit': 17000,
                'start_date': date.today(),
                'due_day': 5,
            }
            schedule_preview = service.get_payment_schedule_preview(sample_data)

    # Determine back URL: if unit_id is provided, go back to unit detail, else tenants list
    back_url = reverse("admin_tenants")
    u_id = request.GET.get("unit_id")
    if u_id:
        back_url = reverse("admin_unit_detail", args=[u_id])

    return render(request, "admin_portal/lease_form.html", {
        "title": "Add Lease",
        "form": form,
        "back_url": back_url,
        "schedule_preview": schedule_preview,
        "gcash_name": getattr(settings, 'GCASH_NAME', ''),
        "gcash_number": getattr(settings, 'GCASH_NUMBER', ''),
    })


@admin_required
def admin_lease_payment(request, lease_id: int):
    """
    Admin portal: Move-in payment page for pending lease.
    Shows payment options after lease is created but not yet activated.
    """
    from rentals.models import Lease
    
    lease = get_object_or_404(
        Lease.objects.select_related('tenant', 'unit'),
        id=lease_id,
        status=Lease.STATUS_PENDING_PAYMENT
    )
    
    if request.method == "POST":
        payment_method = request.POST.get("payment_method", "")
        
        if payment_method == "CASH":
            # For cash, mark payment received and activate immediately
            from rentals.services import LeaseActivationService
            success, message = LeaseActivationService.activate_lease_after_payment(
                lease_id=lease.id,
                payment_method="CASH",
                payment_reference=f"REF-CASH-MOVEIN-{lease.id}",
                amount=lease.total_move_in_cost
            )
            if success:
                messages.success(request, f"Lease activated successfully! {message}")
                return redirect("admin_tenant_detail", tenant_id=lease.tenant.id)
            else:
                messages.error(request, f"Activation failed: {message}")
        
        elif payment_method == "GCASH":
            # Redirect to manual GCash payment page
            from django.http import HttpResponseRedirect
            return HttpResponseRedirect(
                f"/payments/manual-gcash/?amount={lease.total_move_in_cost}&lease_id={lease.id}&payment_type=move_in"
            )
        
        elif payment_method == "PAYMONGO":
            # Redirect to PayMongo checkout with lease_id
            from django.http import HttpResponseRedirect
            return HttpResponseRedirect(
                f"/payments/paymongo/admin-checkout/?amount={lease.total_move_in_cost}&lease_id={lease.id}&payment_type=move_in"
            )
    
    return render(request, "admin_portal/lease_payment.html", {
        "title": "Lease Payment",
        "lease": lease,
        "total_move_in_cost": lease.total_move_in_cost,
        "back_url": reverse("admin_create_lease"),
    })


@admin_required
def admin_edit_tenant(request, tenant_id: int):
    tenant = get_object_or_404(TenantProfile, pk=tenant_id)
    form = ComprehensiveTenantEditForm(tenant, request.POST or None, request.FILES or None)
    
    if request.method == "POST" and form.is_valid():
        try:
            updated_tenant = form.save(uploaded_by=request.user)
            
            # Create notification about tenant account changes
            try:
                changes_made = []
                if tenant.user.email != form.cleaned_data['email']:
                    changes_made.append("email")
                if tenant.user.username != form.cleaned_data['username']:
                    changes_made.append("username")
                if tenant.user.role != form.cleaned_data['role']:
                    changes_made.append("role")
                if form.cleaned_data.get('new_password'):
                    changes_made.append("password")
                
                if changes_made:
                    from notifications.models import Notification
                    change_list = ", ".join(changes_made)
                    Notification.create_notification(
                        title=f"Tenant Account Updated",
                        message=f"Admin updated {updated_tenant.first_name} {updated_tenant.last_name}'s account: {change_list}",
                        notification_type='SYSTEM',
                        related_tenant=updated_tenant.user
                    )
            except Exception as e:
                logger.exception(f"Failed to create tenant update notification: {e}")
            
            messages.success(request, f'Tenant {updated_tenant.first_name} {updated_tenant.last_name} has been updated successfully!')
            return redirect("admin_tenant_detail", tenant_id=tenant.id)
        except Exception as e:
            messages.error(request, f'Error updating tenant: {str(e)}')
            logger.exception("Error updating tenant")
    
    return render(request, "admin_portal/comprehensive_tenant_edit.html", {
        "title": "Edit Tenant",
        "form": form,
        "tenant": tenant,
        "back_url": reverse("admin_tenant_detail", args=[tenant.id]),
    })


@admin_required
def admin_delete_tenant(request, tenant_id: int):
    """
    Delete tenant with password confirmation and archive options.
    Phase 1: Password verification
    Phase 2: Choose archive or permanent delete
    """
    from rentals.models import ArchivedTenant
    from django.utils import timezone
    import json
    
    tenant = get_object_or_404(TenantProfile.objects.select_related('user'), pk=tenant_id)
    user = tenant.user
    has_records = tenant_has_records(tenant)
    
    # PHASE 2: Process deletion after password verified
    if request.method == "POST" and request.POST.get("phase") == "2":
        # Re-verify password
        admin_password = request.POST.get("admin_password", "").strip()
        if not request.user.check_password(admin_password):
            messages.error(request, "Password verification failed. Action cancelled.")
            return redirect("admin_tenant_detail", tenant_id=tenant.id)
        
        deletion_type = request.POST.get("deletion_type", "")
        deletion_reason = request.POST.get("deletion_reason", "").strip()
        
        # Collect all tenant data for archiving
        tenant_data = {
            'full_name': tenant.full_name,
            'first_name': tenant.first_name,
            'last_name': tenant.last_name,
            'email': user.email,
            'contact_no': tenant.contact_no,
            'created_at': tenant.created_at.isoformat() if tenant.created_at else None,
            'has_records': has_records,
        }
        
        # Collect related records summary
        if has_records:
            leases = list(Lease.objects.filter(tenant=user).values(
                'id', 'unit__number', 'monthly_rent', 'start_date', 'end_date', 'is_active'
            ))
            payments = list(ManualPayment.objects.filter(user=user).values(
                'id', 'amount', 'payment_method', 'status', 'created_at'
            )[:10])  # Last 10 payments
            maintenance = list(MaintenanceRequest.objects.filter(tenant=user).values(
                'id', 'title', 'status', 'created_at'
            )[:10])  # Last 10 requests
            
            tenant_data['records_summary'] = {
                'leases': leases,
                'payments_count': ManualPayment.objects.filter(user=user).count(),
                'payments_sample': payments,
                'maintenance_count': MaintenanceRequest.objects.filter(tenant=user).count(),
                'maintenance_sample': maintenance,
            }
        
        if deletion_type == "ARCHIVE":
            # Archive tenant data and deactivate
            ArchivedTenant.objects.create(
                original_user_id=user.id,
                original_tenant_id=tenant.id,
                email=user.email,
                tenant_data=tenant_data,
                archive_type='DEACTIVATED',
                deleted_by=request.user,
                deletion_reason=deletion_reason,
                can_be_restored=True,
            )
            
            # Deactivate (preserve records, disable login)
            deactivate_tenant(tenant)
            messages.success(
                request, 
                f"✓ Tenant {tenant.full_name} archived and deactivated. "
                f"All records preserved. Unit is now available."
            )
            
        elif deletion_type == "DELETE":
            # Archive then hard delete
            ArchivedTenant.objects.create(
                original_user_id=user.id,
                original_tenant_id=tenant.id,
                email=user.email,
                tenant_data=tenant_data,
                archive_type='DELETED_HARD' if has_records else 'DELETED_SOFT',
                deleted_by=request.user,
                deletion_reason=deletion_reason,
                can_be_restored=not has_records,  # Can only restore if no records
            )
            
            full_name = tenant.full_name
            
            if has_records:
                # Delete all related records
                Lease.objects.filter(tenant=user).delete()
                ManualPayment.objects.filter(user=user).delete()
                MaintenanceRequest.objects.filter(tenant=user).delete()
                TenantAttachment.objects.filter(tenant=user).delete()
            
            # Delete tenant profile and user
            tenant.delete()
            user.delete()
            
            messages.success(
                request,
                f"✓ Tenant {full_name} and all records permanently deleted. "
                f"Archive created for audit trail."
            )
        else:
            messages.error(request, "Invalid deletion type selected.")
            return redirect("admin_tenant_detail", tenant_id=tenant.id)
        
        return redirect("admin_tenants")
    
    # PHASE 1: Password verification
    if request.method == "POST":
        admin_password = request.POST.get("admin_password", "").strip()
        
        # Verify password
        if not request.user.check_password(admin_password):
            return render(request, "admin_portal/confirm_delete_tenant.html", {
                "title": "⚠️ Security Verification Failed",
                "error": "Incorrect password. Please try again.",
                "tenant": tenant,
                "has_records": has_records,
                "phase": 1,
                "post_url": reverse("admin_delete_tenant", args=[tenant.id]),
                "back_url": reverse("admin_tenant_detail", args=[tenant.id]),
            })
        
        # Password verified, show deletion options (Phase 2)
        return render(request, "admin_portal/confirm_delete_tenant.html", {
            "title": "Select Deletion Option",
            "tenant": tenant,
            "has_records": has_records,
            "phase": 2,
            "post_url": reverse("admin_delete_tenant", args=[tenant.id]),
            "back_url": reverse("admin_tenant_detail", args=[tenant.id]),
        })
    
    # GET: Show password verification form (Phase 1)
    return render(request, "admin_portal/confirm_delete_tenant.html", {
        "title": "⚠️ Security Verification Required",
        "message": (
            f"You are attempting to delete tenant: {tenant.full_name}\n\n"
            f"For security, please enter your admin password to continue. "
            f"You will then be able to choose between archiving or permanent deletion."
        ),
        "tenant": tenant,
        "has_records": has_records,
        "phase": 1,
        "post_url": reverse("admin_delete_tenant", args=[tenant.id]),
        "back_url": reverse("admin_tenant_detail", args=[tenant.id]),
    })


@admin_required
def admin_edit_lease(request, lease_id: int):
    lease = get_object_or_404(Lease, pk=lease_id)
    form = LeaseForm(request.POST or None, instance=lease)
    if request.method == "POST" and form.is_valid():
        lease = form.save()
        try:
            ensure_bills_since_move_in(lease)
            removed_duplicates = cleanup_duplicate_monthly_bills_for_lease(lease)
            if removed_duplicates:
                messages.info(request, f"Cleaned up {removed_duplicates} duplicate historical bill record{'s' if removed_duplicates != 1 else ''} for this lease.")
        except Exception:
            logger.exception("ensure_bills_since_move_in failed while editing lease id %s", getattr(lease, 'id', None))
            messages.warning(request, "Failed to update billing rows; please regenerate bills if needed.")
        return redirect("admin_tenant_detail", tenant_id=lease.tenant.tenantprofile.id if hasattr(lease.tenant, 'tenantprofile') else lease.tenant.id)
    return render(request, "admin_portal/lease_form.html", {
        "title": "Edit Lease",
        "form": form,
        "lease": lease,
        "back_url": reverse("admin_tenants"),
        "schedule_preview": None,
        "gcash_name": getattr(settings, 'GCASH_NAME', ''),
        "gcash_number": getattr(settings, 'GCASH_NUMBER', ''),
    })


@admin_required
def admin_delete_lease(request, lease_id: int):
    lease = get_object_or_404(Lease, pk=lease_id)
    if request.method == "POST":
        unit = lease.unit
        unit_number = unit.number
        lease.delete()
        unit.status = "AVAILABLE"
        unit.save(update_fields=["status"])
        messages.success(request, f"Lease deleted and unit {unit_number} is now available.")
        return redirect("admin_tenants")
    return render(request, "admin_portal/confirm.html", {
        "title": "Delete Lease",
        "message": f"Delete lease for unit {lease.unit.number}? This cannot be undone.",
        "post_url": reverse("admin_delete_lease", args=[lease.id]),
        "back_url": reverse("admin_tenants"),
    })


@admin_required
def admin_update_maintenance(request, req_id: int):
    req = get_object_or_404(MaintenanceRequest, pk=req_id)
    if request.method == "POST":
        form = AdminMaintenanceUpdateForm(request.POST, instance=req)
        if form.is_valid():
            updated = form.save(commit=False)
            old_status = req.status
            if updated.status == "RESOLVED" and not req.resolved_at:
                updated.resolved_at = dj_timezone.now()
            if updated.status != "RESOLVED":
                updated.resolved_at = None
            updated.save()

            if updated.status != old_status:
                try:
                    from rentals.services import send_email_via_resend
                    status_label = dict(req.STATUS_CHOICES).get(updated.status, updated.status)
                    tenant_name = req.tenant.email
                    if hasattr(req.tenant, 'tenantprofile'):
                        tenant_name = req.tenant.tenantprofile.full_name
                    unit_number = req.lease.unit.number if req.lease else 'N/A'
                    fixed_by_line = f"  Fixed By:    {updated.fixed_by}\n" if updated.fixed_by else ""
                    send_email_via_resend(
                        to_email=req.tenant.email,
                        subject=f"[REALESTATE360+] Maintenance Request Update – {req.title}",
                        message=(
                            f"Dear {tenant_name},\n\n"
                            f"Your maintenance request has been updated.\n\n"
                            f"  Request:     {req.title}\n"
                            f"  Category:    {req.get_category_display()}\n"
                            f"  Unit:        {unit_number}\n"
                            f"  New Status:  {status_label}\n"
                            f"{fixed_by_line}"
                            f"\n"
                            f"{'Your issue has been resolved. Thank you for your patience!' if updated.status == 'RESOLVED' else 'Our team is working on your request.'}\n\n"
                            f"You can view the status in your tenant portal.\n\n"
                            f"REALESTATE360+ Administration"
                        )
                    )
                except Exception as e:
                    logger.exception(f"Failed to send maintenance update email: {e}")

            return redirect("admin_maintenance")
    else:
        form = AdminMaintenanceUpdateForm(instance=req)

    return render(request, "admin_portal/maintenance_update.html", {
        "title": "Resolve Maintenance Issue",
        "form": form,
        "req": req,
        "back_url": reverse("admin_maintenance"),
    })


@admin_required
def admin_edit_announcement(request, ann_id: int):
    ann = get_object_or_404(Announcement, pk=ann_id)
    form = AnnouncementForm(request.POST or None, instance=ann)
    if request.method == "POST" and form.is_valid():
        obj = form.save(commit=False)
        obj.uploaded_by = request.user
        obj.save()
        return redirect("admin_announcements")
    recent_items = Announcement.objects.all().order_by("-created_at")[:3]
    return render(request, "admin_portal/announcement_form.html", {
        "title": "Edit Announcement",
        "form": form,
        "ann": ann,
        "recent_items": recent_items,
        "back_url": reverse("admin_announcements"),
    })


@admin_required
def admin_delete_announcement(request, ann_id: int):
    ann = get_object_or_404(Announcement, pk=ann_id)
    if request.method == "POST":
        ann.delete()
        return redirect("admin_announcements")
    return render(request, "admin_portal/confirm.html", {
        "title": "Delete Announcement",
        "message": f"Delete announcement {ann.title}?",
        "post_url": reverse("admin_delete_announcement", args=[ann.id]),
        "back_url": reverse("admin_announcements"),
    })




@admin_required
def admin_tenant_risk(request):
    """Tenant Risk Classification view"""
    q = request.GET.get("q", "").strip()
    risk_filter = request.GET.get("risk", "").strip()
    
    # Get all tenant risk classifications
    risk_classifications = TenantRiskClassification.objects.select_related('tenant').all()
    
    # Apply filters
    if risk_filter in ("LOW", "MEDIUM", "HIGH"):
        risk_classifications = risk_classifications.filter(risk_level=risk_filter)
    
    if q:
        risk_classifications = risk_classifications.filter(
            Q(tenant__email__icontains=q) |
            Q(tenant__tenantprofile__first_name__icontains=q) |
            Q(tenant__tenantprofile__last_name__icontains=q)
        )

    # Sorting
    sort = request.GET.get("sort", "score_desc").strip()
    if sort == "score_asc":
        risk_classifications = risk_classifications.order_by("payment_score")
    else:
        risk_classifications = risk_classifications.order_by("-payment_score")
    
    # Pagination
    paginator = Paginator(risk_classifications, 10)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    # Calculate statistics
    total_tenants = risk_classifications.count()
    low_risk_count = TenantRiskClassification.objects.filter(risk_level='LOW').count()
    medium_risk_count = TenantRiskClassification.objects.filter(risk_level='MEDIUM').count()
    high_risk_count = TenantRiskClassification.objects.filter(risk_level='HIGH').count()
    new_tenant_count = TenantRiskClassification.objects.filter(is_new_tenant=True).count()
    rf_metrics = None
    try:
        from accounts.ml.tenant_risk_model import load_model_metrics
        rf_metrics = load_model_metrics()
    except Exception:
        rf_metrics = None
    
    context = {
        'page_obj': page_obj,
        'q': q,
        'risk': risk_filter,
        'sort': sort,
        'total_tenants': total_tenants,
        'low_risk_count': low_risk_count,
        'medium_risk_count': medium_risk_count,
        'high_risk_count': high_risk_count,
        'new_tenant_count': new_tenant_count,
        'rf_metrics': rf_metrics,
    }
    
    return render(request, "admin_portal/tenant_risk.html", context)


@admin_required
def admin_update_tenant_risks(request):
    """Update all tenant risk classifications"""
    if request.method == 'POST':
        try:
            updated_count = TenantRiskService.update_all_tenant_risks()
            messages.success(request, f'Successfully updated risk classifications for {updated_count} tenants.')
        except Exception as e:
            messages.error(request, f'Error updating risk classifications: {e}')
    
    return redirect('admin_tenant_risk')


@admin_required
def admin_maintenance(request):
    q = request.GET.get("q", "").strip()
    status = request.GET.get("status", "").strip()
    priority = request.GET.get("priority", "").strip()

    reqs = MaintenanceRequest.objects.select_related("lease", "lease__unit", "lease__tenant")

    if status:
        reqs = reqs.filter(status=status)
        
    if priority:
        reqs = reqs.filter(priority=priority)

    if q:
        reqs = reqs.filter(
            Q(lease__tenant__email__icontains=q) |
            Q(lease__unit__number__icontains=q) |
            Q(description__icontains=q)
        )

    reqs = reqs.order_by("-created_at")

    # Calculate statistics
    all_reqs = MaintenanceRequest.objects.all()
    if q:
        all_reqs = all_reqs.filter(
            Q(lease__tenant__email__icontains=q) |
            Q(lease__unit__number__icontains=q) |
            Q(description__icontains=q)
        )
    
    total_count = all_reqs.count()
    pending_count = all_reqs.filter(status="PENDING").count()
    in_progress_count = all_reqs.filter(status="IN_PROGRESS").count()
    resolved_count = all_reqs.filter(status="RESOLVED").count()

    # Pagination (10 items per page)
    paginator = Paginator(reqs, 10)
    page_number = request.GET.get("page")
    page_obj = paginator.get_page(page_number)

    try:
        from accounts.ml.maintenance_nlp import load_metrics
        nlp_metrics = load_metrics()
    except Exception:
        nlp_metrics = None

    return render(request, "admin_portal/maintenance.html", {
        "page_obj": page_obj,
        "q": q,
        "status": status,
        "priority": priority,
        "total_count": total_count,
        "pending_count": pending_count,
        "in_progress_count": in_progress_count,
        "resolved_count": resolved_count,
        "nlp_metrics": nlp_metrics,
    })


@admin_required
def admin_announcements(request):
    q = request.GET.get("q", "").strip()
    items = Announcement.objects.all()

    # FIX: model field is "body", not "content"
    if q:
        items = items.filter(Q(title__icontains=q) | Q(body__icontains=q))

    items = items.order_by("-created_at")
    
    # Calculate statistics
    total_count = Announcement.objects.count()
    active_count = Announcement.objects.filter(is_active=True).count()
    
    from django.utils import timezone
    now = timezone.now()
    this_month_count = Announcement.objects.filter(
        created_at__year=now.year, 
        created_at__month=now.month
    ).count()

    return render(request, "admin_portal/announcements.html", {
        "items": items, 
        "q": q,
        "total_count": total_count,
        "active_count": active_count,
        "this_month_count": this_month_count
    })


@admin_required
def admin_create_announcement(request):
    form = AnnouncementForm(request.POST or None)

    if request.method == "POST" and form.is_valid():
        form.save(user=request.user)  # uses your custom save(user=...)
        return redirect("admin_announcements")

    recent_items = Announcement.objects.all().order_by("-created_at")[:3]
    return render(request, "admin_portal/announcement_form.html", {
        "title": "Create Announcement",
        "form": form,
        "recent_items": recent_items,
        "back_url": reverse("admin_announcements"),
    })


@admin_required
@require_http_methods(["GET"])
def api_get_unit_data(request, unit_number):
    """
    API endpoint to get unit data for automatic price population.
    Requires admin authentication.
    """
    try:
        unit = Unit.objects.get(number=unit_number.upper(), is_active=True)
        data = {
            'success': True,
            'unit': {
                'id': unit.id,
                'number': unit.number,
                'unit_type': unit.unit_type,
                'floor_level': unit.floor_level,
                'monthly_rent': str(unit.monthly_rent),
                'status': unit.status,
                'description': unit.description or '',
                'amenities': unit.amenities or ''
            }
        }
        return JsonResponse(data)
    except Unit.DoesNotExist:
        return JsonResponse({
            'success': False,
            'error': f'Unit {unit_number} not found'
        }, status=404)
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)


@admin_required
@require_http_methods(["GET"])
def api_get_unit_data_by_id(request, unit_id):
    """
    API endpoint to get unit data by ID for lease forms.
    Requires admin authentication.
    """
    try:
        unit = Unit.objects.get(id=unit_id, is_active=True)
        data = {
            'success': True,
            'unit': {
                'id': unit.id,
                'number': unit.number,
                'unit_type': unit.unit_type,
                'floor_level': unit.floor_level,
                'monthly_rent': str(unit.monthly_rent),
                'status': unit.status,
                'description': unit.description or '',
                'amenities': unit.amenities or ''
            }
        }
        return JsonResponse(data)
    except Unit.DoesNotExist:
        return JsonResponse({
            'success': False,
            'error': f'Unit with ID {unit_id} not found'
        }, status=404)
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)


@admin_required
def admin_rooms(request):
    """Admin portal: list all rooms with filtering."""
    status_filter = request.GET.get('status', 'all')
    search_query = request.GET.get('search', '')
    
    rooms = Room.objects.all()
    
    # Filter by status
    if status_filter != 'all':
        rooms = rooms.filter(status=status_filter)
    
    # Search functionality
    if search_query:
        rooms = rooms.filter(
            Q(name__icontains=search_query) |
            Q(description__icontains=search_query)
        )
    
    # Get statistics
    total_rooms = rooms.count()
    available_rooms = rooms.filter(status='AVAILABLE').count()
    occupied_rooms = rooms.filter(status='OCCUPIED').count()
    maintenance_rooms = rooms.filter(status='MAINTENANCE').count()
    
    # Pagination
    paginator = Paginator(rooms, 12)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    return render(request, "admin_portal/rooms.html", {
        'page_obj': page_obj,
        'status_filter': status_filter,
        'search_query': search_query,
        'total_rooms': total_rooms,
        'available_rooms': available_rooms,
        'occupied_rooms': occupied_rooms,
        'maintenance_rooms': maintenance_rooms,
    })


@admin_required
def admin_room_detail(request, room_id):
    """Admin portal: view room details."""
    room = get_object_or_404(Room, id=room_id)
    
    return render(request, "admin_portal/room_detail.html", {
        'room': room,
    })


def handle_image_uploads(request, unit):
    """Handle image uploads for a unit"""
    # Get uploaded files directly from request.FILES
    images = request.FILES.getlist('images')
    
    for i, image_file in enumerate(images):
        if image_file:
            # Get caption from form data
            caption_key = f'image_caption_{i}'
            caption = request.POST.get(caption_key, '')
            
            # Check if this should be primary image
            primary_image_value = request.POST.get('primary_image')
            is_primary = primary_image_value == f'new_{i}'
            
            # Create UnitImage instance
            unit_image = UnitImage(
                unit=unit,
                image=image_file,
                caption=caption,
                is_primary=is_primary,
                order=i
            )
            unit_image.save()


def handle_image_deletions(request, unit):
    """Handle image deletions for a unit"""
    deleted_images = request.POST.get('deleted_images', '')
    if deleted_images:
        deleted_image_ids = [int(id_str) for id_str in deleted_images.split(',') if id_str.strip().isdigit()]
        
        # Delete the specified images
        UnitImage.objects.filter(id__in=deleted_image_ids, unit=unit).delete()
    
    # Handle caption updates for existing images
    for key, value in request.POST.items():
        if key.startswith('caption_') and value:
            try:
                image_id = int(key.replace('caption_', ''))
                unit_image = UnitImage.objects.get(id=image_id, unit=unit)
                unit_image.caption = value
                unit_image.save()
            except (ValueError, UnitImage.DoesNotExist):
                continue
    
    # Handle primary image selection
    primary_image_id = request.POST.get('primary_image')
    if primary_image_id:
        try:
            # Remove primary flag from all images
            UnitImage.objects.filter(unit=unit).update(is_primary=False)
            
            # Set primary flag on selected image
            unit_image = UnitImage.objects.get(id=int(primary_image_id), unit=unit)
            unit_image.is_primary = True
            unit_image.save()
        except (ValueError, UnitImage.DoesNotExist):
            pass


@admin_required
def admin_tenant_attachments(request, tenant_id: int):
    """Admin portal: view and manage tenant attachments with image preview"""
    tenant = get_object_or_404(TenantProfile.objects.select_related("user"), pk=tenant_id)
    attachments = TenantAttachment.objects.filter(tenant=tenant.user).select_related('uploaded_by').order_by('-uploaded_at')
    
    return render(request, "admin_portal/tenant_attachments.html", {
        "tenant": tenant,
        "attachments": attachments,
    })


@admin_required
@require_GET
def admin_view_attachment(request, attachment_id: int):
    """Admin portal: view attachment file with image preview support"""
    attachment = get_object_or_404(TenantAttachment, pk=attachment_id)
    
    if not attachment.file:
        return HttpResponse("File not found", status=404)
    
    # Serve the file for download or preview
    response = HttpResponse(attachment.file.read(), content_type='application/octet-stream')
    
    # Set appropriate content type for images
    if attachment.is_image:
        response['Content-Type'] = f'image/{attachment.file_extension[1:]}'
    elif attachment.is_pdf:
        response['Content-Type'] = 'application/pdf'
    
    # Set filename for download
    response['Content-Disposition'] = f'inline; filename="{attachment.filename}"'
    
    return response


@admin_required
def admin_delete_attachment(request, attachment_id: int):
    """Admin portal: delete tenant attachment"""
    attachment = get_object_or_404(TenantAttachment, pk=attachment_id)
    tenant_id = attachment.tenant.tenantprofile.id
    
    if request.method == "POST":
        # Delete the file and the attachment record
        if attachment.file:
            attachment.file.delete()
        attachment.delete()
        messages.success(request, f"Attachment '{attachment.filename}' has been deleted successfully.")
        return redirect("admin_tenant_attachments", tenant_id=tenant_id)
    
    return render(request, "admin_portal/confirm.html", {
        "title": "Delete Attachment",
        "message": f"Delete attachment '{attachment.filename}'? This cannot be undone.",
        "post_url": reverse("admin_delete_attachment", args=[attachment.id]),
        "back_url": reverse("admin_tenant_attachments", args=[tenant_id]),
    })


