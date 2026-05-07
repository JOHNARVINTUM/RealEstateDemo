from datetime import date
from decimal import Decimal

from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import models
from django.db.models import F
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse

from announcements.models import Announcement
from billing.models import MonthlyBill
from billing.services import (
    add_months,
    ensure_bills_since_move_in,
    ensure_bills_up_to,
    get_or_update_monthly_bill,
    month_start,
    parse_bill_ids,
)
from payments.models import ManualPayment
from payments.views import manual_gcash_payment

from .models import Lease, TenantProfile, Unit

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
    lease = Lease.objects.filter(tenant=user, is_active=True).select_related("unit").first()
    announcements = Announcement.objects.filter(is_active=True).order_by("-created_at")[:5]

    current_balance = None
    next_due_date = None
    next_billing_month = None

    if lease:
        ensure_bills_since_move_in(lease)

        # Get all bills with unpaid balances (including partial payments)
        all_bills = MonthlyBill.objects.filter(lease=lease).order_by("billing_month")
        
        # Calculate total unpaid balance across all bills (for summary)
        total_unpaid_rent = sum(b.rent_balance for b in all_bills if b.rent_balance > 0)
        total_unpaid_water = sum(b.water_balance for b in all_bills if b.water_balance > 0)
        total_balance_due = total_unpaid_rent + total_unpaid_water
        
        # Get first bill with remaining balance - total_balance is the source of truth
        current_balance = None
        for bill in all_bills:
            if bill.total_balance > 0:
                current_balance = get_or_update_monthly_bill(lease, bill.billing_month)
                break
        
        # If no unpaid bills, show the next month's bill (for preview)
        if current_balance is None:
            # Get the last bill to find the next month
            last_bill = all_bills.last()
            if last_bill:
                next_month_date = add_months(last_bill.billing_month, 1)
                current_balance = MonthlyBill.objects.filter(
                    lease=lease, 
                    billing_month=next_month_date
                ).first()

        today_start = month_start(date.today())
        next_month = add_months(today_start, 1)
        ensure_bills_up_to(lease, next_month)

        next_bill = MonthlyBill.objects.filter(lease=lease, billing_month=next_month).first()
        if next_bill:
            next_billing_month = next_bill.billing_month
            next_due_date = next_bill.due_date

    # Get tenant's recent payments (pending and approved)
    recent_payments = []
    if request.user.is_authenticated:
        recent_payments = ManualPayment.objects.filter(
            user=request.user
        ).order_by("-created_at")[:5]
    
    context = {
        "profile": profile,
        "lease": lease,
        "announcements": announcements,
        "current_balance": current_balance,
        "total_balance_due": total_balance_due if lease else None,
        "next_due_date": next_due_date,
        "next_billing_month": next_billing_month,
        "recent_payments": recent_payments,
    }
    return render(request, "rentals/tenant_dashboard.html", context)


@login_required
def tenant_billing(request):
    """
    Detailed billing statement showing breakdown of rent, water utility, and penalties.
    """
    user = request.user
    lease = Lease.objects.filter(tenant=user, is_active=True).select_related("unit").first()

    if not lease:
        messages.warning(request, "An active lease is required to view billing.")
        return redirect("tenant_dashboard")

    ensure_bills_since_move_in(lease)

    # Get filter parameters
    month_filter = request.GET.get("month", "").strip()
    year_filter = request.GET.get("year", "").strip()

    # Start with all bills for this tenant (include PARTIALLY_PAID)
    bills_query = MonthlyBill.objects.filter(
        lease=lease
    ).exclude(status="PAID").order_by("-billing_month")

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
    for payment in approved_payments:
        bill_id_list = parse_bill_ids(payment.bill_ids)
        if not bill_id_list:
            continue

        bills_paid = MonthlyBill.objects.filter(id__in=bill_id_list)
        
        # Use stored amount if available, otherwise calculate from bills (for old payments)
        if payment.amount and payment.amount > 0:
            total_amount = payment.amount
        else:
            total_amount = sum((bill.total_due or Decimal("0.00")) for bill in bills_paid)

        transactions.append({
            "paid_at": payment.created_at,
            "reference": payment.reference_code,
            "months_paid": bills_paid.count(),
            "total_amount": total_amount,
        })

    # Generate month and year choices
    from django.utils import timezone
    current_year = timezone.now().year
    month_choices = [
        (1, 'January'), (2, 'February'), (3, 'March'), (4, 'April'),
        (5, 'May'), (6, 'June'), (7, 'July'), (8, 'August'),
        (9, 'September'), (10, 'October'), (11, 'November'), (12, 'December')
    ]
    year_choices = list(range(current_year - 3, current_year + 2))  # Last 3 years and next year

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
    })


@login_required
def tenant_pay_advance(request):
    """
    View to handle the Make Payment page.
    Supports partial payments: rent only, water only, or full payment.
    """
    lease = Lease.objects.filter(tenant=request.user, is_active=True).first()

    if not lease:
        messages.warning(request, "An active lease is required to make a payment.")
        return redirect("tenant_dashboard")

    try:
        months_to_pay = int(request.GET.get("months_to_pay", 1))
    except ValueError:
        months_to_pay = 1

    # Get payment type from request (rent_only, water_only, full)
    payment_type = request.GET.get("payment_type", "full")

    ensure_bills_since_move_in(lease)

    today = date.today()
    
    # For partial payments, include bills that have balance for that type
    # Get all bills ordered by month
    all_bills_qs = MonthlyBill.objects.filter(lease=lease).order_by("billing_month")
    
    if payment_type == "rent_only":
        # Filter to bills with unpaid rent, then slice
        bills_with_unpaid_rent = [b for b in all_bills_qs if b.rent_balance > 0]
        bills_to_process = bills_with_unpaid_rent[:months_to_pay]
    elif payment_type == "water_only":
        # Filter to bills with unpaid water, then slice
        bills_with_unpaid_water = [b for b in all_bills_qs if b.water_balance > 0]
        bills_to_process = bills_with_unpaid_water[:months_to_pay]
    else:
        # Full payment - include UNPAID and PARTIALLY_PAID bills (total_balance > 0)
        all_unpaid_qs = MonthlyBill.objects.filter(
            lease=lease, status__in=["UNPAID", "PARTIALLY_PAID"]
        ).order_by("billing_month")
        bills_to_process = list(all_unpaid_qs[:months_to_pay])

    # Count truly unpaid bills for warning
    unpaid_count = MonthlyBill.objects.filter(
        lease=lease, status="UNPAID", due_date__lte=today
    ).count()
    has_pending = unpaid_count > 0

    preview_rows = []
    total_rent = Decimal("0.00")
    total_water = Decimal("0.00")
    total_penalty = Decimal("0.00")
    total_amount = Decimal("0.00")

    for bill in bills_to_process:
        bill = get_or_update_monthly_bill(lease, bill.billing_month)
        
        # Calculate what tenant will actually pay based on payment type
        if payment_type == "rent_only":
            pay_rent = bill.rent_balance
            pay_water = Decimal("0.00")
            pay_penalty = Decimal("0.00")  # Penalty only on full payment
            display_rent = float(pay_rent)
            display_water = 0
        elif payment_type == "water_only":
            pay_rent = Decimal("0.00")
            pay_water = bill.water_balance
            pay_penalty = Decimal("0.00")
            display_rent = 0
            display_water = float(pay_water)
        else:
            # Full payment - pay all remaining balances including interest
            pay_rent = bill.rent_balance
            pay_water = bill.water_balance
            pay_penalty = bill.interest  # Include late interest in full payment
            # For display, show full bill amounts
            display_rent = float(bill.base_rent)
            display_water = float(bill.water_amount or 0)
        
        row = {
            "bill_id": bill.id,
            "month_label": bill.billing_month.strftime("%B %Y"),
            "rent": float(bill.base_rent),
            "water": float(bill.water_amount or 0),
            "penalty": float(bill.interest or 0),
            "pay_rent": float(pay_rent),
            "pay_water": float(pay_water),
            "pay_penalty": float(pay_penalty),
            "pay_total": float(pay_rent + pay_water + pay_penalty),
            "display_rent": display_rent,
            "display_water": display_water,
            "due_date": bill.due_date,
        }
        preview_rows.append(row)

    total_rent = sum(row["display_rent"] if payment_type == "full" else row["pay_rent"] for row in preview_rows)
    total_water = sum(row["display_water"] if payment_type == "full" else row["pay_water"] for row in preview_rows)
    total_penalty = sum(row["pay_penalty"] for row in preview_rows)
    total_amount = sum(row["pay_total"] for row in preview_rows)

    context = {
        "lease": lease,
        "months_options": [1, 2, 3, 4, 5, 6, 12],
        "months_to_pay": months_to_pay,
        "payment_type": payment_type,
        "has_pending": has_pending,
        "unpaid_count": unpaid_count,
        "total_rent": total_rent,
        "total_water": total_water,
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


