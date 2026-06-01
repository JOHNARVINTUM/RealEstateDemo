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
from rentals.models import Lease, Unit, TenantProfile, Notification, TenantRiskClassification, Room
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
from django.contrib.auth.decorators import user_passes_test

def admin_required(view_func):
    """
    Decorator to ensure user is authenticated and has ADMIN role
    """
    def check(user):
        return user.is_authenticated and (getattr(user, "role", "") == "ADMIN" or user.is_superuser)
    return user_passes_test(check)(view_func)


def admin_password_verified(request) -> bool:
    return request.user.check_password((request.POST.get("admin_password") or "").strip())


def render_admin_password_confirm(request, *, title, message, post_url, back_url, error=None):
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
        },
    )


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
def admin_units(request):
    """Admin portal: list all units with filtering."""
    status_filter = request.GET.get('status', 'all')
    search_query = request.GET.get('search', '')
    
    # Handle filter logic
    if status_filter == 'MAINTENANCE':
        # Show both MAINTENANCE status units AND inactive units (both count as "Being Fixed")
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



