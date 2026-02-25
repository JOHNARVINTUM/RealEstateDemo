from datetime import date
from decimal import Decimal
from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect
from django.contrib import messages
from django.urls import reverse
from django.conf import settings                           
from django.views.decorators.http import require_http_methods 

# Local app imports
from announcements.models import Announcement
from .models import Lease, TenantProfile
from billing.models import MonthlyBill
from payments.models import ManualPayment                  
from billing.services import (
    month_start,
    add_months,
    ensure_bills_since_move_in,
    ensure_bills_up_to,
    get_or_update_monthly_bill,
    badge_for_bill,
)

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
        # Sync bills from move-in until today to ensure interest is current
        ensure_bills_since_move_in(lease)
        
        # Identify the most urgent unpaid bill for the 'Payment Status' card
        current_balance = MonthlyBill.objects.filter(
            lease=lease, status="UNPAID"
        ).order_by("billing_month").first()
        
        if current_balance:
            # Refresh calculation to ensure 3% weekly interest is accurate
            current_balance = get_or_update_monthly_bill(lease, current_balance.billing_month)

        # Forecasting: Predict next month for the 'Upcoming' sections
        today_start = month_start(date.today())
        next_month = add_months(today_start, 1)
        ensure_bills_up_to(lease, next_month)
        
        nb = MonthlyBill.objects.filter(lease=lease, billing_month=next_month).first()
        if nb:
            next_billing_month = nb.billing_month
            next_due_date = nb.due_date

    context = {
        "profile": profile,
        "lease": lease,
        "announcements": announcements,
        "current_balance": current_balance, # Used for dashboard total: ₱21,915.00
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

    # Refresh data for the 'Ongoing Billing' table
    ensure_bills_since_move_in(lease)
    
    # Identify the 'Current Bill' for the top highlight breakdown card
    current_bill = MonthlyBill.objects.filter(
        lease=lease, 
        status="UNPAID"
    ).order_by("billing_month").first()

    if current_bill:
        current_bill = get_or_update_monthly_bill(lease, current_bill.billing_month)

    # Prepare all rows for the 'Ongoing Billing' table
    all_bills = MonthlyBill.objects.filter(lease=lease, status="UNPAID").order_by("billing_month")
    ongoing_rows = []
    today = date.today()

    for b in all_bills:
        # Refresh dynamic calculations per bill
        b = get_or_update_monthly_bill(lease, b.billing_month)
        
        # Determine status
        if b.due_date < today:
            display_status = "OVERDUE" 
        elif b.due_date == today:
            display_status = "DUE_TODAY"
        else:
            display_status = "UPCOMING"

        # Skip appending if the status is UPCOMING
        if display_status == "UPCOMING":
            continue

        ongoing_rows.append({
            "month_label": b.billing_month.strftime("%B %Y"),
            "rent": b.base_rent,
            "water": b.water_amount,
            "penalty": b.interest,
            "total": b.total_due,
            "due_date": b.due_date,
            "status": display_status,
        })

    # ==========================================
    # NEW LOGIC: Fetch Payment History
    # ==========================================
    approved_payments = ManualPayment.objects.filter(
        user=user, 
        status="APPROVED"
    ).order_by("-created_at")

    transactions = []
    
    for payment in approved_payments:
        if not payment.bill_ids:
            continue
            
        bill_id_list = [bid.strip() for bid in payment.bill_ids.split(",") if bid.strip()]
        bills_paid = MonthlyBill.objects.filter(id__in=bill_id_list)
        total_paid = sum(b.total_due for b in bills_paid)
        
        transactions.append({
            "paid_at": payment.created_at, 
            "reference": payment.reference_code,
            "months_paid": bills_paid.count(),
            "total_amount": total_paid,
        })
    # ==========================================

    return render(request, "billing/tenant_billing.html", {
        "lease": lease,
        "current_bill": current_bill,
        "ongoing_rows": ongoing_rows,
        "transactions": transactions, # Template now receives real data
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
    
    # We need today's date to separate "Due" bills from "Future" bills
    today = date.today()

    # Fetch ALL unpaid bills 
    all_unpaid_qs = MonthlyBill.objects.filter(lease=lease, status="UNPAID").order_by("billing_month")
    
    # Only count bills where the due date is today or in the past
    unpaid_count = all_unpaid_qs.filter(due_date__lte=today).count()
    has_pending = unpaid_count > 0

    preview_rows = []
    total_amount = Decimal("0.00")

    # Gather the bills based on the dropdown selection
    bills_to_process = list(all_unpaid_qs[:months_to_pay])

    # If they select more months than exist in the DB, generate future bills
    if len(bills_to_process) < months_to_pay:
        if all_unpaid_qs.exists():
            last_month = all_unpaid_qs.last().billing_month
            current_future_month = add_months(last_month, 1)
        else:
            current_future_month = month_start(today)
            if MonthlyBill.objects.filter(lease=lease, billing_month=current_future_month, status="PAID").exists():
                current_future_month = add_months(current_future_month, 1)

        extra_months = months_to_pay - len(bills_to_process)
        for _ in range(extra_months):
            ensure_bills_up_to(lease, current_future_month)
            fb = MonthlyBill.objects.get(lease=lease, billing_month=current_future_month)
            bills_to_process.append(fb)
            current_future_month = add_months(current_future_month, 1)

    # Format the rows specifically for your HTML template variables
    for b in bills_to_process:
        b = get_or_update_monthly_bill(lease, b.billing_month)
        preview_rows.append({
            "month_label": b.billing_month.strftime("%B %Y"),
            "rent": b.base_rent,
            "water": b.water_amount,
            "penalty": b.interest,
            "total": b.total_due,
            "due_date": b.due_date,
        })
        total_amount += b.total_due

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
        from django.urls import reverse
        url = reverse("manual_gcash_payment")
        
        # Extract the IDs of the bills they are previewing
        b_ids = ",".join([str(b.id) for b in bills_to_process if b.id])
        
        # Pass BOTH the amount and the bill_ids to the GCash page
        return redirect(f"{url}?amount={total_amount}&bill_ids={b_ids}")

    return render(request, "billing/tenant_pay_advance.html", context)


@login_required
@require_http_methods(["GET", "POST"])
def manual_gcash_payment(request):
    if request.method == "POST":
        # Extract the variables from the hidden form inputs
        reference_code = (request.POST.get("reference_code") or "").strip()
        amount_to_pay = request.POST.get("amount", "0.00")
        bill_ids = request.POST.get("bill_ids", "")

        if not reference_code:
            return render(request, "payments/manual_gcash.html", {
                "error": "GCash reference number is required.",
                "gcash_number": getattr(settings, "GCASH_NUMBER", "09XX-XXX-XXXX"),
                "gcash_name": getattr(settings, "GCASH_NAME", "STA. MARIA REALTY"),
                "amount_to_pay": amount_to_pay,
                "bill_ids": bill_ids,
            })

        # Save the transaction securely with the bill_ids included
        ManualPayment.objects.create(
            user=request.user,
            reference_code=reference_code,
            bill_ids=bill_ids,  
        )
        
        # Show a success message on the dashboard after submission
        messages.success(request, "Payment submitted! Please wait for admin verification.")
        return redirect("tenant_dashboard")

    # For the initial page load (GET request)
    amount_to_pay = request.GET.get("amount", "0.00")
    bill_ids = request.GET.get("bill_ids", "")

    return render(request, "payments/manual_gcash.html", {
        "gcash_number": getattr(settings, "GCASH_NUMBER", "09XX-XXX-XXXX"),
        "gcash_name": getattr(settings, "GCASH_NAME", "STA. MARIA REALTY"),
        "amount_to_pay": amount_to_pay,
        "bill_ids": bill_ids, 
    })