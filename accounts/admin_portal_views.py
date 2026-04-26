from datetime import date, datetime, timedelta
import logging

from django.db.models import Sum, Q
from django.db import transaction
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.urls import reverse
from django.db.models import Q
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
from django.core.paginator import Paginator
from django.utils.timezone import now
import json
from django.utils import timezone
from rentals.models import Lease, Unit, TenantProfile, Notification, TenantRiskClassification
from billing.models import MonthlyBill
from billing.services import ensure_bills_since_move_in, set_bill_status, approve_manual_payment, reject_manual_payment
from payments.models import ManualPayment
from maintenance.models import MaintenanceRequest
from announcements.models import Announcement
from maintenance.forms import AdminMaintenanceUpdateForm
from rentals.services import TenantRiskService

from .admin_portal_forms import TenantProfileForm, AnnouncementForm, LeaseForm
from .admin_portal_forms import TenantProfileEditForm
from .admin_portal_forms import UnitForm
from django.utils import timezone as dj_timezone
from django.contrib import messages
from .decorators import admin_required

logger = logging.getLogger(__name__)


@admin_required
def admin_dashboard(request):
    total_tenants = Lease.objects.filter(is_active=True).values("tenant").distinct().count()
    occupied_units = Lease.objects.filter(is_active=True).count()
    vacant_units = Unit.objects.filter(is_active=True).count() - occupied_units

    today = timezone.now().date()
    # Count revenue by when bills were actually paid (paid_at), not by their billing month.
    # This ensures advance payments approved now are included in this month's revenue.
    total_revenue = (
        MonthlyBill.objects.filter(status="PAID", paid_at__year=today.year, paid_at__month=today.month)
        .aggregate(total=Sum("total_due"))["total"] or 0
    )
    overdue_payments = MonthlyBill.objects.filter(status="UNPAID", due_date__lt=today).count()

    # Get monthly rental income data for the past 12 months including current month
    monthly_income_data = []
    months_labels = []
    
    # Debug: Check if we have any data
    logger.info(f"DEBUG: Today is {today}")
    logger.info(f"DEBUG: Total paid bills: {MonthlyBill.objects.filter(status='PAID').count()}")
    logger.info(f"DEBUG: Active leases: {Lease.objects.filter(is_active=True).count()}")
    
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
        
        # Get paid bills for this month
        month_revenue = (
            MonthlyBill.objects.filter(
                status="PAID",
                paid_at__year=month_date.year,
                paid_at__month=month_date.month
            ).aggregate(total=Sum("total_due"))["total"] or 0
        )
        
        # Get expected revenue from active leases
        expected_revenue = (
            Lease.objects.filter(is_active=True)
            .aggregate(total=Sum("monthly_rent"))["total"] or 0
        )
        
        monthly_income_data.append({
            'month': month_date.strftime('%b %Y'),
            'actual': float(month_revenue),
            'expected': float(expected_revenue)
        })
        months_labels.append(month_date.strftime('%b'))
        
        # Debug: Log each month's data
        logger.info(f"DEBUG: {month_date.strftime('%b %Y')} - Actual: {month_revenue}, Expected: {expected_revenue}")
    
    logger.info(f"DEBUG: Final monthly_income_data: {monthly_income_data}")
    logger.info(f"DEBUG: Final months_labels: {months_labels}")

    # Get notifications for admin (all notifications, not just user-specific)
    all_notifications = Notification.objects.all().order_by('-created_at')
    notifications = all_notifications[:5]
    unread_notifications = all_notifications.filter(is_read=False)
    unread_count = unread_notifications.count()

    return render(request, "admin_portal/dashboard.html", {
        "total_tenants": total_tenants,
        "occupied_units": occupied_units,
        "vacant_units": max(vacant_units, 0),
        "total_revenue": total_revenue,
        "overdue_payments": overdue_payments,
        "notifications": notifications,
        "unread_notifications": unread_notifications,
        "unread_count": unread_count,
        "monthly_income_data": monthly_income_data,
        "months_labels": months_labels,
    })


@admin_required
def admin_tenants(request):
    q = request.GET.get("q", "").strip()

    tenants = TenantProfile.objects.select_related("user")
    if q:
        tenants = tenants.filter(
            Q(full_name__icontains=q) |
            Q(contact_no__icontains=q) |
            Q(user__email__icontains=q) |
            Q(user__username__icontains=q)
        )

    tenants = tenants.order_by("full_name")[:500]
    return render(request, "admin_portal/tenants.html", {"tenants": tenants, "q": q})


@admin_required
def admin_tenant_detail(request, tenant_id: int):
    tenant = get_object_or_404(TenantProfile.objects.select_related("user"), pk=tenant_id)
    leases = Lease.objects.select_related("unit", "tenant").filter(tenant=tenant.user).order_by("-start_date")
    return render(request, "admin_portal/tenant_detail.html", {"tenant": tenant, "leases": leases})


@admin_required
def admin_create_tenant_profile(request):
    """
    Admin portal: create a TenantProfile row (linked to an existing User).
    """
    form = TenantProfileForm(request.POST or None)

    if request.method == "POST" and form.is_valid():
        tenant_profile = form.save()
        # after creating a tenant, redirect admin to create a lease for that tenant
        try:
            tenant_id = tenant_profile.user.id
            return redirect(f"{reverse('admin_create_lease')}?tenant_id={tenant_id}")
        except Exception as e:
            logger.exception("Failed to redirect to create lease for tenant %s: %s", getattr(tenant_profile.user, 'id', None), e)
            messages.warning(request, "Tenant created but could not prefill lease form. Redirecting to tenants list.")
            return redirect("admin_tenants")

    return render(request, "admin_portal/form.html", {
        "title": "Add Tenant",
        "form": form,
        "back_url": reverse("admin_tenants"),
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
    
    # Get statistics
    total_units = units.count()
    available_units = units.filter(status='AVAILABLE').count()
    occupied_units = units.filter(status='OCCUPIED').count()
    maintenance_units = units.filter(status='MAINTENANCE').count()
    
    return render(request, "admin_portal/units.html", {
        'units': units,
        'status_filter': status_filter,
        'search_query': search_query,
        'total_units': total_units,
        'available_units': available_units,
        'occupied_units': occupied_units,
        'maintenance_units': maintenance_units,
    })


@admin_required
def admin_unit_detail(request, unit_id):
    """Admin portal: view unit details."""
    unit = get_object_or_404(Unit, id=unit_id, is_active=True)
    current_tenant = unit.get_current_tenant()
    
    return render(request, "admin_portal/unit_detail.html", {
        'unit': unit,
        'current_tenant': current_tenant,
        'amenities_list': unit.get_amenities_list(),
    })


@admin_required
def admin_create_unit(request):
    """Admin portal: create a Unit row."""
    if request.method == "POST":
        # Debug: Print the POST data
        print("POST data:", request.POST)
        
        form = UnitForm(request.POST)
        
        if form.is_valid():
            try:
                unit = form.save(commit=False)
                unit.is_active = True
                unit.save()
                
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
                print("Form save error:", e)
        else:
            # Debug: Print form errors
            print("Form errors:", form.errors)
            messages.error(request, 'Please correct the errors below.')
    else:
        form = UnitForm()

    return render(request, "admin_portal/unit_form_final_working.html", {
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
        print("=== MANUAL FORM PROCESSING TEST ===")
        print("Unit before update:", f"ID={unit.id}, Number={unit.number}, Rent={unit.monthly_rent}")
        print("POST data:", request.POST)
        
        # Try manual processing first
        try:
            monthly_rent = request.POST.get('monthly_rent')
            print(f"Monthly rent from POST: {monthly_rent}")
            
            if monthly_rent:
                # Manual update bypassing Django form
                unit.monthly_rent = float(monthly_rent)
                unit.is_active = True
                unit.save()
                
                print(f"Unit after manual save: PHP {unit.monthly_rent}")
                unit.refresh_from_db()
                print(f"Unit after refresh: PHP {unit.monthly_rent}")
                
                messages.success(request, f'Unit {unit.number} has been updated successfully!')
                return redirect("admin_unit_detail", unit_id=unit.id)
            else:
                print("No monthly_rent in POST data")
                
        except Exception as e:
            print(f"Manual processing error: {e}")
            import traceback
            traceback.print_exc()
        
        print("=== FALLING BACK TO DJANGO FORM ===")
        
        # Fall back to Django form processing with debug
        form = UnitForm(request.POST, instance=unit)
        print("Form is valid:", form.is_valid())
        
        if form.is_valid():
            try:
                unit = form.save(commit=False)
                unit.is_active = True
                unit.save()
                print("Django form save successful")
                messages.success(request, f'Unit {unit.number} has been updated successfully!')
                return redirect("admin_unit_detail", unit_id=unit.id)
            except Exception as e:
                print(f"Django form save error: {e}")
        else:
            print("Django form errors:", form.errors)
            messages.error(request, 'Please correct the errors below.')
        
        print("=== END MANUAL PROCESSING TEST ===")
    else:
        form = UnitForm(instance=unit)
    
    return render(request, "admin_portal/unit_form_final_working.html", {
        "title": "Edit Unit",
        "action": "Edit",
        "form": form,
        "back_url": reverse("admin_unit_detail", args=[unit.id]),
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
    Admin portal: create a Lease row (linking a tenant to a unit).
    """
    # allow pre-filling tenant via ?tenant_id=... when redirected from tenant creation
    initial = {}
    tenant_id = request.GET.get("tenant_id")
    if tenant_id:
        initial["tenant"] = tenant_id

    form = LeaseForm(request.POST or None, initial=initial)

    if request.method == "POST" and form.is_valid():
        lease = form.save()
        
        # Create real-time notification for admin about new lease
        try:
            Notification.create_notification(
                title=f"New Lease Created",
                message=f"Lease created for {lease.tenant.email} in Unit {lease.unit.number} (Monthly Rent: ₱{lease.monthly_rent:,.2f})",
                notification_type='LEASE',
                related_tenant=lease.tenant,
                related_unit=lease.unit
            )
        except Exception as e:
            logger.exception(f"Failed to create lease notification: {e}")
        
        # Update unit status to OCCUPIED when lease is created
        try:
            unit = lease.unit
            unit.status = 'OCCUPIED'
            unit.save()
            logger.info(f"Unit {unit.number} status updated to OCCUPIED for lease {lease.id}")
        except Exception as e:
            logger.exception(f"Failed to update unit status for lease {lease.id}: {e}")
            # Don't block lease creation if unit status update fails
        
        # create initial monthly bill rows from move-in until today
        try:
            ensure_bills_since_move_in(lease)
        except Exception:
            # don't block creation if billing generation fails; admin can regenerate later
            logger.exception("ensure_bills_since_move_in failed for lease id %s", getattr(lease, 'id', None))
            messages.warning(request, "Failed to generate initial bills; you can regenerate later.")
        
        messages.success(request, f'Lease created successfully! Unit {lease.unit.number} is now occupied.')
        return redirect("admin_tenants")

    return render(request, "admin_portal/lease_form.html", {
        "title": "Add Lease",
        "form": form,
        "back_url": reverse("admin_tenants"),
    })


@admin_required
def admin_edit_tenant(request, tenant_id: int):
    tenant = get_object_or_404(TenantProfile, pk=tenant_id)
    form = TenantProfileEditForm(request.POST or None, instance=tenant)
    if request.method == "POST" and form.is_valid():
        form.save()
        return redirect("admin_tenant_detail", tenant_id=tenant.id)
    return render(request, "admin_portal/form.html", {
        "title": "Edit Tenant",
        "form": form,
        "back_url": reverse("admin_tenant_detail", args=[tenant.id]),
    })


@admin_required
def admin_delete_tenant(request, tenant_id: int):
    tenant = get_object_or_404(TenantProfile, pk=tenant_id)
    if request.method == "POST":
        tenant.delete()
        return redirect("admin_tenants")
    return render(request, "admin_portal/confirm.html", {
        "title": "Delete Tenant",
        "message": f"Delete tenant {tenant.full_name}? This cannot be undone.",
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
    return render(request, "admin_portal/form.html", {
        "title": "Edit Lease",
        "form": form,
        "back_url": reverse("admin_tenants"),
    })


@admin_required
def admin_delete_lease(request, lease_id: int):
    lease = get_object_or_404(Lease, pk=lease_id)
    if request.method == "POST":
        # Store unit info before deleting lease
        unit = lease.unit
        unit_number = unit.number
        
        # Delete the lease
        lease.delete()
        
        # Update unit status back to AVAILABLE
        try:
            unit.status = 'AVAILABLE'
            unit.save()
            logger.info(f"Unit {unit_number} status updated to AVAILABLE after lease deletion")
        except Exception as e:
            logger.exception(f"Failed to update unit {unit_number} status after lease deletion: {e}")
        
        return redirect("admin_tenants")
    return render(request, "admin_portal/confirm.html", {
        "title": "Delete Lease",
        "message": f"Delete lease for {lease.tenant.email} -> {lease.unit.number}? Unit will become available again.",
        "post_url": reverse("admin_delete_lease", args=[lease.id]),
        "back_url": reverse("admin_tenant_detail", args=[lease.tenant.id])
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
        approve_manual_payment(p)
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
        return redirect("admin_payments")
    return render(request, "admin_portal/confirm.html", {
        "title": "Reject Payment",
        "message": f"Reject payment {p.reference_code} by {p.user.email}?",
        "post_url": reverse("admin_reject_payment", args=[p.id]),
        "back_url": reverse("admin_payments"),
    })


@admin_required
def admin_update_maintenance(request, req_id: int):
    req = get_object_or_404(MaintenanceRequest, pk=req_id)
    if request.method == "POST":
        form = AdminMaintenanceUpdateForm(request.POST, instance=req)
        if form.is_valid():
            updated = form.save(commit=False)
            # set resolved_at when marked resolved
            if updated.status == "RESOLVED" and not req.resolved_at:
                updated.resolved_at = dj_timezone.now()
            if updated.status != "RESOLVED":
                updated.resolved_at = None
            updated.save()
            return redirect("admin_maintenance")
    else:
        form = AdminMaintenanceUpdateForm(instance=req)

    return render(request, "admin_portal/form.html", {
        "title": "Update Maintenance",
        "form": form,
        "back_url": reverse("admin_maintenance"),
    })


@admin_required
def admin_edit_announcement(request, ann_id: int):
    ann = get_object_or_404(Announcement, pk=ann_id)
    form = AnnouncementForm(request.POST or None, instance=ann)
    if request.method == "POST" and form.is_valid():
        form.save()
        return redirect("admin_announcements")
    return render(request, "admin_portal/form.html", {
        "title": "Edit Announcement",
        "form": form,
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
def admin_billing(request):
    q = request.GET.get("q", "").strip()
    status = request.GET.get("status", "").strip()

    bills = MonthlyBill.objects.select_related("lease", "lease__unit", "lease__tenant")

    if status in ("PAID", "UNPAID"):
        bills = bills.filter(status=status)

    if q:
        bills = bills.filter(
            Q(lease__tenant__email__icontains=q) |
            Q(lease__unit__number__icontains=q) |
            Q(payment_reference__icontains=q)
        )

    bills = bills.order_by("-billing_month")[:500]
    
    # Calculate paid bills count for statistics
    if status == "PAID":
        paid_bills_count = bills.count()
    elif status == "UNPAID":
        paid_bills_count = 0
    else:
        # Count paid bills from all bills (before filtering)
        all_bills = MonthlyBill.objects.select_related("lease", "lease__unit", "lease__tenant")
        if q:
            all_bills = all_bills.filter(
                Q(lease__tenant__email__icontains=q) |
                Q(lease__unit__number__icontains=q) |
                Q(payment_reference__icontains=q)
            )
        paid_bills_count = all_bills.filter(status="PAID").count()
    
    # Calculate unpaid bills count
    if status == "PAID":
        unpaid_bills_count = 0
    elif status == "UNPAID":
        unpaid_bills_count = bills.count()
    else:
        # Count unpaid bills from all bills (before filtering)
        all_bills = MonthlyBill.objects.select_related("lease", "lease__unit", "lease__tenant")
        if q:
            all_bills = all_bills.filter(
                Q(lease__tenant__email__icontains=q) |
                Q(lease__unit__number__icontains=q) |
                Q(payment_reference__icontains=q)
            )
        unpaid_bills_count = all_bills.filter(status="UNPAID").count()
    
    return render(request, "admin_portal/billing.html", {
        "bills": bills, 
        "q": q, 
        "status": status,
        "paid_bills_count": paid_bills_count,
        "unpaid_bills_count": unpaid_bills_count
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
def admin_payments(request):
    q = request.GET.get("q", "").strip()
    status = request.GET.get("status", "").strip()

    payments = ManualPayment.objects.select_related("user")
    if status in ("PENDING", "APPROVED", "REJECTED"):
        payments = payments.filter(status=status)
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
    
    return render(request, "admin_portal/payments.html", {
        "payments": payments, 
        "q": q, 
        "status": status,
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
            Q(tenant__tenantprofile__full_name__icontains=q)
        )
    
    # Pagination
    paginator = Paginator(risk_classifications, 20)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    # Calculate statistics
    total_tenants = risk_classifications.count()
    low_risk_count = TenantRiskClassification.objects.filter(risk_level='LOW').count()
    medium_risk_count = TenantRiskClassification.objects.filter(risk_level='MEDIUM').count()
    high_risk_count = TenantRiskClassification.objects.filter(risk_level='HIGH').count()
    new_tenant_count = TenantRiskClassification.objects.filter(is_new_tenant=True).count()
    
    context = {
        'page_obj': page_obj,
        'q': q,
        'risk': risk_filter,
        'total_tenants': total_tenants,
        'low_risk_count': low_risk_count,
        'medium_risk_count': medium_risk_count,
        'high_risk_count': high_risk_count,
        'new_tenant_count': new_tenant_count,
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

    reqs = MaintenanceRequest.objects.select_related("lease", "lease__unit", "lease__tenant")

    if status:
        reqs = reqs.filter(status=status)

    if q:
        reqs = reqs.filter(
            Q(lease__tenant__email__icontains=q) |
            Q(lease__unit__number__icontains=q) |
            Q(description__icontains=q)
        )

    reqs = reqs.order_by("-created_at")[:500]
    return render(request, "admin_portal/maintenance.html", {"reqs": reqs, "q": q, "status": status})


@admin_required
def admin_announcements(request):
    q = request.GET.get("q", "").strip()
    items = Announcement.objects.all()

    # FIX: model field is "body", not "content"
    if q:
        items = items.filter(Q(title__icontains=q) | Q(body__icontains=q))

    items = items.order_by("-created_at")[:200]
    return render(request, "admin_portal/announcements.html", {"items": items, "q": q})


@admin_required
def admin_create_announcement(request):
    form = AnnouncementForm(request.POST or None)

    if request.method == "POST" and form.is_valid():
        form.save(user=request.user)  # uses your custom save(user=...)
        return redirect("admin_announcements")

    return render(request, "admin_portal/form.html", {
        "title": "Add Announcement",
        "form": form,
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
