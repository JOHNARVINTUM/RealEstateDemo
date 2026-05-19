from datetime import date, datetime, timedelta, timezone
import logging
import os

from django.conf import settings
from django.db.models import Sum, Q, F, ExpressionWrapper, DecimalField, Exists, OuterRef
from django.db import transaction
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.urls import reverse
from django.db.models import Q
from django.http import JsonResponse, HttpResponse
from django.views.decorators.http import require_http_methods, require_GET
from django.core.paginator import Paginator
from django.utils.timezone import now
import json
from django.utils import timezone
from rentals.models import Lease, Unit, TenantProfile, Notification, TenantRiskClassification, Room, TenantAttachment
from billing.models import MonthlyBill
from billing.services import ensure_bills_since_move_in, set_bill_status, approve_manual_payment, reject_manual_payment
from payments.models import ManualPayment
from maintenance.models import MaintenanceRequest
from water.models import WaterReading


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
from rentals.services import TenantRiskService

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
    active_leases = Lease.objects.filter(tenant=user, is_active=True)
    for lease in active_leases:
        lease.is_active = False
        if not lease.end_date:
            lease.end_date = today
        lease.save()

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
    total_tenants = Lease.objects.filter(is_active=True).values("tenant").distinct().count()
    occupied_units = Lease.objects.filter(is_active=True).count()
    vacant_units = Unit.objects.filter(is_active=True).count() - occupied_units

    today = timezone.now().date()
    # Billed This Month = total collected from PAID bills this month
    total_revenue = (
        MonthlyBill.objects.filter(
            billing_month__year=today.year,
            billing_month__month=today.month,
            status="PAID",
        )
        .aggregate(
            total=Sum(
                ExpressionWrapper(F("base_rent") + F("water_amount") + F("parking_fee") + F("interest"),
                output_field=DecimalField()
                )
            )
        )["total"] or 0
    )
    # Monthly collected is ALL cash received this month.
    monthly_collected = (
        ManualPayment.objects.filter(status="APPROVED", created_at__year=today.year, created_at__month=today.month)
        .aggregate(total=Sum("amount"))["total"] or 0
    )
    overdue_payments = MonthlyBill.objects.filter(status="UNPAID", due_date__lt=today).count()

    
    # Get monthly rental income data for the past 12 months including current month
    monthly_income_data = []
    water_usage_data = []
    maintenance_trend_data = []
    months_labels = []
    
    # Calculate months from 11 months ago to current month (inclusive)
    current_month_start = today.replace(day=1)
    
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
        
        # Get monthly revenue (rent + water + parking + interest) for PAID bills in this billing month
        actual_revenue = (
            MonthlyBill.objects.filter(
                billing_month__year=month_date.year,
                billing_month__month=month_date.month,
                status="PAID"
            ).aggregate(
                total=Sum(
                    ExpressionWrapper(F("base_rent") + F("water_amount") + F("parking_fee") + F("interest"),
                    output_field=DecimalField()
                    )
                )
            )["total"] or 0
        )
        
        # Get expected revenue from active leases
        expected_revenue = (
            Lease.objects.filter(is_active=True)
            .aggregate(total=Sum("monthly_rent"))["total"] or 0
        )
        
        monthly_income_data.append({
            'month': month_date.strftime('%b %Y'),
            'actual': float(actual_revenue),
            'expected': float(expected_revenue)
        })
        monthly_water_usage = (
            WaterReading.objects.filter(
                reading_month__year=month_date.year,
                reading_month__month=month_date.month
            ).aggregate(total=Sum("consumption"))["total"] or 0
        )
        monthly_maintenance_count = MaintenanceRequest.objects.filter(
            created_at__year=month_date.year,
            created_at__month=month_date.month
        ).count()

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

    # Get notifications for admin (all notifications, not just user-specific)
    all_notifications = Notification.objects.all().order_by('-created_at')
    notifications = all_notifications[:5]
    unread_notifications = all_notifications.filter(is_read=False)
    unread_count = unread_notifications.count()

    return render(request, "admin_portal/dashboard.html", {
        "total_tenants": total_tenants,
        "occupied_units": occupied_units,
        "vacant_units": max(vacant_units, 0),
        "available_units": max(vacant_units, 0),
        "total_revenue": total_revenue,
        "monthly_collected": monthly_collected,
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

    tenants_list = TenantProfile.objects.select_related("user").annotate(
        has_active_lease=Exists(
            Lease.objects.filter(tenant=OuterRef("user"), is_active=True)
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

    # Add has_records flag to each tenant in current page
    for tenant in page_obj:
        tenant.has_records = tenant_has_records(tenant)

    # Calculate stats for the header
    total_tenants_count = TenantProfile.objects.count()
    active_tenants_count = Lease.objects.filter(is_active=True).values("tenant").distinct().count()
    
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
    tenant = get_object_or_404(TenantProfile.objects.select_related("user"), pk=tenant_id)
    leases = Lease.objects.select_related("unit", "tenant").filter(tenant=tenant.user).order_by("-start_date")
    attachments = TenantAttachment.objects.filter(tenant=tenant.user).select_related('uploaded_by').order_by('-uploaded_at')
    tenant.has_records = tenant_has_records(tenant)
    return render(request, "admin_portal/tenant_detail.html", {"tenant": tenant, "leases": leases, "attachments": attachments})


@admin_required
def admin_create_tenant_profile(request):
    """
    Admin portal: create a TenantProfile row with auto-generated password and email notification.
    """
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
    
    # Get statistics (before pagination)
    total_units_count = units.count()
    available_units_count = units.filter(status='AVAILABLE').count()
    occupied_units_count = units.filter(status='OCCUPIED').count()
    maintenance_units_count = units.filter(status='MAINTENANCE').count()

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
• Rent is due on the {lease.due_day} of each month
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
                
                # create initial monthly bill rows from move-in until today
                try:
                    ensure_bills_since_move_in(lease)
                except Exception:
                    # don't block creation if billing generation fails; admin can regenerate later
                    logger.exception("ensure_bills_since_move_in failed for lease id %s", getattr(lease, 'id', None))
                    messages.warning(request, "Failed to generate initial bills; you can regenerate later.")
                
                # Create move-in payment record and mark first month bill as PAID
                try:
                    from payments.models import ManualPayment
                    from billing.services import set_bill_status
                    from django.utils import timezone as dj_tz
                    move_in_method = form.cleaned_data.get('move_in_payment_method', 'GCASH')
                    move_in_ref = form.cleaned_data.get('move_in_reference_code', '').strip()
                    if move_in_method == 'CASH' and not move_in_ref:
                        move_in_ref = f'REF-CASH-MOVEIN-{lease.id}'

                    # Get the first month's bill (billing_month = start month)
                    from billing.services import month_start
                    first_bill_month = month_start(lease.start_date)
                    first_bill = MonthlyBill.objects.filter(
                        lease=lease,
                        billing_month=first_bill_month,
                    ).first()

                    # Mark it PAID with the move-in reference
                    if first_bill:
                        set_bill_status(
                            first_bill,
                            status="PAID",
                            payment_reference=move_in_ref,
                            paid_at=dj_tz.now(),
                        )
                        bill_ids_str = str(first_bill.id)
                    else:
                        bill_ids_str = ''

                    ManualPayment.objects.create(
                        user=lease.tenant,
                        payment_type='move_in',
                        payment_method=move_in_method,
                        amount=lease.total_move_in_cost,
                        reference_code=move_in_ref,
                        bill_ids=bill_ids_str,
                        status='APPROVED',
                    )
                except Exception as e:
                    logger.exception(f'Failed to create move-in payment record: {e}')
                    messages.warning(request, 'Lease created but failed to record move-in payment.')
                
                tenant_name = lease.tenant.tenantprofile.full_name if hasattr(lease.tenant, 'tenantprofile') else lease.tenant.email
                messages.success(request, f"Lease created successfully for {tenant_name} – Unit {lease.unit.number}. A confirmation email with their payment schedule has been sent.")
                return redirect("admin_tenants")
                
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
    tenant = get_object_or_404(TenantProfile, pk=tenant_id)
    has_records = tenant_has_records(tenant)

    if request.method == "POST":
        if has_records:
            # Deactivate: preserve all history
            deactivate_tenant(tenant)
            messages.success(request, f"Tenant {tenant.full_name} has been deactivated. Their history is preserved and the unit is now available.")
        else:
            # Hard delete: no records to preserve
            user = tenant.user
            tenant.delete()
            user.delete()
            messages.success(request, f"Tenant {tenant.full_name} has been permanently deleted.")
        return redirect("admin_tenants")

    # Determine action based on records
    if has_records:
        title = "Deactivate Tenant"
        message = (
            f"Deactivate tenant {tenant.full_name}?\n\n"
            f"This tenant has existing records (leases, payments, or maintenance requests) "
            f"and cannot be permanently deleted.\n\n"
            f"Deactivation will:\n"
            f"• Disable login access for this tenant\n"
            f"• Close any active leases\n"
            f"• Make the occupied unit available\n"
            f"• Preserve all historical records (payments, bills, maintenance)"
        )
    else:
        title = "Delete Tenant"
        message = (
            f"Delete tenant {tenant.full_name}?\n\n"
            f"This tenant has no records. This action will permanently remove the tenant account.\n\n"
            f"This cannot be undone."
        )

    return render(request, "admin_portal/confirm.html", {
        "title": title,
        "message": message,
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
        except Exception:
            logger.exception("ensure_bills_since_move_in failed while editing lease id %s", getattr(lease, 'id', None))
            messages.warning(request, "Failed to update billing rows; please regenerate bills if needed.")
        return redirect("admin_tenant_detail", tenant_id=lease.tenant.tenantprofile.id if hasattr(lease.tenant, 'tenantprofile') else lease.tenant.id)
    return render(request, "admin_portal/lease_form.html", {
        "title": "Edit Lease",
        "form": form,
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
def admin_mark_bill_paid(request, bill_id: int):
    bill = get_object_or_404(MonthlyBill, pk=bill_id)
    if request.method == "POST":
        set_bill_status(bill, status="PAID", paid_at=dj_timezone.now())
        return redirect("admin_billing")
    return render(request, "admin_portal/confirm.html", {
        "title": "Mark Bill Paid",
        "message": f"Mark bill {bill.id} as PAID?",
        "post_url": reverse("admin_mark_bill_paid", args=[bill.id]),
        "back_url": reverse("admin_billing"),
    })


@admin_required
def admin_mark_bill_unpaid(request, bill_id: int):
    bill = get_object_or_404(MonthlyBill, pk=bill_id)
    if request.method == "POST":
        set_bill_status(bill, status="UNPAID")
        return redirect("admin_billing")
    return render(request, "admin_portal/confirm.html", {
        "title": "Mark Bill Unpaid",
        "message": f"Mark bill {bill.id} as UNPAID?",
        "post_url": reverse("admin_mark_bill_unpaid", args=[bill.id]),
        "back_url": reverse("admin_billing"),
    })


@admin_required
def admin_approve_payment(request, payment_id: int):
    p = get_object_or_404(ManualPayment, pk=payment_id)
    if request.method == "POST":
        try:
            approve_manual_payment(p)
            messages.success(request, f"Payment {p.reference_code} approved successfully.")

            try:
                from rentals.services import send_email_via_resend
                tenant_name = p.user.email
                if hasattr(p.user, 'tenantprofile'):
                    tenant_name = p.user.tenantprofile.full_name
                payment_type_label = {'full': 'Full Payment', 'rent_only': 'Rent Only', 'water_only': 'Water Only'}.get(p.payment_type, 'Payment')
                send_email_via_resend(
                    to_email=p.user.email,
                    subject="[REALESTATE360+] Payment Approved – Receipt Confirmation",
                    message=(
                        f"Dear {tenant_name},\n\n"
                        f"Your payment has been approved and recorded.\n\n"
                        f"  Reference No.: {p.reference_code}\n"
                        f"  Payment Type:  {payment_type_label}\n"
                        f"  Amount:        PHP {p.amount:,.2f}\n"
                        f"  Method:        {p.get_payment_method_display() if hasattr(p, 'get_payment_method_display') else p.payment_method}\n"
                        f"  Status:        APPROVED\n\n"
                        f"Your billing statement has been updated. You can view your payment history in your tenant portal.\n\n"
                        f"Thank you for your payment!\n\n"
                        f"REALESTATE360+ Administration"
                    )
                )
            except Exception as e:
                logger.exception(f"Failed to send payment confirmation email: {e}")

        except Exception as e:
            messages.error(request, f"Error approving payment: {e}")
        return redirect("admin_payments")
    return render(request, "admin_portal/confirm.html", {
        "title": "Approve Payment",
        "message": f"Approve payment {p.reference_code} by {p.user.email}?",
        "post_url": reverse("admin_approve_payment", args=[p.id]),
        "back_url": reverse("admin_payments"),
    })


@admin_required
def admin_reject_payment(request, payment_id: int):
    p = get_object_or_404(ManualPayment, pk=payment_id)
    if request.method == "POST":
        reject_manual_payment(p)
        messages.success(request, f"Payment {p.reference_code} rejected.")
        return redirect("admin_payments")
    return render(request, "admin_portal/confirm.html", {
        "title": "Reject Payment",
        "message": f"Reject payment {p.reference_code} by {p.user.email}?",
        "post_url": reverse("admin_reject_payment", args=[p.id]),
        "back_url": reverse("admin_payments"),
    })


@admin_required
def admin_confirm_schedule(request, payment_id: int):
    """Confirm F2F cash payment schedule - notifies tenant that time is confirmed"""
    p = get_object_or_404(ManualPayment, pk=payment_id)
    if request.method == "POST":
        p.schedule_confirmed = True
        p.save(update_fields=["schedule_confirmed"])
        
        # Notify tenant that schedule is confirmed
        try:
            from rentals.models import Notification
            schedule_info = f"on {p.preferred_date.strftime('%B %d, %Y')}" if p.preferred_date else ""
            if p.preferred_time:
                schedule_info += f" at {p.preferred_time.strftime('%I:%M %p')}"
            
            Notification.create_tenant_notification(
                title="Cash Payment Appointment Confirmed",
                message=f"Your face-to-face cash payment appointment has been confirmed.\n\nAmount: ₱{p.amount:,.2f}\nScheduled: {schedule_info}\n\nPlease bring the exact amount. See you then!",
                notification_type='PAYMENT',
                tenant_user=p.user
            )
        except Exception as e:
            logger.exception(f"Failed to create schedule confirmation notification: {e}")
        
        messages.success(request, f"Schedule confirmed for {p.user.email}. Tenant has been notified.")
        return redirect("admin_payments")
    
    schedule_info = f"{p.preferred_date.strftime('%B %d, %Y')}" if p.preferred_date else "No date"
    if p.preferred_time:
        schedule_info += f" at {p.preferred_time.strftime('%I:%M %p')}"
    
    return render(request, "admin_portal/confirm.html", {
        "title": "Confirm F2F Schedule",
        "message": f"Confirm cash payment appointment for {p.user.email}?\n\nAmount: ₱{p.amount:,.2f}\nScheduled: {schedule_info}\n\nTenant will be notified that the appointment is confirmed.",
        "post_url": reverse("admin_confirm_schedule", args=[p.id]),
        "back_url": reverse("admin_payments"),
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
        form.save(uploaded_by=request.user)
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
def admin_notifications(request):
    """Admin portal: view all notifications"""
    # Admins should see all notifications, not just user-specific ones
    notifications = Notification.objects.all().order_by('-created_at')
    unread_count = notifications.filter(is_read=False).count()
    
    # Return JSON for AJAX requests (for auto-refresh)
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        from django.http import JsonResponse
        return JsonResponse({
            'unread_count': unread_count,
            'notifications': [
                {
                    'id': n.id,
                    'title': n.title,
                    'message': n.message,
                    'notification_type': n.notification_type,
                    'is_read': n.is_read,
                    'created_at': n.created_at.strftime('%Y-%m-%d %H:%M:%S'),
                    'related_tenant': {
                        'email': n.related_tenant.email if n.related_tenant else None,
                        'name': n.related_tenant.tenantprofile.full_name if n.related_tenant and hasattr(n.related_tenant, 'tenantprofile') and n.related_tenant.tenantprofile else n.related_tenant.email if n.related_tenant else None
                    } if n.related_tenant else None,
                    'related_unit': {
                        'number': n.related_unit.number if n.related_unit else None,
                        'type': n.related_unit.get_unit_type_display() if n.related_unit else None
                    } if n.related_unit else None
                } for n in notifications
            ]
        })
    
    return render(request, "admin_portal/notifications.html", {
        'notifications': notifications,
        'unread_count': unread_count,
    })


@admin_required
def admin_mark_notification_read(request, notification_id):
    """Admin portal: mark notification as read"""
    notification = get_object_or_404(Notification, id=notification_id)
    notification.is_read = True
    notification.save()
    
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return JsonResponse({'success': True})
    
    return redirect("admin_notifications")


@admin_required
def admin_mark_all_notifications_read(request):
    """Admin portal: mark all notifications as read"""
    Notification.objects.filter(user=request.user, is_read=False).update(is_read=True)
    
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return JsonResponse({'success': True})
    
    return redirect("admin_notifications")


@admin_required
def admin_delete_notification(request, notification_id):
    """Admin portal: delete notification"""
    notification = get_object_or_404(Notification, id=notification_id, user=request.user)
    
    if request.method == "POST":
        notification_title = notification.title
        notification.delete()
        messages.success(request, f"Notification '{notification_title}' has been deleted successfully.")
        return redirect("admin_notifications")
    
    return render(request, "admin_portal/confirm.html", {
        "title": "Delete Notification",
        "message": f"Delete notification '{notification.title}'?",
        "post_url": reverse("admin_delete_notification", args=[notification.id]),
        "back_url": reverse("admin_notifications"),
    })


@admin_required
def admin_billing_export_csv(request):
    import csv
    from calendar import month_abbr
    month_filter  = request.GET.get("month", "").strip()
    year_filter   = request.GET.get("year", "").strip()
    status_filter = request.GET.get("status", "").strip()

    bills = MonthlyBill.objects.select_related(
        "lease", "lease__tenant", "lease__tenant__tenantprofile", "lease__unit"
    ).order_by("-billing_month")

    if month_filter:
        bills = bills.filter(billing_month__month=month_filter)
    if year_filter:
        bills = bills.filter(billing_month__year=year_filter)
    if status_filter:
        bills = bills.filter(status=status_filter)

    filename_parts = ["billing_report"]
    if month_filter and year_filter:
        try:
            filename_parts.append(f"{month_abbr[int(month_filter)]}_{year_filter}")
        except Exception:
            pass
    elif year_filter:
        filename_parts.append(year_filter)
    filename = "_".join(filename_parts) + ".csv"

    response = HttpResponse(content_type="text/csv")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'

    def peso(value):
        return f"PHP {float(value):,.2f}"

    writer = csv.writer(response)
    writer.writerow([
        "Tenant Name", "Email", "Unit", "Billing Month", "Due Date",
        "Base Rent", "Water Amount", "Interest", "Total Due",
        "Rent Paid", "Water Paid", "Total Balance",
        "Status", "Payment Reference", "Paid At",
    ])

    for b in bills:
        try:
            tp = b.lease.tenant.tenantprofile
            name = f"{tp.first_name} {tp.last_name}"
        except Exception:
            name = b.lease.tenant.email
        writer.writerow([
            name,
            b.lease.tenant.email,
            b.lease.unit.number,
            b.billing_month.strftime("%B %Y"),
            b.due_date.strftime("%Y-%m-%d") if b.due_date else "",
            peso(b.base_rent),
            peso(b.water_amount),
            peso(b.interest),
            peso(b.total_due),
            peso(b.rent_paid),
            peso(b.water_paid),
            peso(b.total_balance),
            b.get_status_display(),
            b.payment_reference or "",
            b.paid_at.strftime("%Y-%m-%d %H:%M") if b.paid_at else "",
        ])

    return response


@admin_required
def admin_billing(request):
    q = request.GET.get("q", "").strip()
    status_filter = request.GET.get("status", "").strip()
    month_filter = request.GET.get("month", "").strip()
    year_filter = request.GET.get("year", "").strip()
    active_tab = request.GET.get("tab", "active")
    if active_tab not in ("active", "upcoming"):
        active_tab = "active"

    today = date.today()
    current_month = today.replace(day=1)

    # ── Base queryset with search + date filters applied (no status filter yet) ──
    base_qs = MonthlyBill.objects.select_related("lease", "lease__unit", "lease__tenant")
    if q:
        base_qs = base_qs.filter(
            Q(lease__tenant__email__icontains=q) |
            Q(lease__unit__number__icontains=q) |
            Q(payment_reference__icontains=q)
        )
    if month_filter and month_filter.isdigit():
        base_qs = base_qs.filter(billing_month__month=int(month_filter))
    if year_filter and year_filter.isdigit():
        base_qs = base_qs.filter(billing_month__year=int(year_filter))

    # ── Stats: computed from DB for accuracy (not from sliced Python list) ──
    # Use billing_month for timing, status field as a proxy for paid (DB-level)
    # For unpaid counts we use status__in which now includes PARTIALLY_PAID
    stats_qs = base_qs
    paid_count = stats_qs.filter(status="PAID").count()
    unpaid_count = stats_qs.filter(
        status__in=["UNPAID", "PARTIALLY_PAID"],
        billing_month__lte=current_month
    ).count()
    overdue_count = stats_qs.filter(
        status__in=["UNPAID", "PARTIALLY_PAID"],
        billing_month__lt=current_month
    ).count()
    partial_count = stats_qs.filter(status="PARTIALLY_PAID").count()
    upcoming_count = stats_qs.filter(
        billing_month__gt=current_month
    ).count()

    # ── Fetch all matching bills for display (split in Python using total_balance) ──
    all_bills = list(base_qs.order_by("-billing_month"))

    # Active = current month and older (operations happen here)
    active_bills = [b for b in all_bills if b.billing_month.replace(day=1) <= current_month]
    # Upcoming = future months only (informational)
    upcoming_bills = [b for b in all_bills if b.billing_month.replace(day=1) > current_month]

    # ── Apply status sub-filter within the active tab using b.status as source of truth ──
    if active_tab == "active":
        if status_filter == "UNPAID":
            display_bills = [b for b in active_bills if b.status in ("UNPAID", "PARTIALLY_PAID")]
        elif status_filter == "OVERDUE":
            display_bills = [b for b in active_bills
                             if b.status in ("UNPAID", "PARTIALLY_PAID") and b.billing_month.replace(day=1) < current_month]
        elif status_filter == "PARTIAL":
            display_bills = [b for b in active_bills
                             if b.status == "PARTIALLY_PAID"]
        elif status_filter == "PAID":
            display_bills = [b for b in active_bills if b.status == "PAID"]
        else:
            display_bills = active_bills
    else:
        # Upcoming tab — no status sub-filter needed
        display_bills = upcoming_bills

    # Paginate results (10 items per page)
    paginator = Paginator(display_bills, 10)
    page_number = request.GET.get("page")
    page_obj = paginator.get_page(page_number)

    current_year = timezone.now().year
    month_choices = [
        (1, "January"), (2, "February"), (3, "March"), (4, "April"),
        (5, "May"), (6, "June"), (7, "July"), (8, "August"),
        (9, "September"), (10, "October"), (11, "November"), (12, "December"),
    ]
    year_choices = list(range(current_year - 3, current_year + 2))

    return render(request, "admin_portal/billing.html", {
        "page_obj": page_obj,
        "active_tab": active_tab,
        "q": q,
        "status_filter": status_filter,
        "month_filter": month_filter,
        "year_filter": year_filter,
        "month_choices": month_choices,
        "year_choices": year_choices,
        "paid_count": paid_count,
        "unpaid_count": unpaid_count,
        "overdue_count": overdue_count,
        "partial_count": partial_count,
        "upcoming_count": upcoming_count,
    })


@admin_required
def admin_delete_bill(request, bill_id: int):
    bill = get_object_or_404(MonthlyBill.objects.select_related("lease", "lease__tenant", "lease__unit"), pk=bill_id)
    if request.method == "POST":
        with transaction.atomic():
            bill.delete()
        return redirect("admin_billing")
    return render(request, "admin_portal/confirm.html", {
        "title": "Delete Billing Record",
        "message": f"Delete billing record for {bill.lease.tenant.email} / {bill.lease.unit.number} / {bill.billing_month}? Linked payment history references will be cleaned up.",
        "post_url": reverse("admin_delete_bill", args=[bill.id]),
        "back_url": reverse("admin_billing"),
    })


@admin_required
def admin_send_bill_warning(request, bill_id: int):
    from django.conf import settings as django_settings

    bill = get_object_or_404(
        MonthlyBill.objects.select_related("lease", "lease__tenant", "lease__unit"),
        pk=bill_id
    )
    tenant = bill.lease.tenant
    unit = bill.lease.unit

    try:
        tp = tenant.tenantprofile
        name = f"{tp.first_name} {tp.last_name}"
    except Exception:
        name = tenant.email

    billing_month = bill.billing_month.strftime("%B %Y")
    balance = float(bill.total_balance) if bill.total_balance else float(bill.total_due)
    due_date = bill.due_date.strftime("%B %d, %Y") if bill.due_date else "N/A"

    subject = f"[REALESTATE360+] Billing Reminder - {billing_month}"
    message = (
        f"Dear {name},\n\n"
        f"This is a friendly reminder that your bill for {billing_month} is still outstanding.\n\n"
        f"  Unit:          {unit.number}\n"
        f"  Billing Month: {billing_month}\n"
        f"  Due Date:      {due_date}\n"
        f"  Amount Due:    PHP {balance:,.2f}\n\n"
        f"Please settle your balance at your earliest convenience to avoid any penalties.\n\n"
        f"If you have already made your payment, please disregard this notice.\n\n"
        f"Thank you,\n"
        f"REALESTATE360+ Administration"
    )

    try:
        import resend
        resend.api_key = settings.RESEND_API_KEY
        resend.Emails.send({
            'from': 'REALESTATE360+ <noreply@realestate360.site>',
            'to': [tenant.email],
            'subject': subject,
            'text': message,
        })
        messages.success(request, f"Warning email sent to {tenant.email} for {billing_month}.")
    except Exception as e:
        messages.error(request, f"Failed to send email: {e}")

    return redirect(f"{reverse('admin_billing')}?tab=active")


@admin_required
def admin_payments(request):
    q = request.GET.get("q", "").strip()
    status = request.GET.get("status", "").strip()
    method = request.GET.get("method", "").strip()

    payments = ManualPayment.objects.select_related("user")
    if status in ("PENDING", "APPROVED", "REJECTED"):
        payments = payments.filter(status=status)
    if method == "GCASH":
        payments = payments.filter(payment_method="GCASH")
    elif method == "CASH":
        payments = payments.filter(~Q(payment_method="GCASH"))

    if q:
        payments = payments.filter(
            Q(user__email__icontains=q) |
            Q(reference_code__icontains=q) |
            Q(bill_ids__icontains=q)
        )

    payments = payments.order_by("-created_at")[:500]
    
    # Calculate payment status counts
    all_payments = ManualPayment.objects.select_related("user")
    if q:
        all_payments = all_payments.filter(
            Q(user__email__icontains=q) |
            Q(reference_code__icontains=q) |
            Q(bill_ids__icontains=q)
        )
    
    if status == "PENDING":
        pending_count = payments.count()
        approved_count = 0
        rejected_count = 0
    elif status == "APPROVED":
        pending_count = 0
        approved_count = payments.count()
        rejected_count = 0
    elif status == "REJECTED":
        pending_count = 0
        approved_count = 0
        rejected_count = payments.count()
    else:
        pending_count = all_payments.filter(status="PENDING").count()
        approved_count = all_payments.filter(status="APPROVED").count()
        rejected_count = all_payments.filter(status="REJECTED").count()
    
    # Paginate results (10 items per page)
    paginator = Paginator(payments, 10)
    page_number = request.GET.get("page")
    page_obj = paginator.get_page(page_number)
    
    return render(request, "admin_portal/payments.html", {
        "page_obj": page_obj, 
        "q": q, 
        "status": status,
        "method": method,
        "pending_count": pending_count,
        "approved_count": approved_count,
        "rejected_count": rejected_count
    })


@admin_required
def admin_delete_payment(request, payment_id: int):
    payment = get_object_or_404(ManualPayment.objects.select_related("user"), pk=payment_id)
    if request.method == "POST":
        with transaction.atomic():
            payment.delete()
        return redirect("admin_payments")
    return render(request, "admin_portal/confirm.html", {
        "title": "Delete Billing History",
        "message": f"Delete payment history {payment.reference_code} for {payment.user.email}?",
        "post_url": reverse("admin_delete_payment", args=[payment.id]),
        "back_url": reverse("admin_payments"),
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


@require_http_methods(["GET"])
def api_get_unit_data(request, unit_number):
    """
    API endpoint to get unit data for automatic price population
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


@require_http_methods(["GET"])
def api_get_unit_data_by_id(request, unit_id):
    """
    API endpoint to get unit data by ID for lease forms
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


@admin_required
def admin_forecasting(request):
    today = timezone.now().date()
    current_month_start = today.replace(day=1)

    def _month_date(i):
        y, m = current_month_start.year, current_month_start.month - i
        while m <= 0:
            m += 12
            y -= 1
        return datetime(y, m, 1).date()

    def _moving_avg_forecast(series, window=3, steps=3):
        if len(series) < window:
            return [round(sum(series) / max(len(series), 1), 2)] * steps
        tail = series[-window:]
        forecasts = []
        buf = list(tail)
        for _ in range(steps):
            val = round(sum(buf[-window:]) / window, 2)
            forecasts.append(val)
            buf.append(val)
        return forecasts

    def _accuracy_metrics(series, window=3, test_steps=3):
        import math
        n = len(series)
        if n < window + test_steps:
            return {"rmse": None, "mae": None, "mape": None}
        train = series[:n - test_steps]
        actual = series[n - test_steps:]
        preds = []
        buf = list(train)
        for _ in range(test_steps):
            val = sum(buf[-window:]) / window
            preds.append(val)
            buf.append(val)
        errors = [a - p for a, p in zip(actual, preds)]
        mae  = round(sum(abs(e) for e in errors) / test_steps, 2)
        rmse = round(math.sqrt(sum(e ** 2 for e in errors) / test_steps), 2)
        non_zero = [(a, e) for a, e in zip(actual, errors) if a != 0]
        mape = round(sum(abs(e / a) for a, e in non_zero) / len(non_zero) * 100, 2) if non_zero else None
        return {"rmse": rmse, "mae": mae, "mape": mape}

    def _clean_series(series):
        s = list(series)
        while s and s[-1] == 0:
            s.pop()
        return s

    def _sarima_forecast(series, order=(0,1,1), seasonal_order=(1,1,1,12), steps=6):
        try:
            import warnings
            import numpy as np
            from statsmodels.tsa.statespace.sarimax import SARIMAX
            s = _clean_series(series)
            if len(s) < 18:
                return None, None, None
            with warnings.catch_warnings():
                warnings.simplefilter('ignore')
                model = SARIMAX(s, order=order, seasonal_order=seasonal_order,
                                enforce_stationarity=False, enforce_invertibility=False)
                fit = model.fit(disp=False)
            forecast_obj = fit.get_forecast(steps=steps)
            mean = [round(float(v), 2) for v in forecast_obj.predicted_mean]
            ci = np.array(forecast_obj.conf_int(alpha=0.2))
            lower = [round(float(v), 2) for v in ci[:, 0]]
            upper = [round(float(v), 2) for v in ci[:, 1]]
            return mean, lower, upper
        except ImportError:
            # statsmodels not installed - return None to indicate SARIMA unavailable
            return None, None, None
        except Exception as e:
            # Log other errors but return None to prevent page crashes
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"SARIMA forecast error: {e}")
            return None, None, None

    def _sarima_metrics(series, order=(0,1,1), seasonal_order=(1,1,1,12), test_steps=6):
        try:
            import math
            import warnings
            import numpy as np
            from statsmodels.tsa.statespace.sarimax import SARIMAX
            s = _clean_series(series)
            n = len(s)
            if n < 18:
                return {"rmse": None, "mae": None, "mape": None}
            train = s[:n - test_steps]
            actual = s[n - test_steps:]
            with warnings.catch_warnings():
                warnings.simplefilter('ignore')
                model = SARIMAX(train, order=order, seasonal_order=seasonal_order,
                                enforce_stationarity=False, enforce_invertibility=False)
                fit = model.fit(disp=False)
            preds = [float(v) for v in fit.get_forecast(steps=test_steps).predicted_mean]
            errors = [a - p for a, p in zip(actual, preds)]
            mae  = round(sum(abs(e) for e in errors) / test_steps, 2)
            rmse = round(math.sqrt(sum(e ** 2 for e in errors) / test_steps), 2)
            non_zero = [(a, e) for a, e in zip(actual, errors) if a != 0]
            mape = round(sum(abs(e / a) for a, e in non_zero) / len(non_zero) * 100, 2) if non_zero else None
            return {"rmse": rmse, "mae": mae, "mape": mape}
        except ImportError:
            # statsmodels not installed - return None metrics
            return {"rmse": None, "mae": None, "mape": None}
        except Exception as e:
            # Log other errors but return None to prevent page crashes
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"SARIMA metrics error: {e}")
            return {"rmse": None, "mae": None, "mape": None}

    def _next_month_labels(steps=3):
        labels = []
        y, m = current_month_start.year, current_month_start.month
        for _ in range(steps):
            m += 1
            if m > 12:
                m = 1
                y += 1
            labels.append(datetime(y, m, 1).strftime('%b %Y'))
        return labels

    revenue_series, water_series, maintenance_series, hist_labels = [], [], [], []

    for i in range(24, -1, -1):
        md = _month_date(i)
        rev = float(
            MonthlyBill.objects.filter(
                billing_month__year=md.year,
                billing_month__month=md.month,
            ).aggregate(
                total=Sum(ExpressionWrapper(
                    F("base_rent") + F("water_amount") + F("interest"),
                    output_field=DecimalField()
                ))
            )["total"] or 0
        )
        water = float(
            WaterReading.objects.filter(
                reading_month__year=md.year,
                reading_month__month=md.month,
            ).aggregate(total=Sum("consumption"))["total"] or 0
        )
        maint = MaintenanceRequest.objects.filter(
            created_at__year=md.year,
            created_at__month=md.month,
        ).count()

        revenue_series.append(rev)
        water_series.append(water)
        maintenance_series.append(maint)
        hist_labels.append(md.strftime('%b %Y'))

    forecast_labels = _next_month_labels(3)
    revenue_forecast = _moving_avg_forecast(revenue_series, window=3, steps=3)
    water_forecast = _moving_avg_forecast(water_series, window=3, steps=3)
    maintenance_forecast = _moving_avg_forecast(maintenance_series, window=3, steps=3)

    revenue_metrics = _accuracy_metrics(revenue_series)
    water_metrics = _accuracy_metrics(water_series)
    maintenance_metrics = _accuracy_metrics(maintenance_series)

    rev_sarima_fc, rev_sarima_lower, rev_sarima_upper = _sarima_forecast(
        revenue_series, order=(0,1,1), seasonal_order=(1,1,1,12), steps=6)
    water_sarima_fc, water_sarima_lower, water_sarima_upper = _sarima_forecast(
        water_series, order=(0,1,1), seasonal_order=(1,1,1,12), steps=6)

    revenue_sarima_metrics = _sarima_metrics(revenue_series, order=(0,1,1), seasonal_order=(1,1,1,12))
    water_sarima_metrics   = _sarima_metrics(water_series,   order=(0,1,1), seasonal_order=(1,1,1,12))

    hist_revenue_last12 = revenue_series[-36:]
    hist_water_last12 = water_series[-36:]
    hist_maintenance_last12 = maintenance_series[-36:]
    hist_labels_last12 = hist_labels[-36:]

   
    
    return render(request, "admin_portal/forecasting.html", {
        "hist_labels": hist_labels_last12,
        "hist_revenue": hist_revenue_last12,
        "hist_water": hist_water_last12,
        "hist_maintenance": hist_maintenance_last12,
        "forecast_labels": forecast_labels,
        "revenue_forecast": revenue_forecast,
        "water_forecast": water_forecast,
        "maintenance_forecast": maintenance_forecast,
        "revenue_metrics": revenue_metrics,
        "water_metrics": water_metrics,
        "maintenance_metrics": maintenance_metrics,
        "rev_sarima_fc": rev_sarima_fc,
        "rev_sarima_lower": rev_sarima_lower,
        "rev_sarima_upper": rev_sarima_upper,
        "water_sarima_fc": water_sarima_fc,
        "water_sarima_lower": water_sarima_lower,
        "water_sarima_upper": water_sarima_upper,
        "revenue_sarima_metrics": revenue_sarima_metrics,
        "water_sarima_metrics": water_sarima_metrics,
        "sarima_available": rev_sarima_fc is not None,
        "unread_count": Notification.objects.filter(is_read=False).count(),
    })


@admin_required
def admin_billed_this_month(request):
    """Breakdown of all bills generated this month — shows how Billed This Month is calculated."""
    today = timezone.now().date()

    # Allow ?month=YYYY-MM to view other months too
    month_str = request.GET.get("month", "").strip()
    if month_str:
        try:
            target = datetime.strptime(month_str, "%Y-%m").date()
        except ValueError:
            target = today
    else:
        target = today

    # All bills this month (for context counts)
    all_bills = (
        MonthlyBill.objects
        .filter(billing_month__year=target.year, billing_month__month=target.month)
        .select_related("lease", "lease__unit", "lease__tenant", "lease__tenant__tenantprofile")
        .order_by("lease__unit__number")
    )

    # Only PAID bills are shown in the breakdown
    bills = [b for b in all_bills if b.status == "PAID"]
    unpaid_count = sum(1 for b in all_bills if b.status == "UNPAID")
    partial_count = sum(1 for b in all_bills if b.status == "PARTIALLY_PAID")

    # Totals from PAID bills only
    total_rent = sum(b.base_rent for b in bills)
    total_water = sum(b.water_amount for b in bills)
    total_parking = sum(b.parking_fee for b in bills)
    total_interest = sum(b.interest for b in bills)
    grand_total = total_rent + total_water + total_parking + total_interest

    return render(request, "admin_portal/billed_this_month.html", {
        "bills": bills,
        "total_bills": len(all_bills),
        "unpaid_count": unpaid_count,
        "partial_count": partial_count,
        "total_rent": total_rent,
        "total_water": total_water,
        "total_parking": total_parking,
        "total_interest": total_interest,
        "grand_total": grand_total,
        "target_month": target,
        "current_month_str": today.strftime("%Y-%m"),
        "unread_count": Notification.objects.filter(is_read=False).count(),
    })
