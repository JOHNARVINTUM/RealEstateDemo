from datetime import date
from decimal import Decimal

from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import models
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

        current_balance = MonthlyBill.objects.filter(
            lease=lease,
            status="UNPAID",
        ).order_by("billing_month").first()

        if current_balance:
            current_balance = get_or_update_monthly_bill(lease, current_balance.billing_month)

        today_start = month_start(date.today())
        next_month = add_months(today_start, 1)
        ensure_bills_up_to(lease, next_month)

        next_bill = MonthlyBill.objects.filter(lease=lease, billing_month=next_month).first()
        if next_bill:
            next_billing_month = next_bill.billing_month
            next_due_date = next_bill.due_date

    context = {
        "profile": profile,
        "lease": lease,
        "announcements": announcements,
        "current_balance": current_balance,
        "next_due_date": next_due_date,
        "next_billing_month": next_billing_month,
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

    current_bill = MonthlyBill.objects.filter(
        lease=lease,
        status="UNPAID",
    ).order_by("billing_month").first()

    if current_bill:
        current_bill = get_or_update_monthly_bill(lease, current_bill.billing_month)

    all_bills = MonthlyBill.objects.filter(lease=lease, status="UNPAID").order_by("billing_month")
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

        ongoing_rows.append({
            "month_label": bill.billing_month.strftime("%B %Y"),
            "rent": bill.base_rent,
            "water": bill.water_amount,
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
        total_paid = sum((bill.total_due or Decimal("0.00")) for bill in bills_paid)

        transactions.append({
            "paid_at": payment.created_at,
            "reference": payment.reference_code,
            "months_paid": bills_paid.count(),
            "total_amount": total_paid,
        })

    return render(request, "billing/tenant_billing.html", {
        "lease": lease,
        "current_bill": current_bill,
        "ongoing_rows": ongoing_rows,
        "transactions": transactions,
    })


@login_required
def tenant_pay_advance(request):
    """
    View to handle the Make Payment page.
    It reads the dropdown selection and calculates pending + advance bills.
    """
    lease = Lease.objects.filter(tenant=request.user, is_active=True).first()

    if not lease:
        messages.warning(request, "An active lease is required to make a payment.")
        return redirect("tenant_dashboard")

    try:
        months_to_pay = int(request.GET.get("months_to_pay", 1))
    except ValueError:
        months_to_pay = 1

    ensure_bills_since_move_in(lease)

    today = date.today()
    all_unpaid_qs = MonthlyBill.objects.filter(lease=lease, status="UNPAID").order_by("billing_month")

    unpaid_count = all_unpaid_qs.filter(due_date__lte=today).count()
    has_pending = unpaid_count > 0

    preview_rows = []
    total_amount = Decimal("0.00")
    bills_to_process = list(all_unpaid_qs[:months_to_pay])

    if len(bills_to_process) < months_to_pay:
        if all_unpaid_qs.exists():
            last_month = all_unpaid_qs.last().billing_month
            current_future_month = add_months(last_month, 1)
        else:
            current_future_month = month_start(today)
            if MonthlyBill.objects.filter(
                lease=lease,
                billing_month=current_future_month,
                status="PAID",
            ).exists():
                current_future_month = add_months(current_future_month, 1)

        extra_months = months_to_pay - len(bills_to_process)
        for _ in range(extra_months):
            ensure_bills_up_to(lease, current_future_month)
            future_bill = MonthlyBill.objects.get(lease=lease, billing_month=current_future_month)
            bills_to_process.append(future_bill)
            current_future_month = add_months(current_future_month, 1)

    for bill in bills_to_process:
        bill = get_or_update_monthly_bill(lease, bill.billing_month)
        preview_rows.append({
            "month_label": bill.billing_month.strftime("%B %Y"),
            "rent": bill.base_rent,
            "water": bill.water_amount,
            "penalty": bill.interest,
            "total": bill.total_due,
            "due_date": bill.due_date,
        })
        total_amount += bill.total_due

    context = {
        "lease": lease,
        "months_options": [1, 2, 3, 4, 5, 6, 12],
        "months_to_pay": months_to_pay,
        "has_pending": has_pending,
        "unpaid_count": unpaid_count,
        "total_amount": total_amount,
        "preview_rows": preview_rows,
    }

    if request.method == "POST":
        url = reverse("manual_gcash_payment")
        bill_ids = ",".join(str(bill.id) for bill in bills_to_process if bill.id)
        return redirect(f"{url}?amount={total_amount}&bill_ids={bill_ids}")

    return render(request, "billing/tenant_pay_advance.html", context)


