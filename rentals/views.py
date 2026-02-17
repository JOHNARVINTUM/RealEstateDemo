from datetime import date
from decimal import Decimal

from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect
from django.utils import timezone
from django.db import transaction
from django.db.models import Q

from announcements.models import Announcement
from .models import Lease, TenantProfile
from billing.models import Payment, PaymentTransaction
from billing.services import (
    month_start,
    add_months,
    ensure_payments_since_move_in,
    ensure_payments_up_to,
    compute_balance_for_month
)


@login_required
def tenant_dashboard(request):
    user = request.user

    profile = TenantProfile.objects.filter(user=user).first()
    lease = Lease.objects.filter(
        tenant=user,
        is_active=True
    ).select_related("unit").first()

    announcements = Announcement.objects.filter(
        is_active=True
    ).order_by("-created_at")[:5]

    payment_history = Payment.objects.none()
    current_month_payment = None
    current_balance = None

    if lease:
        # Ensure monthly Payment rows exist from move-in up to current month
        ensure_payments_since_move_in(lease)

        this_month = month_start(date.today())

        # Current month bill
        current_month_payment = Payment.objects.filter(
            lease=lease,
            billing_month=this_month
        ).first()

        if current_month_payment:
            current_balance = compute_balance_for_month(
                lease,
                current_month_payment
            )

        # ✅ HISTORY LOGIC:
        # Show:
        # - All months up to current month
        # - Any future months that are already PAID (advance payments)
        # Hide:
        # - Future months that are still PENDING
        payment_history = (
            Payment.objects
            .filter(lease=lease)
            .filter(
                Q(billing_month__lte=this_month) |
                Q(status="PAID")
            )
            .order_by("-billing_month")
        )

    return render(request, "rentals/tenant_dashboard.html", {
        "profile": profile,
        "lease": lease,
        "announcements": announcements,
        "current_payment": current_month_payment,
        "current_balance": current_balance,
        "payment_history": payment_history,
    })


@login_required
def tenant_pay_advance(request):
    user = request.user
    lease = Lease.objects.filter(
        tenant=user,
        is_active=True
    ).select_related("unit").first()

    if not lease:
        return redirect("tenant_dashboard")

    # Ensure months exist up to current month
    ensure_payments_since_move_in(lease)

    months_to_pay = int(request.GET.get("months_to_pay", "1"))

    if months_to_pay < 1:
        months_to_pay = 1
    if months_to_pay > 12:
        months_to_pay = 12

    # Ensure future months exist for advance payment preview
    target_end_month = add_months(
        month_start(date.today()),
        months_to_pay - 1
    )
    ensure_payments_up_to(lease, target_end_month)

    unpaid_qs = (
        Payment.objects
        .filter(lease=lease)
        .exclude(status="PAID")
        .order_by("billing_month")
    )

    preview_months = list(unpaid_qs[:months_to_pay])
    total_amount = Decimal("0.00")
    breakdown = []

    for p in preview_months:
        bal = compute_balance_for_month(lease, p)
        total_amount += bal["total_due"]

        breakdown.append({
            "payment": p,
            "total_due": bal["total_due"],
            "is_late": bal["is_late"],
            "interest": bal["interest"],
        })

    # Confirm payment
    if request.method == "POST":
        ref = request.POST.get("reference", "").strip()
        months_to_pay_post = int(
            request.POST.get("months_to_pay", str(months_to_pay))
        )

        if not ref:
            return render(request, "rentals/tenant_pay_advance.html", {
                "lease": lease,
                "months_to_pay": months_to_pay,
                "breakdown": breakdown,
                "total_amount": total_amount,
                "error": "Reference number is required.",
            })

        if months_to_pay_post < 1:
            months_to_pay_post = 1
        if months_to_pay_post > 12:
            months_to_pay_post = 12

        target_end_month = add_months(
            month_start(date.today()),
            months_to_pay_post - 1
        )
        ensure_payments_up_to(lease, target_end_month)

        with transaction.atomic():
            unpaid_locked = (
                Payment.objects
                .select_for_update()
                .filter(lease=lease)
                .exclude(status="PAID")
                .order_by("billing_month")
            )

            months = list(unpaid_locked[:months_to_pay_post])

            if not months:
                return redirect("tenant_dashboard")

            total = Decimal("0.00")

            for p in months:
                bal = compute_balance_for_month(lease, p)

                p.amount_paid = bal["total_due"]
                p.status = "PAID"
                p.payment_reference = ref
                p.paid_at = timezone.now()
                p.save()

                total += bal["total_due"]

            PaymentTransaction.objects.create(
                lease=lease,
                reference=ref,
                months_paid=len(months),
                total_amount=total,
            )

        return redirect("tenant_dashboard")

    return render(request, "rentals/tenant_pay_advance.html", {
        "lease": lease,
        "months_to_pay": months_to_pay,
        "breakdown": breakdown,
        "total_amount": total_amount,
    })
