from datetime import date
from decimal import Decimal

from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect
from django.utils import timezone
from django.db import transaction

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

    this_month = month_start(date.today())
    current_bill = None

    if lease:
        ensure_bills_since_move_in(lease)

        current_bill = MonthlyBill.objects.filter(
            lease=lease,
            billing_month=this_month
        ).first()

        if current_bill:
            # update totals (water/interest) and keep fresh
            current_bill = get_or_update_monthly_bill(lease, this_month)

    return render(request, "rentals/tenant_dashboard.html", {
        "profile": profile,
        "lease": lease,
        "announcements": announcements,
        "current_bill": current_bill,
    })


@login_required
def tenant_billing(request):
    user = request.user
    lease = Lease.objects.filter(tenant=user, is_active=True).select_related("unit").first()
    if not lease:
        return redirect("tenant_dashboard")

    ensure_bills_since_move_in(lease)

    this_month = month_start(date.today())

    current_bill = MonthlyBill.objects.filter(
        lease=lease,
        billing_month=this_month
    ).first()
    if current_bill:
        current_bill = get_or_update_monthly_bill(lease, this_month)

    # ✅ ONGOING BILLING = unpaid bills up to current month only
    ongoing_bills = (
        MonthlyBill.objects
        .filter(lease=lease, status="UNPAID", billing_month__lte=this_month)
        .order_by("billing_month")
    )

    ongoing_rows = []
    for b in ongoing_bills:
        # keep each row fresh
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

    # ✅ PAYMENT HISTORY = real transactions only
    transactions = PaymentTransaction.objects.filter(lease=lease).order_by("-paid_at")

    return render(request, "billing/tenant_billing.html", {
        "lease": lease,
        "current_bill": current_bill,
        "ongoing_rows": ongoing_rows,
        "transactions": transactions,
    })


@login_required
def tenant_pay_advance(request):
    user = request.user
    lease = Lease.objects.filter(tenant=user, is_active=True).select_related("unit").first()
    if not lease:
        return redirect("tenant_dashboard")

    ensure_bills_since_move_in(lease)

    months_to_pay = int(request.GET.get("months_to_pay", "1"))
    months_to_pay = max(1, min(months_to_pay, 12))

    target_end_month = add_months(month_start(date.today()), months_to_pay - 1)
    ensure_bills_up_to(lease, target_end_month)

    # Pay the oldest UNPAID months first
    unpaid_qs = (
        MonthlyBill.objects
        .filter(lease=lease, status="UNPAID")
        .order_by("billing_month")
    )

    preview_bills = list(unpaid_qs[:months_to_pay])
    total_amount = Decimal("0.00")

    for b in preview_bills:
        b = get_or_update_monthly_bill(lease, b.billing_month)
        total_amount += b.total_due

    if request.method == "POST":
        ref = request.POST.get("reference", "").strip()
        months_to_pay_post = int(request.POST.get("months_to_pay", str(months_to_pay)))
        months_to_pay_post = max(1, min(months_to_pay_post, 12))

        if not ref:
            return render(request, "rentals/tenant_pay_advance.html", {
                "lease": lease,
                "months_to_pay": months_to_pay,
                "total_amount": total_amount,
                "error": "Reference number is required.",
            })

        target_end_month = add_months(month_start(date.today()), months_to_pay_post - 1)
        ensure_bills_up_to(lease, target_end_month)

        with transaction.atomic():
            bills_locked = (
                MonthlyBill.objects.select_for_update()
                .filter(lease=lease, status="UNPAID")
                .order_by("billing_month")
            )
            to_pay = list(bills_locked[:months_to_pay_post])

            if not to_pay:
                return redirect("tenant_dashboard")

            total_paid = Decimal("0.00")
            now = timezone.now()

            for b in to_pay:
                b = get_or_update_monthly_bill(lease, b.billing_month)
                b.status = "PAID"
                b.paid_at = now
                b.payment_reference = ref
                b.save(update_fields=["status", "paid_at", "payment_reference"])
                total_paid += b.total_due

            PaymentTransaction.objects.create(
                lease=lease,
                reference=ref,
                months_paid=len(to_pay),
                total_amount=total_paid,
            )

        return redirect("tenant_dashboard")

    return render(request, "rentals/tenant_pay_advance.html", {
        "lease": lease,
        "months_to_pay": months_to_pay,
        "total_amount": total_amount,
    })
