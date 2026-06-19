from datetime import date, datetime, timedelta, timezone
import logging
import os
from urllib.parse import quote

from django.conf import settings
from django.db.models import Sum, Q, F, ExpressionWrapper, DecimalField, Exists, OuterRef, Subquery, Count, Prefetch
from django.db.models.functions import Coalesce, TruncMonth
from django.db import transaction
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.urls import reverse
from django.http import JsonResponse, HttpResponse
from django.views.decorators.http import require_http_methods, require_GET
from django.core.paginator import Paginator
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils.timezone import now
import json
from django.utils import timezone
from rentals.models import Lease, Unit, UnitImage, TenantProfile, Notification, TenantRiskClassification, Room
from billing.models import MonthlyBill
from billing.services import ensure_bills_since_move_in, set_bill_status, approve_manual_payment, reject_manual_payment, cleanup_duplicate_monthly_bills_for_lease
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
from rentals.services import TenantRiskService, repair_historical_move_in_payment

from .admin_portal_forms import TenantProfileForm, AnnouncementForm, LeaseForm
from .admin_portal_forms import TenantProfileEditForm
from .admin_portal_forms import ComprehensiveTenantEditForm
from .admin_portal_forms import UnitForm
from rentals.models import UnitImage
from django.contrib import messages
from .decorators import admin_required


def admin_password_verified(request) -> bool:
    return request.user.check_password((request.POST.get("admin_password") or "").strip())


def render_admin_password_confirm(request, *, title, message, post_url, back_url, error=None, attachment=None):
    return render(
        request,
        "admin_portal/confirm.html",
        {
            "title": title,
            "message": message,
            "post_url": post_url,
            "back_url": back_url,
            "require_admin_password": True,
            "error": error,
            "attachment": attachment,
        },
    )


def _get_safe_next_url(request, default_url: str) -> str:
    candidate = (request.POST.get("next") or request.GET.get("next") or "").strip()
    if candidate and url_has_allowed_host_and_scheme(
        candidate,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        return candidate
    return default_url


def _admin_visible_units():
    active_lease_exists = Lease.objects.filter(unit_id=OuterRef('pk'), is_active=True)
    return Unit.objects.annotate(
        has_active_lease=Exists(active_lease_exists)
    ).filter(
        Q(is_active=True) |
        Q(status='MAINTENANCE') |
        Q(has_active_lease=True)
    )


def _sync_unit_active_state(unit, *, previous_status=None, previous_is_active=True):
    if unit.status == 'MAINTENANCE':
        unit.is_active = False
    elif not previous_is_active and unit.status == previous_status:
        unit.is_active = False
    else:
        unit.is_active = True


logger = logging.getLogger(__name__)


def _admin_display_unit_type(unit_type: str) -> str:
    normalized = (unit_type or "").strip().upper()
    if normalized == "1BR" or normalized == "STUDIO":
        return "1 Bedroom"
    if normalized in {"2BR", "3BR", "PENTHOUSE"}:
        return "2 Bedrooms"
    return unit_type or ""


@admin_required
def admin_dashboard(request):
    active_leases = Lease.objects.filter(status=Lease.STATUS_ACTIVE)
    lease_counts = active_leases.aggregate(
        total_tenants=Count("tenant", distinct=True),
        occupied_units=Count("id"),
    )
    total_tenants = lease_counts["total_tenants"]
    occupied_units = lease_counts["occupied_units"]
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
def admin_units(request):
    """Admin portal: list all units with filtering."""
    status_filter = request.GET.get('status', 'all')
    search_query = request.GET.get('search', '')
    image_prefetch = Prefetch(
        'images',
        queryset=UnitImage.objects.order_by('-is_primary', 'order', 'created_at'),
    )
    active_lease_prefetch = Prefetch(
        'lease_set',
        queryset=Lease.objects.filter(
            status__in=[Lease.STATUS_ACTIVE, Lease.STATUS_PENDING_PAYMENT]
        ).select_related('tenant__tenantprofile').order_by('-is_active', '-start_date', '-id'),
        to_attr='admin_display_leases',
    )
    
    active_lease_exists = Lease.objects.filter(
        unit_id=OuterRef('pk'),
        status=Lease.STATUS_ACTIVE,
        is_active=True,
    )

    # Handle filter logic
    if status_filter == 'MAINTENANCE':
        # Show rooms marked maintenance plus inactive occupied rooms still tied to an active lease.
        units = Unit.objects.annotate(
            has_active_lease=Exists(active_lease_exists)
        ).filter(
            Q(status='MAINTENANCE') |
            Q(is_active=False, has_active_lease=True)
        ).prefetch_related(image_prefetch, active_lease_prefetch)
    else:
        units = Unit.objects.filter(is_active=True).annotate(
            has_active_lease=Exists(active_lease_exists)
        ).prefetch_related(image_prefetch, active_lease_prefetch)
        # Filter by status
        if status_filter == 'OCCUPIED':
            units = units.filter(has_active_lease=True)
        elif status_filter == 'AVAILABLE':
            units = units.filter(has_active_lease=False).exclude(status='MAINTENANCE')
        elif status_filter != 'all':
            units = units.filter(status=status_filter)
    
    # Search functionality
    if search_query:
        units = units.filter(
            Q(number__icontains=search_query) |
            Q(unit_type__icontains=search_query) |
            Q(description__icontains=search_query)
        )
    
    from django.core.paginator import Paginator
    
    active_unit_ids = Lease.objects.filter(
        status=Lease.STATUS_ACTIVE,
        is_active=True,
    ).values("unit_id").distinct()
    total_units_count = Unit.objects.filter(is_active=True).count()
    occupied_units_count = active_unit_ids.count()
    maintenance_units_count = Unit.objects.filter(
        Q(status='MAINTENANCE') | Q(is_active=False, lease__is_active=True)
    ).distinct().count()
    available_units_count = (
        Unit.objects.filter(is_active=True)
        .exclude(id__in=active_unit_ids)
        .exclude(status='MAINTENANCE')
        .count()
    )
    
    # Pagination (6 per page)
    paginator = Paginator(units, 6)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    for unit in page_obj:
        prefetched_images = list(getattr(unit, 'images').all()) if hasattr(unit, 'images') else []
        cover_image = next((image for image in prefetched_images if image.is_primary), None)
        if cover_image is None and prefetched_images:
            cover_image = prefetched_images[0]
        unit.cover_image_url = cover_image.image.url if cover_image and cover_image.image else ""
        unit.display_unit_type = _admin_display_unit_type(unit.unit_type)
        unit.cover_image_label = ""
        if not unit.cover_image_url:
            if unit.unit_type == "1BR":
                unit.cover_image_url = "https://ezrxfodgrztlajiiilfz.supabase.co/storage/v1/object/public/unit-images/placeholders/cdd906739ed64fb78aaf8d41b078feea.jpg"
            else:
                unit.cover_image_label = unit.display_unit_type
        display_leases = getattr(unit, 'admin_display_leases', [])
        active_lease = next(
            (
                lease for lease in display_leases
                if lease.is_active or lease.status == Lease.STATUS_ACTIVE
            ),
            None,
        )
        pending_lease = next(
            (
                lease for lease in display_leases
                if lease.status == Lease.STATUS_PENDING_PAYMENT
            ),
            None,
        )
        unit.current_tenant = active_lease.tenant if active_lease else None
        unit.pending_lease = pending_lease
        unit.pending_tenant = pending_lease.tenant if pending_lease else None
        if active_lease:
            unit.display_status_label = "Occupied"
        elif pending_lease:
            unit.display_status_label = "Pending Payment"
        elif unit.status == "MAINTENANCE" or not unit.is_active:
            unit.display_status_label = "Under Maintenance"
        else:
            unit.display_status_label = "Available"
    
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
    unit = get_object_or_404(_admin_visible_units(), id=unit_id)
    default_back_url = reverse("admin_units")
    back_url = _get_safe_next_url(request, default_back_url)
    edit_url = f"{reverse('admin_edit_unit', args=[unit.id])}?next={quote(back_url, safe='')}"
    active_lease = (
        Lease.objects.filter(unit=unit, status=Lease.STATUS_ACTIVE, is_active=True)
        .select_related('tenant__tenantprofile')
        .order_by('-start_date', '-id')
        .first()
    )
    current_tenant = active_lease.tenant if active_lease else None
    pending_lease = (
        Lease.objects.filter(unit=unit, status=Lease.STATUS_PENDING_PAYMENT)
        .select_related('tenant__tenantprofile')
        .order_by('-start_date', '-id')
        .first()
    )
    unit_images = unit.get_all_images()
    if current_tenant:
        display_status_label = "Occupied"
    elif pending_lease:
        display_status_label = "Pending Payment"
    elif unit.status == "MAINTENANCE" or not unit.is_active:
        display_status_label = "Under Maintenance"
    else:
        display_status_label = "Available"
    unit.display_unit_type = _admin_display_unit_type(unit.unit_type)
    
    return render(request, "admin_portal/unit_detail.html", {
        'unit': unit,
        'current_tenant': current_tenant,
        'pending_lease': pending_lease,
        'pending_tenant': pending_lease.tenant if pending_lease else None,
        'display_status_label': display_status_label,
        'unit_images': unit_images,
        'amenities_list': unit.get_amenities_list(),
        'back_url': back_url,
        'edit_url': edit_url,
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
                        recipient_type="ADMIN",
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
    unit = get_object_or_404(_admin_visible_units(), id=unit_id)
    default_back_url = reverse("admin_units")
    back_url = _get_safe_next_url(request, default_back_url)
    
    if request.method == "POST":
        previous_status = unit.status
        previous_is_active = unit.is_active
        form = UnitForm(request.POST, instance=unit)
        
        if form.is_valid():
            try:
                unit = form.save(commit=False)
                _sync_unit_active_state(
                    unit,
                    previous_status=previous_status,
                    previous_is_active=previous_is_active,
                )
                unit.save()
                
                # Handle image uploads and deletions
                handle_image_uploads(request, unit)
                handle_image_deletions(request, unit)

                messages.success(request, f'Unit {unit.number} has been updated successfully!')
                detail_url = f"{reverse('admin_unit_detail', args=[unit.id])}?next={quote(back_url, safe='')}"
                return redirect(detail_url)
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
        "back_url": back_url,
        "next_url": back_url,
        "unit_images": unit.get_all_images(),
    })


@admin_required
def admin_delete_unit(request, unit_id):
    """Admin portal: delete a Unit row (soft delete)."""
    unit = get_object_or_404(Unit, id=unit_id)
    
    if request.method == "POST":
        if not admin_password_verified(request):
            return render_admin_password_confirm(
                request,
                title="Delete Unit",
                message=f"Delete unit {unit.number}? This will mark it as inactive but preserve all historical data.",
                post_url=reverse("admin_delete_unit", args=[unit.id]),
                back_url=reverse("admin_unit_detail", args=[unit.id]),
                error="Incorrect admin password. Unit deletion was not completed.",
            )
        unit.is_active = False
        unit.save()
        messages.success(request, f'Unit {unit.number} has been deleted successfully!')
        return redirect("admin_units")
    
    return render_admin_password_confirm(
        request,
        title="Delete Unit",
        message=f"Delete unit {unit.number}? This will mark it as inactive but preserve all historical data.",
        post_url=reverse("admin_delete_unit", args=[unit.id]),
        back_url=reverse("admin_unit_detail", args=[unit.id]),
    )


@admin_required
def admin_restore_unit(request, unit_id):
    """Admin portal: show a previously hidden Unit row again."""
    unit = get_object_or_404(_admin_visible_units(), id=unit_id)

    if request.method == "POST":
        unit.is_active = True
        unit.save(update_fields=["is_active"])
        messages.success(request, f'Unit {unit.number} is now visible in the room list.')

    return redirect("admin_unit_detail", unit_id=unit.id)


@admin_required
def admin_toggle_unit_status(request, unit_id):
    """Admin portal: toggle unit status."""
    unit = get_object_or_404(_admin_visible_units(), id=unit_id)
    
    if request.method == "POST":
        new_status = request.POST.get('status')
        if new_status in ['AVAILABLE', 'OCCUPIED', 'MAINTENANCE']:
            unit.status = new_status
            _sync_unit_active_state(unit)
            unit.save()
            messages.success(request, f'Unit {unit.number} status changed to {new_status}!')
        
        return redirect("admin_unit_detail", unit_id=unit.id)
    
    return redirect("admin_unit_detail", unit_id=unit.id)




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
        if not admin_password_verified(request):
            return render_admin_password_confirm(
                request,
                title="Delete Announcement",
                message=f"Delete announcement {ann.title}?",
                post_url=reverse("admin_delete_announcement", args=[ann.id]),
                back_url=reverse("admin_announcements"),
                error="Incorrect admin password. Announcement deletion was not completed.",
            )
        ann.delete()
        return redirect("admin_announcements")
    return render_admin_password_confirm(
        request,
        title="Delete Announcement",
        message=f"Delete announcement {ann.title}?",
        post_url=reverse("admin_delete_announcement", args=[ann.id]),
        back_url=reverse("admin_announcements"),
    )




@admin_required
def admin_tenant_risk(request):
    """Tenant Risk Classification view"""
    q = request.GET.get("q", "").strip()
    risk_filter = request.GET.get("risk", "").strip()
    
    # Get all tenant risk classifications
    risk_classifications = TenantRiskClassification.objects.select_related(
        'tenant',
        'tenant__tenantprofile',
    ).all()
    
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
            logger.exception("Tenant risk refresh failed: %s", e)
            messages.warning(
                request,
                "Risk refresh could not fully complete. The rule-based fallback remains available; check server logs for details.",
            )
    
    return redirect('admin_tenant_risk')


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



