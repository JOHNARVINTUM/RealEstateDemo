from datetime import date
from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect
from django.utils import timezone

from announcements.models import Announcement
from .models import Lease, TenantProfile
from billing.models import Payment
from billing.services import month_start, compute_balance_for_lease

@login_required
def tenant_dashboard(request):
    user = request.user

    profile = TenantProfile.objects.filter(user=user).first()
    lease = Lease.objects.filter(tenant=user, is_active=True).select_related("unit").first()

    active_announcements = Announcement.objects.filter(is_active=True).order_by("-created_at")[:5]

    balance_info = None
    payment = None
    payment_history = []

    if lease:
        this_month = month_start(date.today())
        payment = Payment.objects.filter(lease=lease, billing_month=this_month).first()
        balance_info = compute_balance_for_lease(lease, payment_for_month=payment)

        # ✅ Payment history (latest 10)
        payment_history = Payment.objects.filter(lease=lease).order_by("-paid_at", "-billing_month")[:10]

    return render(request, "rentals/tenant_dashboard.html", {
        "profile": profile,
        "lease": lease,
        "announcements": active_announcements,
        "payment": payment,
        "balance": balance_info,
        "payment_history": payment_history,   # ✅ add this
    })

@login_required
def tenant_pay_qr(request):
    """
    MVP: 'QR testing' - tenant inputs a reference string and we mark PAID.
    (No real gateway yet.)
    """
    user = request.user
    lease = Lease.objects.filter(tenant=user, is_active=True).first()
    if not lease:
        return redirect("tenant_dashboard")

    if request.method == "POST":
        ref = request.POST.get("reference", "").strip()
        this_month = month_start(date.today())

        payment, _ = Payment.objects.get_or_create(
            lease=lease,
            billing_month=this_month,
            defaults={"amount_paid": 0}
        )

        # Mark paid for MVP (you can change this to partial/amount input later)
        payment.amount_paid = lease.monthly_rent
        payment.status = "PAID"
        payment.payment_reference = ref
        payment.paid_at = timezone.now()
        payment.save()

        return redirect("tenant_dashboard")

    return render(request, "rentals/tenant_pay_qr.html", {})
