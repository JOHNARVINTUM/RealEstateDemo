from datetime import date
from decimal import Decimal

from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.shortcuts import render, redirect
from django.utils import timezone

from announcements.models import Announcement
from .models import Lease, TenantProfile

from billing.models import MonthlyBill, PaymentTransaction
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
    user = request.user

    profile = TenantProfile.objects.filter(user=user).first()
    lease = Lease.objects.filter(tenant=user, is_active=True).select_related("unit").first()
    announcements = Announcement.objects.filter(is_active=True).order_by("-created_at")[:5]

    current_bill = None
    next_billing_month = None
    next_due_date = None

    if lease:
        ensure_bills_since_move_in(lease)

        this_month = month_start(date.today())

        # ✅ Show the OLDEST unpaid bill (so tenant sees pending correctly)
        current_bill = (
            MonthlyBill.objects
            .filter(lease=lease, status="UNPAID")
            .order_by("billing_month")
            .first()
        )
        if current_bill:
            current_bill = get_or_update_monthly_bill(lease, current_bill.billing_month)

        # ✅ Next billing month + due date
        next_billing_month = add_months(this_month, 1)
        ensure_bills_up_to(lease, next_billing_month)

        next_bill = MonthlyBill.objects.filter(lease=lease, billing_month=next_billing_month).first()
        if next_bill:
            next_bill = get_or_update_monthly_bill(lease, next_billing_month)
            next_due_date = next_bill.due_date

    return render(
        request,
        "rentals/tenant_dashboard.html",
        {
            "profile": profile,
            "lease": lease,
            "announcements": announcements,
            "current_bill": current_bill,
            "next_billing_month": next_billing_month,
            "next_due_date": next_due_date,
        },
    )


@login_required
def tenant_billing(request):
    user = request.user
    lease = Lease.objects.filter(tenant=user, is_active=True).select_related("unit").first()
    if not lease:
        return redirect("tenant_dashboard")

    ensure_bills_since_move_in(lease)

    this_month = month_start(date.today())

    # ✅ Current bill for this month (still fine for billing page)
    current_bill = MonthlyBill.objects.filter(lease=lease, billing_month=this_month).first()
    if current_bill:
        current_bill = get_or_update_monthly_bill(lease, this_month)

    # ✅ Ongoing billing: unpaid bills up to current month
    ongoing_bills = (
        MonthlyBill.objects
        .filter(lease=lease, status="UNPAID", billing_month__lte=this_month)
        .order_by("billing_month")
    )

    ongoing_rows = []
    for b in ongoing_bills:
        b = get_or_update_monthly_bill(lease, b.billing_month)
        ongoing_rows.append({
            "month_label": b.billing_month.strftime("%B %Y"),
            "rent": b.base_rent,
            "water": b.water_amount,
            "penalty": b.interest,
            "total": b.total_due,
            "due_date": b.due_date,
            "badge": badge_for_bill(b),
        })

    transactions = PaymentTransaction.objects.filter(lease=lease).order_by("-paid_at")

    return render(
        request,
        "billing/tenant_billing.html",
        {
            "lease": lease,
            "current_bill": current_bill,
            "ongoing_rows": ongoing_rows,
            "transactions": transactions,
        },
    )


@login_required
def tenant_pay_advance(request):
    user = request.user
    lease = Lease.objects.filter(tenant=user, is_active=True).select_related("unit").first()
    if not lease:
        return redirect("tenant_dashboard")

    ensure_bills_since_move_in(lease)

    # ✅ Pay button -> redirect to manual GCash page
    if request.method == "POST":
        return redirect("manual_gcash_payment")

    # months_to_pay (1-12) from GET (preview only)
    months_to_pay = int(request.GET.get("months_to_pay", "1"))
    months_to_pay = max(1, min(months_to_pay, 12))

    this_month = month_start(date.today())

    # ✅ Pending = unpaid bills up to current month only
    pending_qs = (
        MonthlyBill.objects
        .filter(lease=lease, status="UNPAID", billing_month__lte=this_month)
        .order_by("billing_month")
    )
    pending_count = pending_qs.count()
    has_pending = pending_count > 0

    # ✅ Preview bills
    if has_pending:
        pay_bills_qs = pending_qs
        months_to_pay_effective = min(months_to_pay, pending_count)
    else:
        target_end_month = add_months(this_month, months_to_pay - 1)
        ensure_bills_up_to(lease, target_end_month)
        pay_bills_qs = (
            MonthlyBill.objects
            .filter(lease=lease, status="UNPAID", billing_month__gte=this_month)
            .order_by("billing_month")
        )
        months_to_pay_effective = months_to_pay

    preview_bills = list(pay_bills_qs[:months_to_pay_effective])

    total_amount = Decimal("0.00")
    preview_rows = []
    for b in preview_bills:
        b = get_or_update_monthly_bill(lease, b.billing_month)
        total_amount += b.total_due
        preview_rows.append({
            "month_label": b.billing_month.strftime("%B %Y"),
            "rent": b.base_rent,
            "water": b.water_amount,
            "penalty": b.interest,
            "total": b.total_due,
            "due_date": b.due_date,
        })

    return render(request, "rentals/tenant_pay_advance.html", {
        "lease": lease,
        "months_to_pay": months_to_pay,
        "months_options": [1, 2, 3, 4, 5, 6, 12],  # ✅ IMPORTANT
        "total_amount": total_amount,
        "has_pending": has_pending,
        "unpaid_count": pending_count,
        "preview_rows": preview_rows,
    })