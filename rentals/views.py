from datetime import date, timedelta
from decimal import Decimal
from functools import lru_cache

from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import connection, models
from django.db.models import F, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone

from announcements.models import Announcement
from billing.models import MonthlyBill
from billing.services import (
    add_months,
    reconcile_approved_payments_for_tenant,
    ensure_bills_since_move_in,
    ensure_bills_up_to,
    get_or_update_monthly_bill,
    month_start,
    parse_bill_ids,
)
from payments.models import ManualPayment
from payments.views import manual_gcash_payment

from .models import Lease, Notification, TenantProfile, Unit

# Temporary inline form to resolve import issue
class UnitForm(forms.ModelForm):
    class Meta:
        model = Unit
        fields = [
            'number', 'unit_type', 'floor_level', 'size_sqm', 
            'monthly_rent', 'status', 'description', 'amenities'
        ]
        widgets = {
            'number': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'e.g., 101, A-201'
            }),
            'unit_type': forms.Select(attrs={
                'class': 'form-control'
            }),
            'floor_level': forms.NumberInput(attrs={
                'class': 'form-control',
                'min': '1',
                'max': '50'
            }),
            'size_sqm': forms.NumberInput(attrs={
                'class': 'form-control',
                'step': '0.01',
                'min': '10'
            }),
            'monthly_rent': forms.NumberInput(attrs={
                'class': 'form-control',
                'step': '0.01',
                'min': '1000'
            }),
            'status': forms.Select(attrs={
                'class': 'form-control'
            }),
            'description': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': '3',
                'placeholder': 'Describe unit features, location, etc.'
            }),
            'amenities': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': '2',
                'placeholder': 'e.g., Air Conditioning, WiFi, Parking, Swimming Pool'
            }),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field_name, field in self.fields.items():
            field.widget.attrs.update({'class': field.widget.attrs.get('class', '') + ' tenant-form-input'})
            if field.required:
                field.widget.attrs.update({'required': 'required'})

    def clean_number(self):
        number = self.cleaned_data.get('number')
        if number:
            return number.upper().strip()
        return number

    def clean_monthly_rent(self):
        rent = self.cleaned_data.get('monthly_rent')
        if rent and rent < 1000:
            raise forms.ValidationError('Monthly rent must be at least ₱1,000')
        return rent

    def clean_size_sqm(self):
        size = self.cleaned_data.get('size_sqm')
        if size and size < 10:
            raise forms.ValidationError('Unit size must be at least 10 sqm')
        return size

    def clean_amenities(self):
        amenities = self.cleaned_data.get('amenities')
        if amenities:
            # Clean up the amenities string
            amenities_list = [item.strip() for item in amenities.split(',') if item.strip()]
            return ', '.join(amenities_list)
        return amenities


@login_required
def tenant_dashboard(request):
    """
    Main landing page for tenants. Synchronizes all billing and displays
    the current status, rent, and announcements.
    """
    user = request.user
    profile = TenantProfile.objects.filter(user=user).first()
    today = timezone.localdate()

    # Get all leases for unit switcher (including future start dates, excluding ended ones)
    # Include both ACTIVE and PENDING_PAYMENT leases
    all_active_leases = Lease.objects.filter(
        tenant=user,
    ).filter(
        Q(end_date__isnull=True) | Q(end_date__gte=today)
    ).filter(
        Q(status=Lease.STATUS_ACTIVE) | Q(status=Lease.STATUS_PENDING_PAYMENT)
    ).select_related("unit").order_by('-start_date')

    # Allow switching via ?lease_id=XX
    selected_lease_id = request.GET.get('lease_id')
    if selected_lease_id:
        lease = all_active_leases.filter(pk=selected_lease_id).first()
    else:
        # Default to the most recent lease that has already started
        lease = all_active_leases.filter(start_date__lte=today).first()
        if not lease:
            lease = all_active_leases.first()

    announcements = Announcement.objects.filter(is_active=True).order_by("-created_at")[:5]

    current_balance = None
    show_paid_hero = False
    paid_hero_month = None
    next_due_date = None
    next_billing_month = None
    next_bill_preview = None
    total_balance_due = None

    # Calculate total monthly rent including parking
    total_monthly_rent = None
    if lease:
        total_monthly_rent = lease.monthly_rent + lease.parking_fee

    # Only generate bills for ACTIVE leases, not pending ones
    if lease and lease.status == Lease.STATUS_ACTIVE:
        reconcile_approved_payments_for_tenant(user)
        ensure_bills_since_move_in(lease)
        # Get all bills with unpaid balances (including partial payments)
        all_bills = list(MonthlyBill.objects.filter(lease=lease).order_by("billing_month"))
        
        # Calculate total unpaid balance across all bills (for summary)
        total_unpaid_rent = sum(b.rent_balance for b in all_bills if b.rent_balance > 0)
        total_unpaid_water = sum(b.water_balance for b in all_bills if b.water_balance > 0)
        total_balance_due = total_unpaid_rent + total_unpaid_water
        
        # Get first bill with remaining balance - total_balance is the source of truth
        actual_balance = None
        for bill in all_bills:
            if bill.total_balance > 0:
                actual_balance = get_or_update_monthly_bill(lease, bill.billing_month)
                break

        today_start = month_start(today)
        # Surface the red billing card only for current/past due balances or
        # within the 7-day reminder window before the due date.
        if actual_balance:
            days_until_due = (actual_balance.due_date - today).days
            should_show_due_card = (
                actual_balance.billing_month <= today_start or days_until_due <= 7
            )

            if should_show_due_card:
                current_balance = actual_balance
            else:
                show_paid_hero = True
                paid_hero_month = today_start

        # Find the actual "next" bill after the displayed balance, or use the
        # next unpaid future bill as preview when the current cycle is already paid.
        if current_balance:
            next_bill = next(
                (bill for bill in all_bills if bill.billing_month > current_balance.billing_month),
                None,
            )
            
            if next_bill:
                next_billing_month = next_bill.billing_month
                next_due_date = next_bill.due_date
            else:
                # No next bill exists yet, generate it
                next_month_date = add_months(current_balance.billing_month, 1)
                next_bill = get_or_update_monthly_bill(lease, next_month_date)
                if next_bill:
                    next_billing_month = next_bill.billing_month
                    next_due_date = next_bill.due_date
            next_bill_preview = next_bill
        elif actual_balance:
            show_paid_hero = True
            paid_hero_month = today_start
            next_bill_preview = actual_balance
            next_billing_month = actual_balance.billing_month
            next_due_date = actual_balance.due_date
        else:
            # No unpaid balances at all, show a paid hero and preview the next bill.
            show_paid_hero = True
            paid_hero_month = today_start
            next_month = add_months(today_start, 1)
            ensure_bills_up_to(lease, next_month)
            
            next_bill = MonthlyBill.objects.filter(lease=lease, billing_month=next_month).first()
            if next_bill:
                next_billing_month = next_bill.billing_month
                next_due_date = next_bill.due_date
                next_bill_preview = next_bill

    # Get tenant's recent payments (pending and approved)
    recent_payments = []
    move_in_payment = None
    has_pending_payment = False
    if request.user.is_authenticated:
        recent_payments = ManualPayment.objects.filter(
            user=request.user
        ).order_by("-created_at")[:5]
        move_in_payment = ManualPayment.objects.filter(
            user=request.user, payment_type="move_in"
        ).first()
        has_pending_payment = ManualPayment.objects.filter(
            user=request.user, status="PENDING"
        ).exists()
    
    context = {
        "profile": profile,
        "lease": lease,
        "total_monthly_rent": total_monthly_rent,
        "all_active_leases": all_active_leases,
        "announcements": announcements,
        "current_balance": current_balance,
        "show_paid_hero": show_paid_hero,
        "paid_hero_month": paid_hero_month,
        "total_balance_due": total_balance_due if lease else None,
        "next_due_date": next_due_date,
        "next_billing_month": next_billing_month,
        "next_bill_preview": next_bill_preview,
        "recent_payments": recent_payments,
        "move_in_payment": move_in_payment,
        "has_pending_payment": has_pending_payment,
    }
    return render(request, "rentals/tenant_dashboard.html", context)


@login_required
def tenant_billing(request):
    """
    Detailed billing statement showing breakdown of rent, water utility, and penalties.
    """
    user = request.user
    today = timezone.localdate()
    lease = Lease.objects.filter(
        tenant=user,
        start_date__lte=today,
    ).filter(
        Q(end_date__isnull=True) | Q(end_date__gte=today)
    ).select_related("unit").order_by('-start_date').first()

    if not lease:
        messages.warning(request, "An active lease is required to view billing.")
        return redirect("tenant_dashboard")

    reconcile_approved_payments_for_tenant(user)
    ensure_bills_since_move_in(lease)

    # Get filter parameters
    month_filter = request.GET.get("month", "").strip()
    year_filter = request.GET.get("year", "").strip()

    # Start with all bills for this tenant (include PARTIALLY_PAID)
    bills_query = MonthlyBill.objects.filter(
        lease=lease
    ).exclude(status="PAID").select_related("source_water_reading").order_by("-billing_month")

    # Apply filters
    if month_filter and month_filter.isdigit():
        bills_query = bills_query.filter(billing_month__month=int(month_filter))

    if year_filter and year_filter.isdigit():
        bills_query = bills_query.filter(billing_month__year=int(year_filter))

    current_bill = bills_query.filter(status__in=["UNPAID", "PARTIALLY_PAID"]).order_by("billing_month").first()

    water_reading = None
    if current_bill:
        current_bill = get_or_update_monthly_bill(lease, current_bill.billing_month)
        # Fetch water reading details if available
        if current_bill.source_water_reading:
            water_reading = current_bill.source_water_reading

    all_bills = bills_query.filter(status__in=["UNPAID", "PARTIALLY_PAID"]).order_by("billing_month")
    ongoing_rows = []
    today = date.today()

    for bill in all_bills:
        bill = get_or_update_monthly_bill(lease, bill.billing_month)

        if bill.due_date < today:
            display_status = "OVERDUE"
        elif bill.due_date == today:
            display_status = "DUE_TODAY"
        else:
            display_status = "UPCOMING"

        if display_status == "UPCOMING":
            continue

        # Get water reading for this ongoing bill if exists
        bill_water = bill.source_water_reading if bill.source_water_reading else None
        
        ongoing_rows.append({
            "month_label": bill.billing_month.strftime("%B %Y"),
            "rent": bill.base_rent,
            "water": bill.water_amount,
            "water_reading": bill_water,
            "penalty": bill.interest,
            "total": bill.total_due,
            "due_date": bill.due_date,
            "status": display_status,
        })

    approved_payments = ManualPayment.objects.filter(
        user=user,
        status="APPROVED",
    ).order_by("-created_at")

    transactions = []
    payment_bill_ids = []
    payment_bill_map = {}
    for payment in approved_payments:
        bill_id_list = parse_bill_ids(payment.bill_ids)
        if not bill_id_list:
            continue
        payment_bill_ids.extend(bill_id_list)
        payment_bill_map[payment.id] = bill_id_list

    bills_by_id = {
        bill.id: bill
        for bill in MonthlyBill.objects.filter(id__in=payment_bill_ids)
    }

    for payment in approved_payments:
        bill_id_list = payment_bill_map.get(payment.id)
        if not bill_id_list:
            continue

        bills_paid = [bills_by_id[bill_id] for bill_id in bill_id_list if bill_id in bills_by_id]
        
        # Use stored amount if available, otherwise calculate from bills (for old payments)
        if payment.amount and payment.amount > 0:
            total_amount = payment.amount
        else:
            total_amount = sum((bill.total_due or Decimal("0.00")) for bill in bills_paid)

        transactions.append({
            "paid_at": payment.created_at,
            "reference": payment.reference_code,
            "months_paid": len(bills_paid),
            "total_amount": total_amount,
        })

    # Generate month and year choices
    current_year = timezone.now().year
    month_choices = [
        (1, 'January'), (2, 'February'), (3, 'March'), (4, 'April'),
        (5, 'May'), (6, 'June'), (7, 'July'), (8, 'August'),
        (9, 'September'), (10, 'October'), (11, 'November'), (12, 'December')
    ]
    year_choices = list(range(current_year - 3, current_year + 2))  # Last 3 years and next year

    has_pending_payment = ManualPayment.objects.filter(
        user=request.user, status="PENDING"
    ).exists()

    return render(request, "billing/tenant_billing.html", {
        "lease": lease,
        "current_bill": current_bill,
        "water_reading": water_reading,
        "ongoing_rows": ongoing_rows,
        "transactions": transactions,
        "month_filter": month_filter,
        "year_filter": year_filter,
        "month_choices": month_choices,
        "year_choices": year_choices,
        "has_pending_payment": has_pending_payment,
    })


@login_required
def tenant_pay_advance(request):
    """
    View to handle the Make Payment page.
    Supports partial payments: rent only, water only, or full payment.
    """
    # Check if user just returned from a cancelled PayMongo payment
    # PayMongo redirects back to cancel_url when user clicks back arrow or closes checkout
    referrer = request.META.get('HTTP_REFERER', '')
    cancelled_param = request.GET.get('cancelled')
    
    if 'paymongo' in referrer.lower() or cancelled_param == '1':
        messages.info(request, "Payment cancelled. You can try again or choose a different payment method.")
    
    today = timezone.localdate()
    lease = Lease.objects.filter(
        tenant=request.user,
        start_date__lte=today,
    ).filter(
        Q(end_date__isnull=True) | Q(end_date__gte=today)
    ).order_by('-start_date').first()

    if not lease:
        messages.warning(request, "An active lease is required to make a payment.")
        return redirect("tenant_dashboard")

    try:
        months_to_pay = int(request.GET.get("months_to_pay", 1))
    except ValueError:
        months_to_pay = 1

    reconcile_approved_payments_for_tenant(request.user)
    ensure_bills_since_move_in(lease)

    existing_bills = list(MonthlyBill.objects.filter(lease=lease).order_by("billing_month"))
    oldest_outstanding_bill = existing_bills[0] if existing_bills else None
    for candidate_bill in existing_bills:
        if candidate_bill.total_balance > 0:
            oldest_outstanding_bill = candidate_bill
            break

    water_only_locked = bool(
        oldest_outstanding_bill
        and oldest_outstanding_bill.total_balance > 0
        and oldest_outstanding_bill.water_balance > 0
        and oldest_outstanding_bill.rent_balance == 0
        and oldest_outstanding_bill.parking_balance == 0
    )

    # Get payment type from request (rent_only, water_only, full)
    requested_payment_type = request.GET.get("payment_type", "full")
    payment_type = "water_only" if water_only_locked else requested_payment_type

    today = date.today()
    
    # Ensure bills exist up to next months for advance payment capability
    today_start = month_start(today)
    ensure_bills_up_to(lease, add_months(today_start, months_to_pay + 1))
    
    # For partial payments, include bills that have balance for that type
    # Get all bills ordered by month
    all_bills = list(MonthlyBill.objects.filter(lease=lease).order_by("billing_month"))
    
    if payment_type == "rent_only":
        # Filter to bills with unpaid rent, then slice
        bills_with_unpaid_rent = [b for b in all_bills if b.rent_balance > 0]
        bills_to_process = bills_with_unpaid_rent[:months_to_pay]
        # If no unpaid rent bills but user wants to pay in advance, get future bills
        if not bills_to_process:
            future_bills = [b for b in all_bills if b.rent_balance > 0 or b.status == "UPCOMING"]
            bills_to_process = future_bills[:months_to_pay]
    elif payment_type == "water_only":
        # Filter to bills with unpaid water, then slice
        bills_with_unpaid_water = [b for b in all_bills if b.water_balance > 0]
        bills_to_process = bills_with_unpaid_water[:months_to_pay]
        # If no unpaid water bills but user wants to pay in advance, get future bills
        if not bills_to_process:
            future_bills = [b for b in all_bills if b.water_balance > 0 or b.status == "UPCOMING"]
            bills_to_process = future_bills[:months_to_pay]
    else:
        # Full payment - include UNPAID and PARTIALLY_PAID bills (total_balance > 0)
        all_unpaid_bills = [
            bill for bill in all_bills
            if bill.status in ["UNPAID", "PARTIALLY_PAID"]
        ]
        bills_to_process = all_unpaid_bills[:months_to_pay]
        # If no unpaid bills but user wants to pay in advance, get future upcoming bills
        if not bills_to_process:
            # Get upcoming/future bills for advance payment
            future_bills = [
                bill for bill in all_bills
                if bill.status in ["UNPAID", "UPCOMING"] or bill.billing_month > today_start
            ]
            bills_to_process = future_bills[:months_to_pay]

    # Count truly unpaid bills for warning
    unpaid_count = sum(
        1 for bill in all_bills
        if bill.status == "UNPAID" and bill.due_date <= today
    )
    has_pending = unpaid_count > 0
    
    # Check if water bills are available (water_amount > 0 on any bill)
    water_available = any(
        bill.billing_month >= today_start and bill.water_amount > 0
        for bill in all_bills
    )

    preview_rows = []
    total_rent = Decimal("0.00")
    total_water = Decimal("0.00")
    total_parking = Decimal("0.00")
    total_penalty = Decimal("0.00")
    total_amount = Decimal("0.00")

    for bill in bills_to_process:
        bill = get_or_update_monthly_bill(lease, bill.billing_month)
        
        # Calculate what tenant will actually pay based on payment type
        if payment_type == "rent_only":
            # Rent Only = Rent + Parking (both are monthly recurring fees)
            pay_rent = bill.rent_balance
            pay_water = Decimal("0.00")
            pay_parking = bill.parking_balance  # Include parking in rent-only payments
            pay_penalty = Decimal("0.00")  # Penalty only on full payment
            display_rent = float(pay_rent)
            display_water = 0
            display_parking = float(pay_parking)
        elif payment_type == "water_only":
            pay_rent = Decimal("0.00")
            pay_water = bill.water_balance
            pay_parking = Decimal("0.00")
            pay_penalty = Decimal("0.00")
            display_rent = 0
            display_water = float(pay_water)
            display_parking = 0
        else:
            # Full payment - pay all remaining balances including interest and parking
            pay_rent = bill.rent_balance
            pay_water = bill.water_balance
            pay_parking = bill.parking_balance
            pay_penalty = bill.interest  # Include late interest in full payment
            # For display, show full bill amounts
            display_rent = float(bill.base_rent)
            display_water = float(bill.water_amount or 0)
            display_parking = float(bill.parking_fee or 0)
        
        row = {
            "bill_id": bill.id,
            "month_label": bill.billing_month.strftime("%B %Y"),
            "rent": float(bill.base_rent),
            "water": float(bill.water_amount or 0),
            "parking": float(bill.parking_fee or 0),
            "penalty": float(bill.interest or 0),
            "pay_rent": float(pay_rent),
            "pay_water": float(pay_water),
            "pay_parking": float(pay_parking),
            "pay_penalty": float(pay_penalty),
            "pay_total": float(pay_rent + pay_parking) if payment_type == "rent_only" else float(pay_water) if payment_type == "water_only" else float(pay_rent + pay_water + pay_parking + pay_penalty),
            "display_rent": display_rent,
            "display_water": display_water,
            "display_parking": display_parking,
            "due_date": bill.due_date,
        }
        preview_rows.append(row)

    total_rent = sum(row["display_rent"] if payment_type == "full" else row["pay_rent"] for row in preview_rows)
    total_water = sum(row["display_water"] if payment_type == "full" else row["pay_water"] for row in preview_rows)
    total_parking = sum(row["display_parking"] if payment_type == "full" else row["pay_parking"] for row in preview_rows)
    total_penalty = sum(row["pay_penalty"] for row in preview_rows)
    total_amount = sum(row["pay_total"] for row in preview_rows)

    context = {
        "lease": lease,
        "months_options": [1, 2, 3, 4, 5, 6, 12],
        "months_to_pay": months_to_pay,
        "payment_type": payment_type,
        "water_only_locked": water_only_locked,
        "has_pending": has_pending,
        "unpaid_count": unpaid_count,
        "water_available": water_available,
        "total_rent": total_rent,
        "total_water": total_water,
        "total_parking": total_parking,
        "total_penalty": total_penalty,
        "total_amount": total_amount,
        "preview_rows": preview_rows,
    }

    if request.method == "POST":
        url = reverse("manual_gcash_payment")
        # Pass payment type to payment processor
        bill_ids = ",".join(str(row["bill_id"]) for row in preview_rows)
        return redirect(f"{url}?amount={total_amount}&bill_ids={bill_ids}&payment_type={payment_type}")

    return render(request, "billing/tenant_pay_advance.html", context)


@login_required
def mark_unit_welcome_seen(request):
    """Mark the unit welcome popup as seen for the current tenant"""
    if request.method == "POST":
        try:
            # Get the tenant's profile
            tenant_profile = get_object_or_404(TenantProfile, user=request.user)
            tenant_profile.has_seen_unit_welcome = True
            tenant_profile.save()
            
            from django.http import JsonResponse
            return JsonResponse({"success": True, "message": "Welcome popup marked as seen"})
        except Exception as e:
            from django.http import JsonResponse
            return JsonResponse({"success": False, "message": str(e)})
    
    # Only accept POST requests
    from django.http import JsonResponse
    return JsonResponse({"success": False, "message": "Method not allowed"})


@login_required
def tenant_notifications(request):
    """
    Display all notifications for the current tenant.
    Unread notifications are shown first, sorted by creation date.
    """
    purge_read_notifications_for_tenant(request.user)

    # Get notifications for this tenant
    base_notifications = Notification.objects.filter(
        recipient_type='TENANT',
        user=request.user
    )
    notifications = base_notifications
    
    # Handle filtering
    status_filter = request.GET.get('status', 'all')
    if status_filter == 'unread':
        notifications = notifications.filter(is_read=False)
    elif status_filter == 'read':
        notifications = notifications.filter(is_read=True)
        
    notifications = notifications.order_by('is_read', '-created_at')
    
    # Calculate unread count (unfiltered)
    unread_count = base_notifications.filter(is_read=False).count()
    
    context = {
        "notifications": notifications,
        "unread_count": unread_count,
        "status_filter": status_filter,
    }
    return render(request, "rentals/tenant_notifications.html", context)


@lru_cache(maxsize=1)
def notification_has_read_at_column() -> bool:
    """Return True when the notifications table already has the read_at column."""
    with connection.cursor() as cursor:
        columns = connection.introspection.get_table_description(cursor, Notification._meta.db_table)
    return any(column.name == "read_at" for column in columns)


@login_required
def mark_notification_read(request, notification_id):
    """
    Mark a specific notification as read.
    Supports both POST (AJAX) and regular form submit requests.
    """
    notification = get_object_or_404(
        Notification,
        id=notification_id,
        recipient_type='TENANT',
        user=request.user
    )

    notification.is_read = True
    if notification_has_read_at_column():
        notification.read_at = timezone.now()
        notification.save(update_fields=["is_read", "read_at"])
    else:
        notification.save(update_fields=["is_read"])

    # Check if this is an AJAX request (fetch/XHR)
    is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'

    if is_ajax:
        from django.http import JsonResponse
        return JsonResponse({"success": True, "message": "Notification marked as read"})
    else:
        # Regular form submit - redirect back to notifications page
        messages.success(request, "Notification marked as read.")
        return redirect('tenant_notifications')


@login_required
def mark_all_notifications_read(request):
    """Mark all tenant notifications as read for the current user."""
    if request.method != "POST":
        return redirect("tenant_notifications")

    read_time = timezone.now()
    unread_notifications = Notification.objects.filter(
        recipient_type='TENANT',
        user=request.user,
        is_read=False,
    )
    if notification_has_read_at_column():
        updated_count = unread_notifications.update(is_read=True, read_at=read_time)
    else:
        updated_count = unread_notifications.update(is_read=True)

    messages.success(
        request,
        f"Marked {updated_count} notification{'' if updated_count == 1 else 's'} as read."
    )
    return redirect("tenant_notifications")


def purge_read_notifications_for_tenant(user):
    """Delete tenant notifications that have been read for over 24 hours."""
    if not notification_has_read_at_column():
        return

    cutoff = timezone.now() - timedelta(days=1)
    Notification.objects.filter(
        recipient_type='TENANT',
        user=user,
        is_read=True,
        read_at__lte=cutoff,
    ).delete()


